"""Tests for the story engine database schema."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from wwi_realtime.framework.schema import (
    create_schema,
    get_connection,
    get_schema_version,
    verify_schema,
    SCHEMA_VERSION,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    yield db_path

    # Cleanup
    db_path.unlink(missing_ok=True)


@pytest.fixture
def conn(temp_db):
    """Create a connection with schema applied."""
    conn = get_connection(temp_db)
    create_schema(conn)
    yield conn
    conn.close()


class TestSchemaCreation:
    """Tests for schema creation."""

    def test_arcs_table_created(self, conn):
        """Verify arcs table exists with correct columns."""
        cursor = conn.execute("PRAGMA table_info(arcs)")
        columns = {row[1] for row in cursor.fetchall()}

        expected = {
            "id", "title", "parent_arc_id", "start_date", "end_date",
            "wikipedia_url", "narrative_summary", "significance",
            "theater", "created_at"
        }
        assert expected.issubset(columns)

    def test_canonical_sources_table_created(self, conn):
        """Verify canonical_sources table exists with correct columns."""
        cursor = conn.execute("PRAGMA table_info(canonical_sources)")
        columns = {row[1] for row in cursor.fetchall()}

        expected = {
            "id", "title", "author", "author_info", "type", "perspective",
            "gutenberg_id", "internet_archive_id", "available", "ingested"
        }
        assert expected.issubset(columns)

    def test_source_coverage_table_created(self, conn):
        """Verify source_coverage table exists with correct columns."""
        cursor = conn.execute("PRAGMA table_info(source_coverage)")
        columns = {row[1] for row in cursor.fetchall()}

        expected = {"id", "source_id", "arc_id", "event_id", "topic"}
        assert expected.issubset(columns)

    def test_source_passages_table_created(self, conn):
        """Verify source_passages table exists with correct columns."""
        cursor = conn.execute("PRAGMA table_info(source_passages)")
        columns = {row[1] for row in cursor.fetchall()}

        expected = {
            "id", "source_id", "content", "page_or_chapter",
            "date_referenced", "date_approximate", "has_direct_quote", "topics"
        }
        assert expected.issubset(columns)

    def test_fts_index_created(self, conn):
        """Verify FTS virtual table exists."""
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='source_passages_fts'"
        )
        assert cursor.fetchone() is not None


class TestArcHierarchy:
    """Tests for arc parent-child relationships."""

    def test_parent_arc_id_foreign_key(self, conn):
        """Verify parent_arc_id can reference another arc."""
        # Create parent arc
        conn.execute(
            "INSERT INTO arcs (id, title) VALUES (?, ?)",
            ("western_front", "Western Front")
        )

        # Create child arc
        conn.execute(
            "INSERT INTO arcs (id, title, parent_arc_id) VALUES (?, ?, ?)",
            ("western_front_1916", "Western Front 1916", "western_front")
        )

        conn.commit()

        # Verify relationship
        cursor = conn.execute(
            "SELECT parent_arc_id FROM arcs WHERE id = ?",
            ("western_front_1916",)
        )
        assert cursor.fetchone()[0] == "western_front"

    def test_nested_arcs(self, conn):
        """Verify multiple levels of nesting work."""
        arcs = [
            ("wwi", "World War I", None),
            ("western_front", "Western Front", "wwi"),
            ("somme_1916", "Battle of the Somme", "western_front"),
            ("first_day_somme", "First Day of the Somme", "somme_1916"),
        ]

        for arc_id, title, parent in arcs:
            conn.execute(
                "INSERT INTO arcs (id, title, parent_arc_id) VALUES (?, ?, ?)",
                (arc_id, title, parent)
            )

        conn.commit()

        # Query to get full hierarchy
        cursor = conn.execute("""
            WITH RECURSIVE arc_path AS (
                SELECT id, title, parent_arc_id, 0 as depth
                FROM arcs WHERE id = 'first_day_somme'
                UNION ALL
                SELECT a.id, a.title, a.parent_arc_id, ap.depth + 1
                FROM arcs a
                JOIN arc_path ap ON a.id = ap.parent_arc_id
            )
            SELECT id, depth FROM arc_path ORDER BY depth
        """)

        path = [(row[0], row[1]) for row in cursor.fetchall()]
        assert path == [
            ("first_day_somme", 0),
            ("somme_1916", 1),
            ("western_front", 2),
            ("wwi", 3),
        ]


class TestFTSIndex:
    """Tests for full-text search functionality."""

    def test_fts_search_basic(self, conn):
        """Verify basic FTS search works."""
        # Insert a source
        conn.execute(
            "INSERT INTO canonical_sources (id, title, author) VALUES (?, ?, ?)",
            ("test_source", "Test Memoir", "Test Author")
        )

        # Insert a passage
        conn.execute(
            """INSERT INTO source_passages
            (id, source_id, content, topics, has_direct_quote)
            VALUES (?, ?, ?, ?, ?)""",
            ("p1", "test_source", "The shells came over like rain", '["artillery"]', True)
        )

        conn.commit()

        # Search for "shells"
        cursor = conn.execute("""
            SELECT sp.id, sp.content
            FROM source_passages sp
            JOIN source_passages_fts fts ON sp.rowid = fts.rowid
            WHERE source_passages_fts MATCH 'shells'
        """)

        results = cursor.fetchall()
        assert len(results) == 1
        assert "shells" in results[0][1]

    def test_fts_search_multiple_terms(self, conn):
        """Verify multi-term FTS search works."""
        conn.execute(
            "INSERT INTO canonical_sources (id, title, author) VALUES (?, ?, ?)",
            ("test_source", "Test Memoir", "Test Author")
        )

        passages = [
            ("p1", "The artillery barrage was devastating"),
            ("p2", "Machine guns rattled through the night"),
            ("p3", "The artillery and machine guns never stopped"),
        ]

        for pid, content in passages:
            conn.execute(
                """INSERT INTO source_passages
                (id, source_id, content, has_direct_quote)
                VALUES (?, ?, ?, ?)""",
                (pid, "test_source", content, False)
            )

        conn.commit()

        # Search for passages with both artillery and machine guns
        cursor = conn.execute("""
            SELECT sp.id
            FROM source_passages sp
            JOIN source_passages_fts fts ON sp.rowid = fts.rowid
            WHERE source_passages_fts MATCH 'artillery AND machine'
        """)

        results = cursor.fetchall()
        assert len(results) == 1
        assert results[0][0] == "p3"


class TestSchemaVersion:
    """Tests for schema versioning."""

    def test_schema_version_set(self, conn):
        """Verify schema version is recorded."""
        version = get_schema_version(conn)
        assert version == SCHEMA_VERSION

    def test_verify_schema_all_tables(self, conn):
        """Verify all expected tables exist."""
        # Create events table (normally exists from build_event_index)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                date DATE NOT NULL,
                title TEXT NOT NULL,
                arc_id TEXT
            )
        """)
        conn.commit()

        result = verify_schema(conn)
        assert result["all_exist"] is True
        assert result["version"] == SCHEMA_VERSION


