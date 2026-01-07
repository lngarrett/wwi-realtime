"""Gutenberg API client for downloading WWI sources.

Uses the Gutendex API (https://gutendex.com/) for metadata and
direct Gutenberg.org downloads for text content.
"""

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# Gutendex API base URL
GUTENDEX_API = "https://gutendex.com/books"

# Direct download URL patterns
GUTENBERG_TXT_URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
GUTENBERG_TXT_UTF8_URL = "https://www.gutenberg.org/files/{id}/{id}-0.txt"


@dataclass
class GutenbergBook:
    """Metadata for a Gutenberg book."""
    id: str
    title: str
    authors: list[str]
    subjects: list[str]
    languages: list[str]
    download_count: int
    text_url: str | None = None


def get_book_metadata(gutenberg_id: str, client: httpx.Client | None = None) -> GutenbergBook | None:
    """Fetch metadata for a Gutenberg book.

    Args:
        gutenberg_id: The Gutenberg book ID (numeric string)
        client: Optional httpx client for connection reuse

    Returns:
        GutenbergBook with metadata, or None if not found
    """
    close_client = client is None
    if client is None:
        client = httpx.Client(timeout=30.0, follow_redirects=True)

    try:
        url = f"{GUTENDEX_API}/{gutenberg_id}/"  # Trailing slash to avoid redirect
        response = client.get(url)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        data = response.json()

        # Extract author names
        authors = [a["name"] for a in data.get("authors", [])]

        # Find text download URL
        text_url = None
        formats = data.get("formats", {})
        for mime, url in formats.items():
            if "text/plain" in mime and "utf-8" in mime.lower():
                text_url = url
                break
        if not text_url:
            for mime, url in formats.items():
                if "text/plain" in mime:
                    text_url = url
                    break

        return GutenbergBook(
            id=str(data["id"]),
            title=data.get("title", "Unknown"),
            authors=authors,
            subjects=data.get("subjects", []),
            languages=data.get("languages", []),
            download_count=data.get("download_count", 0),
            text_url=text_url,
        )

    except Exception as e:
        print(f"Error fetching metadata for {gutenberg_id}: {e}")
        return None

    finally:
        if close_client:
            client.close()


def download_text(gutenberg_id: str, client: httpx.Client | None = None) -> str | None:
    """Download the plain text content of a Gutenberg book.

    Args:
        gutenberg_id: The Gutenberg book ID (numeric string)
        client: Optional httpx client for connection reuse

    Returns:
        The book text content, or None if download failed
    """
    close_client = client is None
    if client is None:
        client = httpx.Client(timeout=60.0, follow_redirects=True)

    try:
        # Try multiple URL patterns
        urls = [
            GUTENBERG_TXT_URL.format(id=gutenberg_id),
            GUTENBERG_TXT_UTF8_URL.format(id=gutenberg_id),
        ]

        for url in urls:
            try:
                response = client.get(url)
                if response.status_code == 200:
                    return response.text
            except Exception:
                continue

        # If direct URLs fail, try getting URL from metadata
        book = get_book_metadata(gutenberg_id, client)
        if book and book.text_url:
            response = client.get(book.text_url)
            if response.status_code == 200:
                return response.text

        return None

    except Exception as e:
        print(f"Error downloading text for {gutenberg_id}: {e}")
        return None

    finally:
        if close_client:
            client.close()


