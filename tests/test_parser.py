"""Tests for the passage parser."""

import sqlite3
from datetime import date

import pytest

from wwi_realtime.sources.parser import (
    Passage,
    has_direct_quote,
    detect_chapter,
    find_split_point,
    split_into_passages,
    parse_source_text,
    save_passages,
    get_passages_for_source,
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
    # Add a test source
    conn.execute("""
        INSERT INTO canonical_sources (id, title, author, available)
        VALUES ('test_source', 'Test Book', 'Test Author', 1)
    """)
    conn.commit()
    yield conn
    conn.close()


class TestHasDirectQuote:
    """Tests for quote detection."""

    def test_detects_double_quotes(self):
        """Verify double-quoted text detected."""
        text = 'He said, "The shells came over like rain and we had no cover."'
        assert has_direct_quote(text) is True

    def test_detects_single_quotes(self):
        """Verify single-quoted text detected."""
        text = "The order came: 'Stand to your posts and await further instructions.'"
        assert has_direct_quote(text) is True

    def test_ignores_short_quotes(self):
        """Verify short quotes ignored."""
        text = 'He said "yes" and left.'
        assert has_direct_quote(text) is False

    def test_no_quotes(self):
        """Verify text without quotes returns False."""
        text = "The attack began at dawn. We moved forward through the mud."
        assert has_direct_quote(text) is False


class TestDetectChapter:
    """Tests for chapter detection."""

    def test_detect_roman_numeral_chapter(self):
        """Verify CHAPTER I format detected."""
        text = "CHAPTER IV\n\nThe first day was quiet..."
        chapter = detect_chapter(text)
        assert chapter == "CHAPTER IV"

    def test_detect_numbered_chapter(self):
        """Verify CHAPTER 1 format detected."""
        text = "Chapter 12\n\nWe arrived at the front..."
        chapter = detect_chapter(text)
        assert chapter == "Chapter 12"

    def test_detect_part(self):
        """Verify PART format detected."""
        text = "PART III\n\nThe final offensive..."
        chapter = detect_chapter(text)
        assert chapter == "PART III"

    def test_no_chapter(self):
        """Verify regular text returns None."""
        text = "The trenches were cold and wet."
        chapter = detect_chapter(text)
        assert chapter is None


class TestFindSplitPoint:
    """Tests for finding good split points."""

    def test_prefers_paragraph_break(self):
        """Verify paragraph breaks preferred."""
        text = "First paragraph here.\n\nSecond paragraph starts here. More text."
        # Target in middle of second paragraph
        split = find_split_point(text, 40)
        # Should split at paragraph break (position 23)
        assert text[split-2:split] == "\n\n" or text[split-1] == "\n"

    def test_falls_back_to_sentence(self):
        """Verify sentence end used when no paragraph break."""
        text = "First sentence here. Second sentence here. Third sentence."
        split = find_split_point(text, 30)
        # Should be after a period
        assert text[split-2] == '.' or text[split-1] == ' '


class TestSplitIntoPassages:
    """Tests for splitting text into passages."""

    def test_splits_long_text(self):
        """Verify long text split into multiple passages."""
        # Create text longer than target size
        text = "This is paragraph one. " * 50 + "\n\n" + "This is paragraph two. " * 50
        passages = split_into_passages(text, "test")

        assert len(passages) >= 2
        assert all(isinstance(p, Passage) for p in passages)

    def test_preserves_sequence(self):
        """Verify passages have correct sequence numbers."""
        text = "First part. " * 100 + "\n\n" + "Second part. " * 100
        passages = split_into_passages(text, "test")

        for i, passage in enumerate(passages):
            assert passage.sequence_num == i

    def test_assigns_source_id(self):
        """Verify source_id assigned correctly."""
        text = "Test content. " * 50
        passages = split_into_passages(text, "my_source")

        assert all(p.source_id == "my_source" for p in passages)

    def test_calculates_word_count(self):
        """Verify word count calculated."""
        text = "One two three four five. " * 50
        passages = split_into_passages(text, "test")

        assert all(p.word_count > 0 for p in passages)

    def test_tracks_chapters(self):
        """Verify chapter tracking works."""
        text = "CHAPTER I\n\nFirst chapter content. " * 30 + \
               "\n\nCHAPTER II\n\nSecond chapter. " * 30

        passages = split_into_passages(text, "test")

        # First passage should have CHAPTER I
        assert passages[0].page_or_chapter == "CHAPTER I"

        # Later passages should have chapter info
        chapter_changes = [p for p in passages if p.page_or_chapter == "CHAPTER II"]
        assert len(chapter_changes) >= 1


class TestParseSourceText:
    """Tests for full source parsing."""

    def test_applies_topics(self):
        """Verify topics applied to all passages."""
        text = "Test content for parsing. " * 50
        topics = ["trench_warfare", "infantry"]

        passages = parse_source_text("test", text, topics=topics)

        assert all(p.topics == topics for p in passages)

    def test_extracts_dates(self):
        """Verify dates extracted from content."""
        text = "On 1 July 1916, the attack began. " * 30

        passages = parse_source_text("test", text)

        # At least one passage should have date info
        dates_found = [p for p in passages if p.date_referenced or p.date_approximate]
        assert len(dates_found) >= 1


class TestSaveAndRetrievePassages:
    """Tests for database operations."""

    def test_save_passages(self, db_conn):
        """Verify passages saved to database."""
        passages = [
            Passage(
                id="p1",
                source_id="test_source",
                content="Test content one",
                sequence_num=0,
                word_count=3,
            ),
            Passage(
                id="p2",
                source_id="test_source",
                content="Test content two",
                sequence_num=1,
                word_count=3,
            ),
        ]

        count = save_passages(db_conn, passages)
        assert count == 2

    def test_retrieve_passages(self, db_conn):
        """Verify passages retrieved correctly."""
        passages = [
            Passage(
                id="p1",
                source_id="test_source",
                content="First passage content",
                sequence_num=0,
                date_approximate="July 1916",
                has_direct_quote=True,
                word_count=3,
            ),
        ]
        save_passages(db_conn, passages)

        retrieved = get_passages_for_source(db_conn, "test_source")

        assert len(retrieved) == 1
        assert retrieved[0]["content"] == "First passage content"
        assert retrieved[0]["date_approximate"] == "July 1916"
        assert retrieved[0]["has_direct_quote"] == 1
