"""Tests for the Gutenberg API client."""

import pytest

from wwi_realtime.sources.gutenberg import (
    get_book_metadata,
    clean_gutenberg_text,
    GutenbergBook,
)


class TestGetBookMetadata:
    """Tests for fetching book metadata."""

    def test_fetch_over_the_top(self):
        """Verify we can fetch metadata for 'Over the Top'."""
        book = get_book_metadata("7962")
        assert book is not None
        assert book.id == "7962"
        assert "Over the Top" in book.title
        assert any("Empey" in a for a in book.authors)
        assert book.text_url is not None

    def test_fetch_nonexistent_book(self):
        """Verify None returned for nonexistent book."""
        book = get_book_metadata("999999999")
        assert book is None

    def test_fetch_gallipoli_diary(self):
        """Verify we can fetch Gallipoli Diary."""
        book = get_book_metadata("19317")
        assert book is not None
        assert "Gallipoli" in book.title
        assert any("Hamilton" in a for a in book.authors)


class TestCleanGutenbergText:
    """Tests for cleaning Gutenberg boilerplate."""

    def test_removes_header(self):
        """Verify header is removed."""
        text = """The Project Gutenberg EBook of Test Book

*** START OF THE PROJECT GUTENBERG EBOOK TEST BOOK ***

This is the actual content of the book.
It has multiple paragraphs.

*** END OF THE PROJECT GUTENBERG EBOOK TEST BOOK ***

End of Project Gutenberg stuff here.
"""
        cleaned = clean_gutenberg_text(text)
        assert "This is the actual content" in cleaned
        assert "START OF THE PROJECT GUTENBERG" not in cleaned
        assert "END OF THE PROJECT GUTENBERG" not in cleaned

    def test_preserves_content(self):
        """Verify book content is preserved."""
        text = """*** START OF THE PROJECT GUTENBERG EBOOK ***

Chapter 1

The shells came over like rain. We had no idea
what we were getting into.

"Take cover!" shouted the sergeant.

Chapter 2

The next morning was quiet.

*** END OF THE PROJECT GUTENBERG EBOOK ***
"""
        cleaned = clean_gutenberg_text(text)
        assert "Chapter 1" in cleaned
        assert "Chapter 2" in cleaned
        assert "Take cover!" in cleaned
        assert "shells came over" in cleaned

    def test_handles_missing_markers(self):
        """Verify text without markers is returned as-is."""
        text = "This is just regular text without any Gutenberg markers."
        cleaned = clean_gutenberg_text(text)
        assert cleaned == text


class TestGutenbergBookDataclass:
    """Tests for the GutenbergBook dataclass."""

    def test_create_book(self):
        """Verify book dataclass works."""
        book = GutenbergBook(
            id="123",
            title="Test Book",
            authors=["Author One", "Author Two"],
            subjects=["War", "History"],
            languages=["en"],
            download_count=100,
            text_url="https://example.com/book.txt",
        )
        assert book.id == "123"
        assert len(book.authors) == 2
        assert "History" in book.subjects
