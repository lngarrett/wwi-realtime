"""Tests for the curator module."""

import sqlite3
from datetime import date

import pytest

from wwi_realtime.sources.curator import (
    CanonicalSource,
    load_canonical_sources,
    populate_sources_table,
    populate_arc_coverage,
    get_coverage_stats,
    get_sources_for_arc,
    get_sources_for_topic,
    get_available_sources,
)
from wwi_realtime.framework.schema import create_schema
from wwi_realtime.framework.arcs import Arc, populate_arcs_table


@pytest.fixture
def db_conn():
    """Create a temporary database with schema."""
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
def db_with_arcs(db_conn):
    """Database with arcs populated."""
    arcs = [
        Arc(
            id="western_front",
            title="Western Front",
            start_date=date(1914, 8, 4),
            end_date=date(1918, 11, 11),
            theater="western",
        ),
        Arc(
            id="gallipoli",
            title="Gallipoli Campaign",
            start_date=date(1915, 2, 19),
            end_date=date(1916, 1, 9),
            theater="mediterranean",
        ),
        Arc(
            id="naval_warfare",
            title="Naval Warfare",
            theater="naval",
        ),
    ]
    populate_arcs_table(db_conn, arcs)
    return db_conn


class TestLoadCanonicalSources:
    """Tests for loading sources from JSON."""

    def test_load_sources(self):
        """Verify sources load from JSON."""
        sources = load_canonical_sources()
        assert len(sources) >= 20

    def test_sources_have_required_fields(self):
        """Verify each source has required fields."""
        sources = load_canonical_sources()
        for source in sources:
            assert source.id
            assert source.title
            assert source.author

    def test_sources_have_gutenberg_ids(self):
        """Verify most sources have Gutenberg IDs."""
        sources = load_canonical_sources()
        with_gutenberg = [s for s in sources if s.gutenberg_id]
        assert len(with_gutenberg) >= 20

    def test_sources_have_coverage(self):
        """Verify sources have coverage info."""
        sources = load_canonical_sources()
        with_arcs = [s for s in sources if s.coverage_arcs]
        assert len(with_arcs) >= 15


class TestPopulateSourcesTable:
    """Tests for populating sources table."""

    def test_populate_sources(self, db_conn):
        """Verify sources are populated."""
        sources = [
            CanonicalSource(
                id="test1",
                title="Test Source 1",
                author="Author 1",
                gutenberg_id="123",
                priority=1,
            ),
            CanonicalSource(
                id="test2",
                title="Test Source 2",
                author="Author 2",
                gutenberg_id="456",
                priority=2,
            ),
        ]

        count = populate_sources_table(db_conn, sources)
        assert count == 2

        cursor = db_conn.execute("SELECT COUNT(*) FROM canonical_sources")
        assert cursor.fetchone()[0] == 2

    def test_populate_with_topics(self, db_conn):
        """Verify topic coverage is created."""
        sources = [
            CanonicalSource(
                id="test1",
                title="Test Source",
                author="Author",
                coverage_topics=["trench_warfare", "infantry"],
            ),
        ]

        populate_sources_table(db_conn, sources)

        cursor = db_conn.execute(
            "SELECT topic FROM source_coverage WHERE source_id = 'test1'"
        )
        topics = [row[0] for row in cursor.fetchall()]
        assert "trench_warfare" in topics
        assert "infantry" in topics


class TestPopulateArcCoverage:
    """Tests for arc coverage mappings."""

    def test_populate_arc_coverage(self, db_with_arcs):
        """Verify arc coverage is created."""
        sources = [
            CanonicalSource(
                id="test1",
                title="Test Source",
                author="Author",
                coverage_arcs=["western_front", "gallipoli"],
            ),
        ]
        populate_sources_table(db_with_arcs, sources)

        count = populate_arc_coverage(db_with_arcs, sources)
        assert count == 2

        cursor = db_with_arcs.execute(
            "SELECT arc_id FROM source_coverage WHERE source_id = 'test1' AND arc_id IS NOT NULL"
        )
        arcs = [row[0] for row in cursor.fetchall()]
        assert "western_front" in arcs
        assert "gallipoli" in arcs

    def test_skips_nonexistent_arcs(self, db_with_arcs):
        """Verify nonexistent arcs are skipped."""
        sources = [
            CanonicalSource(
                id="test1",
                title="Test Source",
                author="Author",
                coverage_arcs=["western_front", "nonexistent_arc"],
            ),
        ]
        populate_sources_table(db_with_arcs, sources)

        count = populate_arc_coverage(db_with_arcs, sources)
        # Only western_front should be added
        assert count == 1


class TestGetSourcesForArc:
    """Tests for querying sources by arc."""

    def test_get_sources_for_arc(self, db_with_arcs):
        """Verify sources retrieved by arc."""
        sources = [
            CanonicalSource(
                id="source1",
                title="Western Front Memoir",
                author="Author 1",
                gutenberg_id="123",
                coverage_arcs=["western_front"],
            ),
            CanonicalSource(
                id="source2",
                title="Gallipoli Diary",
                author="Author 2",
                gutenberg_id="456",
                coverage_arcs=["gallipoli"],
            ),
        ]
        populate_sources_table(db_with_arcs, sources)
        populate_arc_coverage(db_with_arcs, sources)

        western_sources = get_sources_for_arc(db_with_arcs, "western_front")
        assert len(western_sources) == 1
        assert western_sources[0]["id"] == "source1"

        gallipoli_sources = get_sources_for_arc(db_with_arcs, "gallipoli")
        assert len(gallipoli_sources) == 1
        assert gallipoli_sources[0]["id"] == "source2"


class TestGetCoverageStats:
    """Tests for coverage statistics."""

    def test_coverage_stats(self, db_with_arcs):
        """Verify coverage stats calculated."""
        sources = [
            CanonicalSource(
                id="source1",
                title="Source 1",
                author="Author",
                coverage_arcs=["western_front"],
                coverage_topics=["infantry", "trench_warfare"],
            ),
            CanonicalSource(
                id="source2",
                title="Source 2",
                author="Author",
                coverage_arcs=["western_front", "gallipoli"],
                coverage_topics=["infantry"],
            ),
        ]
        populate_sources_table(db_with_arcs, sources)
        populate_arc_coverage(db_with_arcs, sources)

        stats = get_coverage_stats(db_with_arcs)

        assert stats["sources_with_arc"] == 2
        assert stats["sources_with_topic"] == 2
        assert stats["arcs_coverage"]["western_front"] == 2
        assert stats["arcs_coverage"]["gallipoli"] == 1
        assert "infantry" in stats["top_topics"]