class TestSourceCoverage:
    """Tests for source-to-arc/event coverage mapping."""

    def test_source_covers_arc(self, conn):
        """Verify source can be tagged as covering an arc."""
        # Create arc
        conn.execute(
            "INSERT INTO arcs (id, title) VALUES (?, ?)",
            ("somme", "Battle of the Somme")
        )

        # Create source
        conn.execute(
            "INSERT INTO canonical_sources (id, title, author) VALUES (?, ?, ?)",
            ("graves", "Goodbye to All That", "Robert Graves")
        )

        # Create coverage mapping
        conn.execute(
            "INSERT INTO source_coverage (source_id, arc_id) VALUES (?, ?)",
            ("graves", "somme")
        )

        conn.commit()

        # Query sources that cover Somme
        cursor = conn.execute("""
            SELECT cs.title, cs.author
            FROM canonical_sources cs
            JOIN source_coverage sc ON cs.id = sc.source_id
            WHERE sc.arc_id = ?
        """, ("somme",))

        results = cursor.fetchall()
        assert len(results) == 1
        assert results[0][0] == "Goodbye to All That"

    def test_source_covers_topic(self, conn):
        """Verify source can be tagged with topics."""
        conn.execute(
            "INSERT INTO canonical_sources (id, title, author) VALUES (?, ?, ?)",
            ("junger", "Storm of Steel", "Ernst Jünger")
        )

        # Tag with multiple topics
        topics = ["trench_warfare", "artillery", "german_perspective"]
        for topic in topics:
            conn.execute(
                "INSERT INTO source_coverage (source_id, topic) VALUES (?, ?)",
                ("junger", topic)
            )

        conn.commit()

        # Query sources about artillery
        cursor = conn.execute("""
            SELECT cs.title
            FROM canonical_sources cs
            JOIN source_coverage sc ON cs.id = sc.source_id
            WHERE sc.topic = ?
        """, ("artillery",))

        results = cursor.fetchall()
        assert len(results) == 1
        assert results[0][0] == "Storm of Steel"
