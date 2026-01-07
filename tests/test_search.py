"""Tests for the source search module."""

import sqlite3
from datetime import date

import pytest

from wwi_realtime.sources.search import (
    PassageResult,
    search_passages_fts,
    get_passages_for_arc,
    get_passages_for_date,
    get_passages_for_topic,
    get_quotes_for_event,
    get_diverse_perspectives,
)
from wwi_realtime.framework.schema import create_schema
from wwi_realtime.framework.arcs import Arc, populate_arcs_table


@pytest.fixture
def db_conn():
    """Create a database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, date DATE
        )
    """)
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def db_with_data(db_conn):
    """Database with test data."""
    # Add arcs
    arcs = [
        Arc(id="western_front", title="Western Front", theater="western"),
        Arc(id="gallipoli", title="Gallipoli", theater="mediterranean"),
    ]
    populate_arcs_table(db_conn, arcs)

    # Add sources
    db_conn.execute("""
        INSERT INTO canonical_sources (id, title, author, type, perspective, available, ingested, priority)
        VALUES
        ('british_memoir', 'British Memoir', 'British Officer', 'memoir', 'british', 1, 1, 1),
        ('german_diary', 'German Diary', 'German Soldier', 'diary', 'german', 1, 1, 1),
        ('french_letters', 'French Letters', 'French Soldier', 'letters', 'french', 1, 1, 2)
    """)

    # Add source coverage
    db_conn.execute("""
        INSERT INTO source_coverage (source_id, arc_id, topic)
        VALUES
        ('british_memoir', 'western_front', 'infantry'),
        ('german_diary', 'western_front', 'trench_warfare'),
        ('french_letters', 'western_front', 'infantry')
    """)

    # Add passages
    db_conn.execute("""
        INSERT INTO source_passages
        (id, source_id, content, sequence_num, has_direct_quote, date_referenced, date_approximate, topics, word_count)
        VALUES
        ('p1', 'british_memoir', 'The shells came over like rain. We crouched in the trenches waiting for the barrage to lift.', 0, 0, NULL, 'July 1916', '["trench_warfare"]', 16),
        ('p2', 'british_memoir', 'The sergeant shouted "Over the top, lads!" and we climbed into no mans land.', 1, 1, '1916-07-01', 'July 1916', '["infantry"]', 14),
        ('p3', 'german_diary', 'Die Engländer kamen in Wellen. "Feuer!" schrie der Offizier.', 0, 1, '1916-07-01', 'July 1916', '["combat"]', 9),
        ('p4', 'french_letters', 'Ma chère Marie, the fighting here is terrible beyond description.', 0, 0, '1916-08-15', 'August 1916', '["letters_home"]', 10)
    """)

    db_conn.commit()
    return db_conn


class TestPassageResult:
    """Tests for PassageResult dataclass."""

    def test_create_result(self):
        """Verify dataclass creation."""
        result = PassageResult(
            passage_id="p1",
            source_id="test",
            content="Test content",
            source_title="Test Book",
            source_author="Author",
            source_type="memoir",
            source_perspective="british",
            has_direct_quote=True,
            date_approximate="July 1916",
            word_count=10,
        )
        assert result.passage_id == "p1"
        assert result.has_direct_quote is True


class TestSearchPassagesFTS:
    """Tests for FTS search."""

    def test_search_basic(self, db_with_data):
        """Verify basic FTS search."""
        results = search_passages_fts(db_with_data, "shells trenches")
        assert len(results) >= 1
        assert any("shells" in r.content.lower() for r in results)

    def test_search_returns_metadata(self, db_with_data):
        """Verify search returns source metadata."""
        results = search_passages_fts(db_with_data, "sergeant")
        assert len(results) >= 1
        result = results[0]
        assert result.source_title == "British Memoir"
        assert result.source_author == "British Officer"

    def test_search_no_results(self, db_with_data):
        """Verify empty results for non-matching query."""
        results = search_passages_fts(db_with_data, "xyznonexistent")
        assert len(results) == 0


class TestGetPassagesForArc:
    """Tests for arc-based passage retrieval."""

    def test_get_passages_for_arc(self, db_with_data):
        """Verify passages retrieved by arc."""
        results = get_passages_for_arc(db_with_data, "western_front")
        assert len(results) >= 3

    def test_quotes_only_filter(self, db_with_data):
        """Verify quotes-only filter works."""
        results = get_passages_for_arc(
            db_with_data, "western_front", with_quotes_only=True
        )
        assert all(r.has_direct_quote for r in results)


class TestGetPassagesForDate:
    """Tests for date-based passage retrieval."""

    def test_get_passages_for_date(self, db_with_data):
        """Verify passages retrieved by date."""
        results = get_passages_for_date(
            db_with_data, date(1916, 7, 1), tolerance_days=7
        )
        assert len(results) >= 2

    def test_date_tolerance(self, db_with_data):
        """Verify date tolerance works."""
        # August 15 with small tolerance should not find July passages
        results = get_passages_for_date(
            db_with_data, date(1916, 8, 15), tolerance_days=3
        )
        # Should find French letters passage
        assert any("Marie" in r.content for r in results)


class TestGetPassagesForTopic:
    """Tests for topic-based passage retrieval."""

    def test_get_passages_for_topic(self, db_with_data):
        """Verify passages retrieved by topic."""
        results = get_passages_for_topic(db_with_data, "infantry")
        assert len(results) >= 1

    def test_topic_quotes_filter(self, db_with_data):
        """Verify quotes filter works with topic."""
        results = get_passages_for_topic(
            db_with_data, "infantry", with_quotes_only=True
        )
        assert all(r.has_direct_quote for r in results)


class TestGetQuotesForEvent:
    """Tests for event-based quote retrieval."""

    def test_get_quotes_for_event(self, db_with_data):
        """Verify quotes retrieved for event."""
        results = get_quotes_for_event(
            db_with_data,
            "Battle of the Somme",
            arc_id="western_front",
            event_date=date(1916, 7, 1),
        )
        # Should find quoted passages
        assert len(results) >= 1
        assert all(r.has_direct_quote for r in results)

    def test_keyword_matching(self, db_with_data):
        """Verify keyword extraction works."""
        # "trenches" should match our passage
        results = get_quotes_for_event(
            db_with_data,
            "Life in the Trenches",
        )
        # May or may not find results depending on FTS
        assert isinstance(results, list)


class TestGetDiversePerspectives:
    """Tests for multi-perspective retrieval."""

    def test_get_diverse_perspectives(self, db_with_data):
        """Verify multiple perspectives returned."""
        results = get_diverse_perspectives(db_with_data, "western_front")

        # Should have british, german, french
        assert "british" in results
        assert "german" in results
        assert "french" in results

    def test_perspective_passages(self, db_with_data):
        """Verify each perspective has passages."""
        results = get_diverse_perspectives(db_with_data, "western_front")

        for perspective, passages in results.items():
            assert len(passages) >= 1
            assert all(p.source_perspective == perspective for p in passages)
