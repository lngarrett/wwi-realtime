"""Tests for media tagging."""

import sqlite3
from datetime import date

import pytest

from wwi_realtime.media.tagger import (
    MediaItem,
    MediaTag,
    tag_by_keywords,
    tag_by_date,
    tag_by_location,
    tag_media_item,
    get_best_tags,
    save_media_tags,
    tag_media_batch,
)


@pytest.fixture
def test_db():
    """Create test database with events and arcs."""
    conn = sqlite3.connect(":memory:")

    # Create arcs table
    conn.execute("""
        CREATE TABLE arcs (
            id TEXT PRIMARY KEY,
            title TEXT
        )
    """)

    # Create events table
    conn.execute("""
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            title TEXT,
            date DATE,
            arc_id TEXT
        )
    """)

    # Add test arcs
    arcs = [
        ("western_front", "Western Front"),
        ("verdun", "Battle of Verdun"),
        ("somme", "Battle of the Somme"),
        ("eastern_front", "Eastern Front"),
    ]
    conn.executemany("INSERT INTO arcs VALUES (?, ?)", arcs)

    # Add test events
    events = [
        ("e1", "Battle of Verdun Begins", "1916-02-21", "verdun"),
        ("e2", "First Day of the Somme", "1916-07-01", "somme"),
        ("e3", "Somme Offensive Continues", "1916-07-02", "somme"),
        ("e4", "Action on the Western Front", "1916-07-03", "western_front"),
    ]
    conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", events)

    conn.commit()
    return conn


class TestTagByKeywords:
    """Tests for keyword-based tagging."""

    def test_tag_verdun_keyword(self):
        """Test tagging content with Verdun keyword."""
        content = "The battle at Verdun continues with heavy losses."
        matches = tag_by_keywords(content)

        assert len(matches) >= 1
        arc_ids = [m[0] for m in matches]
        assert "verdun" in arc_ids

    def test_tag_multiple_keywords(self):
        """Test tagging with multiple keywords."""
        content = "German forces on the Western Front near Ypres."
        matches = tag_by_keywords(content)

        arc_ids = [m[0] for m in matches]
        assert "western_front" in arc_ids

    def test_tag_naval_keywords(self):
        """Test tagging naval content."""
        content = "A German submarine attacked the convoy."
        matches = tag_by_keywords(content)

        arc_ids = [m[0] for m in matches]
        assert "uboat_campaign" in arc_ids

    def test_no_keywords(self):
        """Test content with no matching keywords."""
        content = "The weather remained pleasant throughout the day."
        matches = tag_by_keywords(content)

        assert len(matches) == 0


class TestTagByDate:
    """Tests for date-based tagging."""

    def test_exact_date_match(self, test_db):
        """Test finding events on exact date."""
        matches = tag_by_date(date(1916, 7, 1), test_db)

        event_ids = [m[0] for m in matches]
        assert "e2" in event_ids

        # Should have high confidence for exact match
        for event_id, conf in matches:
            if event_id == "e2":
                assert conf == 1.0

    def test_nearby_date_match(self, test_db):
        """Test finding events on nearby dates."""
        # Day after Somme start
        matches = tag_by_date(date(1916, 7, 2), test_db)

        event_ids = [m[0] for m in matches]
        # Should find July 1 event with lower confidence
        assert "e2" in event_ids or "e3" in event_ids

    def test_no_events_on_date(self, test_db):
        """Test date with no events."""
        matches = tag_by_date(date(1915, 1, 1), test_db)

        # May still find nearby events, but with low confidence
        for _, conf in matches:
            assert conf < 1.0


class TestTagByLocation:
    """Tests for location-based tagging."""

    def test_tag_location_verdun(self, test_db):
        """Test tagging by Verdun location."""
        content = "Troops were stationed near Verdun."
        matches = tag_by_location(content, test_db)

        arc_ids = [m[0] for m in matches]
        assert "verdun" in arc_ids

    def test_tag_location_flanders(self, test_db):
        """Test tagging by Flanders location."""
        content = "Fighting in Flanders was fierce."
        matches = tag_by_location(content, test_db)

        arc_ids = [m[0] for m in matches]
        assert "western_front" in arc_ids


