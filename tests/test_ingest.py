"""Tests for source ingestion pipeline."""

import sqlite3

import pytest

from wwi_realtime.sources.ingest import (
    ingest_source,
    get_ingestion_stats,
    verify_ingestion,
)
from wwi_realtime.framework.schema import create_schema


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
def db_with_source(db_conn):
    """Database with a test source configured."""
    db_conn.execute("""
        INSERT INTO canonical_sources
        (id, title, author, gutenberg_id, available, priority)
        VALUES ('over_the_top', 'Over the Top', 'Arthur Guy Empey', '7962', 1, 1)
    """)
    db_conn.commit()
    return db_conn


class TestIngestSource:
    """Tests for single source ingestion."""

    @pytest.mark.slow
    def test_ingest_over_the_top(self, db_with_source):
        """Verify we can ingest 'Over the Top' from Gutenberg."""
        count = ingest_source(
            db_with_source,
            "over_the_top",
            "7962",
            topics=["trench_warfare", "infantry"],
            save_raw=False,
        )

        assert count > 0
        # Should have significant number of passages
        assert count >= 100

    @pytest.mark.slow
    def test_ingest_marks_source_ingested(self, db_with_source):
        """Verify ingested flag is set."""
        ingest_source(db_with_source, "over_the_top", "7962", save_raw=False)

        cursor = db_with_source.execute(
            "SELECT ingested FROM canonical_sources WHERE id = 'over_the_top'"
        )
        assert cursor.fetchone()[0] == 1

    @pytest.mark.slow
    def test_ingest_creates_passages_with_quotes(self, db_with_source):
        """Verify passages with quotes are detected."""
        ingest_source(db_with_source, "over_the_top", "7962", save_raw=False)

        cursor = db_with_source.execute(
            "SELECT COUNT(*) FROM source_passages WHERE has_direct_quote = 1"
        )
        quote_count = cursor.fetchone()[0]
        # Over the Top has many quoted dialogues
        assert quote_count > 10


class TestIngestionStats:
    """Tests for ingestion statistics."""

    def test_empty_stats(self, db_conn):
        """Verify stats work on empty database."""
        stats = get_ingestion_stats(db_conn)

        assert stats["available"] == 0
        assert stats["ingested"] == 0
        assert stats["passages"] == 0

    def test_stats_with_data(self, db_conn):
        """Verify stats reflect data."""
        # Add sources
        db_conn.execute("""
            INSERT INTO canonical_sources
            (id, title, author, gutenberg_id, available, ingested)
            VALUES ('s1', 'Source 1', 'Author', '123', 1, 1)
        """)
        # Add passages
        db_conn.execute("""
            INSERT INTO source_passages
            (id, source_id, content, sequence_num, has_direct_quote, word_count)
            VALUES ('p1', 's1', 'Test content', 0, 1, 10)
        """)
        db_conn.commit()

        stats = get_ingestion_stats(db_conn)

        assert stats["available"] == 1
        assert stats["ingested"] == 1
        assert stats["passages"] == 1
        assert stats["passages_with_quotes"] == 1
        assert stats["total_words"] == 10


class TestVerifyIngestion:
    """Tests for ingestion verification."""

    def test_verify_not_ingested(self, db_with_source):
        """Verify None returned for non-ingested source."""
        result = verify_ingestion(db_with_source, "over_the_top")
        assert result is None

    def test_verify_ingested(self, db_conn):
        """Verify stats returned for ingested source."""
        db_conn.execute("""
            INSERT INTO canonical_sources
            (id, title, author, available, ingested)
            VALUES ('test', 'Test', 'Author', 1, 1)
        """)
        db_conn.execute("""
            INSERT INTO source_passages
            (id, source_id, content, sequence_num, has_direct_quote, word_count)
            VALUES ('p1', 'test', 'Quote here', 0, 1, 5)
        """)
        db_conn.execute("""
            INSERT INTO source_passages
            (id, source_id, content, sequence_num, has_direct_quote, word_count)
            VALUES ('p2', 'test', 'No quote', 1, 0, 3)
        """)
        db_conn.commit()

        result = verify_ingestion(db_conn, "test")

        assert result is not None
        assert result["passages"] == 2
        assert result["words"] == 8
        assert result["quotes"] == 1
