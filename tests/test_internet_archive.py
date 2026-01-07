"""Tests for Internet Archive API client."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from wwi_realtime.sources.internet_archive import (
    IAItem,
    IAFile,
    get_item_metadata,
    list_item_files,
    get_text_file,
    search_items,
    search_wwi_sources,
    download_item_text,
    check_item_availability,
)


class TestIAItem:
    """Tests for IAItem dataclass."""

    def test_create_item(self):
        """Test creating an IAItem."""
        item = IAItem(
            identifier="stormofsteel00jung",
            title="Storm of Steel",
            creator="Ernst Jünger",
            date="1920",
        )

        assert item.identifier == "stormofsteel00jung"
        assert item.title == "Storm of Steel"
        assert item.creator == "Ernst Jünger"

    def test_item_optional_fields(self):
        """Test IAItem with minimal fields."""
        item = IAItem(identifier="test", title="Test")

        assert item.creator is None
        assert item.date is None
        assert item.subjects is None


class TestIAFile:
    """Tests for IAFile dataclass."""

    def test_create_file(self):
        """Test creating an IAFile."""
        file = IAFile(
            name="book.txt",
            format="Text",
            size=12345,
            source="derivative",
        )

        assert file.name == "book.txt"
        assert file.format == "Text"
        assert file.size == 12345


class TestGetItemMetadata:
    """Tests for metadata retrieval."""

    @patch("wwi_realtime.sources.internet_archive.httpx.Client")
    def test_get_metadata_success(self, mock_client_class):
        """Test successful metadata retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {
                "title": "Storm of Steel",
                "creator": "Ernst Jünger",
                "date": "1920",
                "subject": ["World War, 1914-1918", "German literature"],
            }
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        item = get_item_metadata("stormofsteel00jung")

        assert item is not None
        assert item.title == "Storm of Steel"
        assert item.creator == "Ernst Jünger"
        assert "World War, 1914-1918" in item.subjects

    @patch("wwi_realtime.sources.internet_archive.httpx.Client")
    def test_get_metadata_not_found(self, mock_client_class):
        """Test metadata for non-existent item."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        item = get_item_metadata("nonexistent")

        assert item is None

    @patch("wwi_realtime.sources.internet_archive.httpx.Client")
    def test_get_metadata_subject_string(self, mock_client_class):
        """Test metadata with subject as string (not list)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {
                "title": "Test",
                "subject": "Single Subject",
            }
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        item = get_item_metadata("test")

        assert item.subjects == ["Single Subject"]


class TestListItemFiles:
    """Tests for file listing."""

    @patch("wwi_realtime.sources.internet_archive.httpx.Client")
    def test_list_files_success(self, mock_client_class):
        """Test successful file listing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": [
                {"name": "book.txt", "format": "Text", "size": 12345},
                {"name": "book.pdf", "format": "PDF", "size": 54321},
            ]
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        files = list_item_files("test")

        assert len(files) == 2
        assert files[0].name == "book.txt"
        assert files[0].format == "Text"


class TestGetTextFile:
    """Tests for text file retrieval."""

    @patch("wwi_realtime.sources.internet_archive.list_item_files")
    @patch("wwi_realtime.sources.internet_archive.httpx.Client")
    def test_get_text_file_success(self, mock_client_class, mock_list_files):
        """Test successful text file retrieval."""
        mock_list_files.return_value = [
            IAFile(name="book.txt", format="Text"),
            IAFile(name="book.pdf", format="PDF"),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "This is the book text."

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        text = get_text_file("test")

        assert text == "This is the book text."

    @patch("wwi_realtime.sources.internet_archive.list_item_files")
    def test_get_text_file_no_text(self, mock_list_files):
        """Test when no text file available."""
        mock_list_files.return_value = [
            IAFile(name="book.pdf", format="PDF"),
        ]

        text = get_text_file("test")

        assert text is None

    @patch("wwi_realtime.sources.internet_archive.list_item_files")
    @patch("wwi_realtime.sources.internet_archive.httpx.Client")
    def test_get_text_file_prefers_text_format(self, mock_client_class, mock_list_files):
        """Test that Text format is preferred over DjVuTXT."""
        mock_list_files.return_value = [
            IAFile(name="book_djvu.txt", format="DjVuTXT"),
            IAFile(name="book.txt", format="Text"),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Text content"

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        text = get_text_file("test")

        # Should have requested the Text format file
        call_url = mock_client.get.call_args[0][0]
        assert "book.txt" in call_url


class TestSearchItems:
    """Tests for search functionality."""

    @patch("wwi_realtime.sources.internet_archive.httpx.Client")
    def test_search_success(self, mock_client_class):
        """Test successful search."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": {
                "docs": [
                    {
                        "identifier": "book1",
                        "title": "WWI Memoir",
                        "creator": "Soldier",
                        "date": "1920",
                    },
                    {
                        "identifier": "book2",
                        "title": "War Letters",
                    },
                ]
            }
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        items = search_items("world war")

        assert len(items) == 2
        assert items[0].identifier == "book1"
        assert items[0].title == "WWI Memoir"


