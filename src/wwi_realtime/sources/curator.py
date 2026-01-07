"""Curator module for managing canonical sources.

This module handles loading, storing, and querying the curated list of
WWI primary sources (memoirs, diaries, letters).
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CanonicalSource:
    """A curated primary source for WWI content."""
    id: str
    title: str
    author: str
    author_info: str | None = None
    type: str | None = None  # memoir, diary, letters, novel, etc.
    perspective: str | None = None  # german, british, french, american, etc.
    gutenberg_id: str | None = None
    internet_archive_id: str | None = None
    priority: int = 5  # 1 = highest
    notes: str | None = None
    coverage_arcs: list[str] | None = None
    coverage_events: list[str] | None = None
    coverage_topics: list[str] | None = None


def load_canonical_sources(path: Path | str | None = None) -> list[CanonicalSource]:
    """Load canonical sources from JSON file.

    Args:
        path: Path to JSON file. Defaults to data/canonical_sources.json

    Returns:
        List of CanonicalSource objects
    """
    if path is None:
        path = Path("data/canonical_sources.json")
    else:
        path = Path(path)

    with open(path) as f:
        data = json.load(f)

    sources = []
    for s in data.get("sources", []):
        coverage = s.get("coverage", {})
        source = CanonicalSource(
            id=s["id"],
            title=s["title"],
            author=s["author"],
            author_info=s.get("author_info"),
            type=s.get("type"),
            perspective=s.get("perspective"),
            gutenberg_id=s.get("gutenberg_id"),
            internet_archive_id=s.get("internet_archive_id"),
            priority=s.get("priority", 5),
            notes=s.get("notes"),
            coverage_arcs=coverage.get("arcs"),
            coverage_events=coverage.get("events"),
            coverage_topics=coverage.get("topics"),
        )
        sources.append(source)

    return sources


def populate_sources_table(conn: sqlite3.Connection, sources: list[CanonicalSource]) -> int:
    """Populate the canonical_sources table from a list of sources.

    Args:
        conn: Database connection
        sources: List of CanonicalSource objects

    Returns:
        Number of sources inserted/updated
    """
    count = 0
    for source in sources:
        # Check if source has a Gutenberg ID or IA ID
        available = bool(source.gutenberg_id or source.internet_archive_id)

        conn.execute(
            """INSERT OR REPLACE INTO canonical_sources
            (id, title, author, author_info, type, perspective,
             gutenberg_id, internet_archive_id, available, priority, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source.id,
                source.title,
                source.author,
                source.author_info,
                source.type,
                source.perspective,
                source.gutenberg_id,
                source.internet_archive_id,
                available,
                source.priority,
                source.notes,
            )
        )

        # Add coverage mappings for topics (arcs added later when arcs exist)
        # Skip arc mappings for now - they'll be added in source_coverage_mappings step
        if source.coverage_topics:
            for topic in source.coverage_topics:
                conn.execute(
                    """INSERT OR IGNORE INTO source_coverage
                    (source_id, topic) VALUES (?, ?)""",
                    (source.id, topic)
                )

        count += 1

    conn.commit()
    return count


def get_available_sources(conn: sqlite3.Connection, priority_max: int = 5) -> list[dict]:
    """Get all available sources up to a given priority.

    Args:
        conn: Database connection
        priority_max: Maximum priority to include (1 = highest priority only)

    Returns:
        List of source dictionaries
    """
    cursor = conn.execute(
        """SELECT id, title, author, type, perspective,
                  gutenberg_id, internet_archive_id, priority, ingested
           FROM canonical_sources
           WHERE available = 1 AND priority <= ?
           ORDER BY priority, title""",
        (priority_max,)
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_sources_for_arc(conn: sqlite3.Connection, arc_id: str) -> list[dict]:
    """Get sources that cover a specific arc.

    Args:
        conn: Database connection
        arc_id: Arc ID to search for

    Returns:
        List of source dictionaries
    """
    cursor = conn.execute(
        """SELECT DISTINCT cs.id, cs.title, cs.author, cs.type, cs.perspective
           FROM canonical_sources cs
           JOIN source_coverage sc ON cs.id = sc.source_id
           WHERE sc.arc_id = ? AND cs.available = 1
           ORDER BY cs.priority""",
        (arc_id,)
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def populate_arc_coverage(conn: sqlite3.Connection, sources: list[CanonicalSource] | None = None) -> int:
    """Populate source-to-arc coverage mappings.

    Should be called after arcs table is populated.

    Args:
        conn: Database connection
        sources: List of sources (loads from JSON if None)

    Returns:
        Number of mappings created
    """
    if sources is None:
        sources = load_canonical_sources()

    count = 0
    for source in sources:
        if source.coverage_arcs:
            for arc_id in source.coverage_arcs:
                # Check if arc exists
                cursor = conn.execute(
                    "SELECT id FROM arcs WHERE id = ?", (arc_id,)
                )
                if cursor.fetchone():
                    conn.execute(
                        """INSERT OR IGNORE INTO source_coverage
                        (source_id, arc_id) VALUES (?, ?)""",
                        (source.id, arc_id)
                    )
                    count += 1

        if source.coverage_events:
            for event_id in source.coverage_events:
                conn.execute(
                    """INSERT OR IGNORE INTO source_coverage
                    (source_id, event_id) VALUES (?, ?)""",
                    (source.id, event_id)
                )
                count += 1

    conn.commit()
    return count


def get_coverage_stats(conn: sqlite3.Connection) -> dict:
    """Get statistics about source coverage mappings."""
    stats = {}

    cursor = conn.execute(
        "SELECT COUNT(DISTINCT source_id) FROM source_coverage WHERE arc_id IS NOT NULL"
    )
    stats["sources_with_arc"] = cursor.fetchone()[0]

    cursor = conn.execute(
        "SELECT COUNT(DISTINCT source_id) FROM source_coverage WHERE topic IS NOT NULL"
    )
    stats["sources_with_topic"] = cursor.fetchone()[0]

    cursor = conn.execute(
        "SELECT arc_id, COUNT(*) as cnt FROM source_coverage WHERE arc_id IS NOT NULL GROUP BY arc_id ORDER BY cnt DESC"
    )
    stats["arcs_coverage"] = {row[0]: row[1] for row in cursor.fetchall()}

    cursor = conn.execute(
        "SELECT topic, COUNT(*) as cnt FROM source_coverage WHERE topic IS NOT NULL GROUP BY topic ORDER BY cnt DESC LIMIT 10"
    )
    stats["top_topics"] = {row[0]: row[1] for row in cursor.fetchall()}

    return stats


def get_sources_for_topic(conn: sqlite3.Connection, topic: str) -> list[dict]:
    """Get sources that cover a specific topic.

    Args:
        conn: Database connection
        topic: Topic to search for

    Returns:
        List of source dictionaries
    """
    cursor = conn.execute(
        """SELECT DISTINCT cs.id, cs.title, cs.author, cs.type, cs.perspective
           FROM canonical_sources cs
           JOIN source_coverage sc ON cs.id = sc.source_id
           WHERE sc.topic = ? AND cs.available = 1
           ORDER BY cs.priority""",
        (topic,)
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