def clean_gutenberg_text(text: str) -> str:
    """Remove Gutenberg header/footer boilerplate from text.

    Args:
        text: Raw text from Gutenberg

    Returns:
        Cleaned text with header/footer removed
    """
    # Common start markers
    start_markers = [
        "*** START OF THE PROJECT GUTENBERG EBOOK",
        "*** START OF THIS PROJECT GUTENBERG EBOOK",
        "*END*THE SMALL PRINT",
        "*** START OF THE PROJECT GUTENBERG",
    ]

    # Common end markers
    end_markers = [
        "*** END OF THE PROJECT GUTENBERG EBOOK",
        "*** END OF THIS PROJECT GUTENBERG EBOOK",
        "End of the Project Gutenberg EBook",
        "End of Project Gutenberg",
    ]

    # Find start
    start_pos = 0
    for marker in start_markers:
        pos = text.find(marker)
        if pos != -1:
            # Find the end of the line after the marker
            newline_pos = text.find("\n", pos)
            if newline_pos != -1:
                start_pos = newline_pos + 1
                break

    # Find end
    end_pos = len(text)
    for marker in end_markers:
        pos = text.find(marker)
        if pos != -1:
            end_pos = pos
            break

    cleaned = text[start_pos:end_pos].strip()

    # Remove any remaining license text at the end
    license_markers = [
        "This eBook is for the use of anyone",
        "This and all associated files",
        "Updated editions will replace",
    ]
    for marker in license_markers:
        pos = cleaned.find(marker)
        if pos != -1 and pos > len(cleaned) * 0.9:  # Only if near the end
            cleaned = cleaned[:pos].strip()

    return cleaned


def save_source_text(
    source_id: str,
    gutenberg_id: str,
    output_dir: Path | str = "data/sources",
) -> Path | None:
    """Download and save a Gutenberg source.

    Args:
        source_id: Our internal source ID
        gutenberg_id: The Gutenberg book ID
        output_dir: Directory to save files

    Returns:
        Path to saved file, or None if failed
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{source_id}.txt"

    # Check if already downloaded
    if output_path.exists():
        return output_path

    print(f"Downloading {source_id} (Gutenberg #{gutenberg_id})...")

    text = download_text(gutenberg_id)
    if not text:
        print(f"  Failed to download")
        return None

    cleaned = clean_gutenberg_text(text)

    # Save to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(cleaned)

    word_count = len(cleaned.split())
    print(f"  Saved {word_count:,} words to {output_path}")

    return output_path


def download_available_sources(
    conn: sqlite3.Connection,
    output_dir: Path | str = "data/sources",
    priority_max: int = 2,
    limit: int | None = None,
) -> list[tuple[str, Path]]:
    """Download all available Gutenberg sources.

    Args:
        conn: Database connection
        output_dir: Directory to save files
        priority_max: Maximum priority to download (1 = highest only)
        limit: Maximum number of sources to download

    Returns:
        List of (source_id, path) tuples for successfully downloaded sources
    """
    cursor = conn.execute(
        """SELECT id, gutenberg_id FROM canonical_sources
           WHERE gutenberg_id IS NOT NULL
             AND available = 1
             AND priority <= ?
           ORDER BY priority, title""",
        (priority_max,)
    )

    rows = cursor.fetchall()
    if limit:
        rows = rows[:limit]

    downloaded = []
    for source_id, gutenberg_id in rows:
        path = save_source_text(source_id, gutenberg_id, output_dir)
        if path:
            downloaded.append((source_id, path))
            time.sleep(1)  # Be nice to Gutenberg servers

    return downloaded


def search_gutenberg(query: str, topic: str | None = None) -> list[GutenbergBook]:
    """Search Gutenberg for books matching a query.

    Args:
        query: Search query (title, author, etc.)
        topic: Optional topic filter

    Returns:
        List of matching GutenbergBook objects
    """
    params = {"search": query}
    if topic:
        params["topic"] = topic

    with httpx.Client(timeout=30.0) as client:
        response = client.get(GUTENDEX_API, params=params)
        response.raise_for_status()
        data = response.json()

        books = []
        for result in data.get("results", []):
            authors = [a["name"] for a in result.get("authors", [])]

            # Find text URL
            text_url = None
            for mime, url in result.get("formats", {}).items():
                if "text/plain" in mime:
                    text_url = url
                    break

            books.append(GutenbergBook(
                id=str(result["id"]),
                title=result.get("title", "Unknown"),
                authors=authors,
                subjects=result.get("subjects", []),
                languages=result.get("languages", []),
                download_count=result.get("download_count", 0),
                text_url=text_url,
            ))

        return books
