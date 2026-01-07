"""Tag media with arc and event IDs.

Links newspaper articles and other media to narrative arcs and events
based on content, date, and extracted entities.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from wwi_realtime.media.entities import extract_locations, extract_persons, EntityType
from wwi_realtime.media.newspapers import extract_quotes, find_war_related_content


@dataclass
class MediaTag:
    """A tag linking media to an arc or event."""
    media_id: str
    arc_id: str | None = None
    event_id: str | None = None
    confidence: float = 1.0
    match_reason: str | None = None


@dataclass
class MediaItem:
    """A media item to be tagged."""
    id: str
    content: str
    date: date | None = None
    source: str | None = None  # e.g., newspaper name
    type: str = "newspaper"  # newspaper, photo, poster


# Keywords that map to specific arcs (similar to migrate_events)
ARC_KEYWORDS = {
    "verdun": "verdun",
    "somme": "somme",
    "passchendaele": "passchendaele",
    "ypres": "western_front",
    "marne": "first_marne",
    "tannenberg": "tannenberg",
    "gallipoli": "gallipoli",
    "dardanelles": "gallipoli",
    "jutland": "jutland",
    "isonzo": "isonzo_battles",
    "caporetto": "caporetto",
    "brusilov": "brusilov_offensive",

    # Theaters
    "western front": "western_front",
    "eastern front": "eastern_front",
    "belgium": "western_front",
    "flanders": "western_front",
    "france": "western_front",
    "russia": "eastern_front",
    "galicia": "eastern_front",
    "italy": "italian_front",
    "mesopotamia": "mesopotamian_campaign",
    "palestine": "sinai_palestine",
    "africa": "african_theatre",

    # Naval
    "submarine": "uboat_campaign",
    "u-boat": "uboat_campaign",
    "naval": "naval_warfare",
    "fleet": "naval_warfare",
    "battleship": "naval_warfare",
}


def tag_by_keywords(content: str) -> list[tuple[str, float]]:
    """Find arc matches based on keywords in content.

    Args:
        content: Text content to search

    Returns:
        List of (arc_id, confidence) tuples
    """
    content_lower = content.lower()
    matches = []

    for keyword, arc_id in ARC_KEYWORDS.items():
        if keyword in content_lower:
            # Higher confidence for longer/more specific keywords
            confidence = min(1.0, 0.5 + len(keyword) * 0.05)
            matches.append((arc_id, confidence))

    # Deduplicate by arc_id, keeping highest confidence
    arc_scores = {}
    for arc_id, conf in matches:
        if arc_id not in arc_scores or conf > arc_scores[arc_id]:
            arc_scores[arc_id] = conf

    return list(arc_scores.items())


def tag_by_date(
    media_date: date,
    conn: sqlite3.Connection,
) -> list[tuple[str, float]]:
    """Find events on or near the media date.

    Args:
        media_date: Date of the media
        conn: Database connection

    Returns:
        List of (event_id, confidence) tuples
    """
    matches = []

    # Exact date match
    cursor = conn.execute(
        "SELECT id FROM events WHERE date = ?",
        (media_date.isoformat(),)
    )
    for row in cursor.fetchall():
        matches.append((row[0], 1.0))

    # Within 3 days (newspapers often report on recent events)
    for delta in [1, 2, 3]:
        for direction in [-1, 1]:
            check_date = media_date + timedelta(days=delta * direction)
            cursor = conn.execute(
                "SELECT id FROM events WHERE date = ?",
                (check_date.isoformat(),)
            )
            for row in cursor.fetchall():
                # Lower confidence for non-exact dates
                confidence = 1.0 - (delta * 0.15)
                matches.append((row[0], confidence))

    return matches


def tag_by_location(
    content: str,
    conn: sqlite3.Connection,
) -> list[tuple[str, float]]:
    """Find arc matches based on extracted locations.

    Args:
        content: Text content
        conn: Database connection

    Returns:
        List of (arc_id, confidence) tuples
    """
    locations = extract_locations(content)
    matches = []

    for loc in locations:
        loc_lower = loc.text.lower()

        # Check if location matches any arc keywords
        for keyword, arc_id in ARC_KEYWORDS.items():
            if keyword in loc_lower or loc_lower in keyword:
                matches.append((arc_id, 0.7))

    return matches


def tag_media_item(
    item: MediaItem,
    conn: sqlite3.Connection,
) -> list[MediaTag]:
    """Tag a single media item with arcs and events.

    Args:
        item: Media item to tag
        conn: Database connection

    Returns:
        List of MediaTag objects
    """
    tags = []

    # 1. Tag by keywords in content
    keyword_matches = tag_by_keywords(item.content)
    for arc_id, conf in keyword_matches:
        tags.append(MediaTag(
            media_id=item.id,
            arc_id=arc_id,
            confidence=conf,
            match_reason="keyword",
        ))

    # 2. Tag by date (if available)
    if item.date:
        date_matches = tag_by_date(item.date, conn)
        for event_id, conf in date_matches:
            # Get event's arc_id
            cursor = conn.execute(
                "SELECT arc_id FROM events WHERE id = ?",
                (event_id,)
            )
            row = cursor.fetchone()
            arc_id = row[0] if row else None

            tags.append(MediaTag(
                media_id=item.id,
                event_id=event_id,
                arc_id=arc_id,
                confidence=conf,
                match_reason="date",
            ))

    # 3. Tag by extracted locations
    location_matches = tag_by_location(item.content, conn)
    for arc_id, conf in location_matches:
        # Only add if not already tagged with this arc
        if not any(t.arc_id == arc_id for t in tags):
            tags.append(MediaTag(
                media_id=item.id,
                arc_id=arc_id,
                confidence=conf,
                match_reason="location",
            ))

    # Sort by confidence
    tags.sort(key=lambda t: t.confidence, reverse=True)

    return tags


def get_best_tags(tags: list[MediaTag], max_tags: int = 3) -> list[MediaTag]:
    """Get the best tags for a media item.

    Args:
        tags: All tags
        max_tags: Maximum number to return

    Returns:
        Best tags by confidence
    """
    # Prefer tags with both arc_id and event_id
    with_event = [t for t in tags if t.event_id]
    without_event = [t for t in tags if not t.event_id]

    result = []

    # Add best event-linked tags first
    for tag in with_event[:max_tags]:
        result.append(tag)

    # Fill remaining with arc-only tags
    remaining = max_tags - len(result)
    if remaining > 0:
        # Dedupe by arc_id
        seen_arcs = {t.arc_id for t in result}
        for tag in without_event:
            if tag.arc_id not in seen_arcs:
                result.append(tag)
                seen_arcs.add(tag.arc_id)
                if len(result) >= max_tags:
                    break

    return result


def save_media_tags(
    conn: sqlite3.Connection,
    tags: list[MediaTag],
) -> int:
    """Save media tags to database.

    Args:
        conn: Database connection
        tags: Tags to save

    Returns:
        Number of tags saved
    """
    # Create table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS media_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id TEXT NOT NULL,
            arc_id TEXT,
            event_id TEXT,
            confidence REAL,
            match_reason TEXT,
            FOREIGN KEY (arc_id) REFERENCES arcs(id),
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    """)

    count = 0
    for tag in tags:
        conn.execute(
            """INSERT INTO media_tags (media_id, arc_id, event_id, confidence, match_reason)
               VALUES (?, ?, ?, ?, ?)""",
            (tag.media_id, tag.arc_id, tag.event_id, tag.confidence, tag.match_reason)
        )
        count += 1

    conn.commit()
    return count


def tag_media_batch(
    items: list[MediaItem],
    conn: sqlite3.Connection,
    max_tags_per_item: int = 3,
) -> dict:
    """Tag a batch of media items.

    Args:
        items: Media items to tag
        conn: Database connection
        max_tags_per_item: Max tags per item

    Returns:
        Statistics dict
    """
    stats = {
        "total": len(items),
        "tagged": 0,
        "untagged": 0,
        "tags_created": 0,
    }

    all_tags = []

    for item in items:
        tags = tag_media_item(item, conn)
        best_tags = get_best_tags(tags, max_tags_per_item)

        if best_tags:
            stats["tagged"] += 1
            stats["tags_created"] += len(best_tags)
            all_tags.extend(best_tags)
        else:
            stats["untagged"] += 1

    if all_tags:
        save_media_tags(conn, all_tags)

    return stats