class TestSearchWWISources:
    """Tests for WWI-specific search."""

    @patch("wwi_realtime.sources.internet_archive.search_items")
    def test_search_wwi_basic(self, mock_search):
        """Test basic WWI search."""
        mock_search.return_value = []

        search_wwi_sources()

        # Should have called search_items with WWI subject
        call_args = mock_search.call_args
        assert "World War, 1914-1918" in call_args[0][0]

    @patch("wwi_realtime.sources.internet_archive.search_items")
    def test_search_wwi_with_keywords(self, mock_search):
        """Test WWI search with additional keywords."""
        mock_search.return_value = []

        search_wwi_sources(keywords=["trench warfare", "Somme"])

        call_args = mock_search.call_args
        query = call_args[0][0]
        assert "trench warfare" in query
        assert "Somme" in query


class TestDownloadItemText:
    """Tests for text download."""

    @patch("wwi_realtime.sources.internet_archive.get_text_file")
    @patch("wwi_realtime.sources.internet_archive.time.sleep")
    def test_download_success(self, mock_sleep, mock_get_text, tmp_path):
        """Test successful download."""
        mock_get_text.return_value = "Downloaded text content."

        result = download_item_text("test", tmp_path, delay=0.1)

        assert result is not None
        assert result.exists()
        assert result.read_text() == "Downloaded text content."
        mock_sleep.assert_called_once_with(0.1)

    @patch("wwi_realtime.sources.internet_archive.get_text_file")
    def test_download_no_text(self, mock_get_text, tmp_path):
        """Test download when no text available."""
        mock_get_text.return_value = None

        result = download_item_text("test", tmp_path, delay=0)

        assert result is None


class TestCheckItemAvailability:
    """Tests for availability checking."""

    @patch("wwi_realtime.sources.internet_archive.get_item_metadata")
    @patch("wwi_realtime.sources.internet_archive.list_item_files")
    def test_check_available_with_text(self, mock_list_files, mock_metadata):
        """Test checking available item with text."""
        mock_metadata.return_value = IAItem(
            identifier="test",
            title="Test Book",
        )
        mock_list_files.return_value = [
            IAFile(name="book.txt", format="Text"),
        ]

        result = check_item_availability("test")

        assert result["exists"] is True
        assert result["has_text"] is True
        assert result["title"] == "Test Book"
        assert result["text_format"] == "Text"

    @patch("wwi_realtime.sources.internet_archive.get_item_metadata")
    def test_check_not_available(self, mock_metadata):
        """Test checking non-existent item."""
        mock_metadata.return_value = None

        result = check_item_availability("nonexistent")

        assert result["exists"] is False
        assert result["has_text"] is False

    @patch("wwi_realtime.sources.internet_archive.get_item_metadata")
    @patch("wwi_realtime.sources.internet_archive.list_item_files")
    def test_check_available_no_text(self, mock_list_files, mock_metadata):
        """Test checking item without text."""
        mock_metadata.return_value = IAItem(
            identifier="test",
            title="Audio Book",
        )
        mock_list_files.return_value = [
            IAFile(name="audio.mp3", format="VBR MP3"),
        ]

        result = check_item_availability("test")

        assert result["exists"] is True
        assert result["has_text"] is False