class TestTagMediaItem:
    """Tests for full media item tagging."""

    def test_tag_newspaper_article(self, test_db):
        """Test tagging a newspaper article."""
        item = MediaItem(
            id="article1",
            content="Heavy fighting continues at Verdun. French troops hold the line.",
            date=date(1916, 2, 21),
            source="The Times",
        )

        tags = tag_media_item(item, test_db)

        assert len(tags) > 0
        # Should have verdun arc
        arc_ids = [t.arc_id for t in tags]
        assert "verdun" in arc_ids

    def test_tag_with_event_link(self, test_db):
        """Test that date matching links to events."""
        item = MediaItem(
            id="article2",
            content="Major offensive begins on the Somme.",
            date=date(1916, 7, 1),
        )

        tags = tag_media_item(item, test_db)

        # Should have at least one tag with event_id
        event_tags = [t for t in tags if t.event_id]
        assert len(event_tags) > 0

    def test_tag_content_only(self, test_db):
        """Test tagging by content only (no date)."""
        item = MediaItem(
            id="article3",
            content="The submarine menace threatens shipping.",
            date=None,
        )

        tags = tag_media_item(item, test_db)

        # Should still find tags by keyword
        assert len(tags) > 0
        arc_ids = [t.arc_id for t in tags]
        assert "uboat_campaign" in arc_ids


class TestGetBestTags:
    """Tests for selecting best tags."""

    def test_get_best_limits_count(self):
        """Test that get_best_tags limits count."""
        tags = [
            MediaTag("m1", arc_id="arc1", confidence=0.9),
            MediaTag("m1", arc_id="arc2", confidence=0.8),
            MediaTag("m1", arc_id="arc3", confidence=0.7),
            MediaTag("m1", arc_id="arc4", confidence=0.6),
        ]

        best = get_best_tags(tags, max_tags=2)

        assert len(best) == 2

    def test_prefers_event_tags(self):
        """Test that tags with events are preferred."""
        tags = [
            MediaTag("m1", arc_id="arc1", confidence=0.9),
            MediaTag("m1", arc_id="arc2", event_id="e1", confidence=0.7),
        ]

        best = get_best_tags(tags, max_tags=1)

        # Should prefer the one with event_id despite lower confidence
        assert best[0].event_id == "e1"

    def test_dedupes_arcs(self):
        """Test that arcs are deduplicated."""
        tags = [
            MediaTag("m1", arc_id="arc1", confidence=0.9, match_reason="keyword"),
            MediaTag("m1", arc_id="arc1", confidence=0.7, match_reason="location"),
            MediaTag("m1", arc_id="arc2", confidence=0.8),
        ]

        best = get_best_tags(tags, max_tags=3)

        # Should only have each arc once
        arc_ids = [t.arc_id for t in best]
        assert len(arc_ids) == len(set(arc_ids))


class TestSaveMediaTags:
    """Tests for saving tags to database."""

    def test_save_creates_table(self, test_db):
        """Test that save creates the media_tags table."""
        tags = [
            MediaTag("m1", arc_id="western_front", confidence=0.9),
        ]

        count = save_media_tags(test_db, tags)

        assert count == 1

        # Verify table exists
        cursor = test_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='media_tags'"
        )
        assert cursor.fetchone() is not None

    def test_save_multiple_tags(self, test_db):
        """Test saving multiple tags."""
        tags = [
            MediaTag("m1", arc_id="western_front", confidence=0.9),
            MediaTag("m1", arc_id="verdun", event_id="e1", confidence=0.8),
            MediaTag("m2", arc_id="somme", confidence=0.7),
        ]

        count = save_media_tags(test_db, tags)

        assert count == 3

        # Verify all saved
        cursor = test_db.execute("SELECT COUNT(*) FROM media_tags")
        assert cursor.fetchone()[0] == 3


class TestTagMediaBatch:
    """Tests for batch tagging."""

    def test_batch_tagging(self, test_db):
        """Test tagging a batch of media items."""
        items = [
            MediaItem(
                id="a1",
                content="Battle at Verdun continues.",
                date=date(1916, 2, 21),
            ),
            MediaItem(
                id="a2",
                content="Somme offensive begins.",
                date=date(1916, 7, 1),
            ),
            MediaItem(
                id="a3",
                content="Local weather report.",  # No war content
                date=date(1916, 5, 1),
            ),
        ]

        stats = tag_media_batch(items, test_db)

        assert stats["total"] == 3
        assert stats["tagged"] >= 2  # At least war-related items tagged
        assert stats["tags_created"] > 0

    def test_batch_stats(self, test_db):
        """Test batch statistics are accurate."""
        items = [
            MediaItem(id="a1", content="Verdun", date=None),
        ]

        stats = tag_media_batch(items, test_db, max_tags_per_item=2)

        assert stats["total"] == 1
        assert stats["tagged"] == 1
        assert stats["tags_created"] <= 2  # Respects max
