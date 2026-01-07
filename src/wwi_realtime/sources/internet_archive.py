"""Internet Archive API client.

Provides access to Internet Archive for downloading WWI primary sources.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx


BASE_URL = "https://archive.org"
METADATA_URL = f"{BASE_URL}/metadata"
DOWNLOAD_URL = f"{BASE_URL}/download"
SEARCH_URL = f"{BASE_URL}/advancedsearch.php"


@dataclass
class IAItem:
    """An Internet Archive item."""
    identifier: str
    title: str
    creator: str | None = None
    date: str | None = None
    description: str | None = None
    mediatype: str | None = None
    subjects: list[str] | None = None


@dataclass
class IAFile:
    """A file within an Internet Archive item."""
    name: str
    format: str
    size: int | None = None
    source: str | None = None  # "original" or "derivative"


def get_item_metadata(identifier: str, timeout: float = 30.0) -> IAItem | None:
    """Fetch metadata for an Internet Archive item.

    Args:
        identifier: The IA identifier (e.g., "stormofsteel00jung")
        timeout: Request timeout in seconds

    Returns:
        IAItem or None if not found
    """
    url = f"{METADATA_URL}/{identifier}"

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()

            metadata = data.get("metadata", {})

            # Handle subjects (can be string or list)
            subjects = metadata.get("subject", [])
            if isinstance(subjects, str):
                subjects = [subjects]

            return IAItem(
                identifier=identifier,
                title=metadata.get("title", "Unknown"),
                creator=metadata.get("creator"),
                date=metadata.get("date"),
                description=metadata.get("description"),
                mediatype=metadata.get("mediatype"),
                subjects=subjects,
            )

    except httpx.HTTPError:
        return None


def list_item_files(identifier: str, timeout: float = 30.0) -> list[IAFile]:
    """List files available for an Internet Archive item.

    Args:
        identifier: The IA identifier
        timeout: Request timeout

    Returns:
        List of IAFile objects
    """
    url = f"{METADATA_URL}/{identifier}/files"

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

            files = []
            for file_info in data.get("result", []):
                files.append(IAFile(
                    name=file_info.get("name", ""),
                    format=file_info.get("format", ""),
                    size=file_info.get("size"),
                    source=file_info.get("source"),
                ))

            return files

    except httpx.HTTPError:
        return []


def get_text_file(identifier: str, timeout: float = 60.0) -> str | None:
    """Get the best available text file for an item.

    Prefers plain text, then DjVu text, then OCR.

    Args:
        identifier: The IA identifier
        timeout: Request timeout

    Returns:
        Text content or None
    """
    files = list_item_files(identifier, timeout)

    # Priority order for text formats
    text_formats = [
        "Text",
        "DjVuTXT",
        "Plain Text",
    ]

    # Find best text file
    text_file = None
    for fmt in text_formats:
        for f in files:
            if f.format == fmt:
                text_file = f.name
                break
        if text_file:
            break

    # Fallback: any .txt file
    if not text_file:
        for f in files:
            if f.name.endswith(".txt"):
                text_file = f.name
                break

    if not text_file:
        return None

    # Download the text file
    url = f"{DOWNLOAD_URL}/{identifier}/{quote(text_file)}"

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text

    except httpx.HTTPError:
        return None


def search_items(
    query: str,
    mediatype: str = "texts",
    rows: int = 50,
    timeout: float = 30.0,
) -> list[IAItem]:
    """Search Internet Archive.

    Args:
        query: Search query
        mediatype: Media type filter (e.g., "texts", "audio")
        rows: Maximum results to return
        timeout: Request timeout

    Returns:
        List of matching IAItem objects
    """
    params = {
        "q": f"{query} AND mediatype:{mediatype}",
        "output": "json",
        "rows": rows,
        "fl[]": ["identifier", "title", "creator", "date", "description"],
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(SEARCH_URL, params=params)
            response.raise_for_status()
            data = response.json()

            items = []
            for doc in data.get("response", {}).get("docs", []):
                items.append(IAItem(
                    identifier=doc.get("identifier", ""),
                    title=doc.get("title", "Unknown"),
                    creator=doc.get("creator"),
                    date=doc.get("date"),
                    description=doc.get("description"),
                    mediatype=mediatype,
                ))

            return items

    except httpx.HTTPError:
        return []


def search_wwi_sources(
    keywords: list[str] | None = None,
    rows: int = 100,
) -> list[IAItem]:
    """Search for WWI primary sources.

    Args:
        keywords: Additional keywords to search
        rows: Maximum results

    Returns:
        List of matching items
    """
    base_query = '(subject:"World War, 1914-1918" OR subject:"World War I")'

    if keywords:
        keyword_query = " OR ".join(f'"{k}"' for k in keywords)
        query = f"{base_query} AND ({keyword_query})"
    else:
        query = base_query

    return search_items(query, mediatype="texts", rows=rows)


def download_item_text(
    identifier: str,
    output_dir: Path,
    delay: float = 1.0,
) -> Path | None:
    """Download text for an item and save to file.

    Args:
        identifier: The IA identifier
        output_dir: Directory to save file
        delay: Delay after download (rate limiting)

    Returns:
        Path to saved file or None
    """
    text = get_text_file(identifier)

    if not text:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{identifier}.txt"
    output_path.write_text(text)

    if delay > 0:
        time.sleep(delay)

    return output_path


def check_item_availability(identifier: str) -> dict:
    """Check if an item is available and has text.

    Args:
        identifier: The IA identifier

    Returns:
        Dict with availability info
    """
    result = {
        "identifier": identifier,
        "exists": False,
        "has_text": False,
        "title": None,
        "text_format": None,
    }

    metadata = get_item_metadata(identifier)
    if not metadata:
        return result

    result["exists"] = True
    result["title"] = metadata.title

    files = list_item_files(identifier)
    text_formats = ["Text", "DjVuTXT", "Plain Text"]

    for f in files:
        if f.format in text_formats or f.name.endswith(".txt"):
            result["has_text"] = True
            result["text_format"] = f.format or "txt"
            break

    return result
