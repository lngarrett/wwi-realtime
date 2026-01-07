"""Passage parser for splitting source texts into searchable chunks.

Splits downloaded texts into passages suitable for FTS indexing and retrieval.
"""

import hashlib
import re
import sqlite3
from dataclasses import dataclass

from wwi_realtime.sources.date_extractor import extract_date_references


@dataclass
class Passage:
    """A parsed passage from a source text."""
    id: str
    source_id: str
    content: str
    sequence_num: int
    page_or_chapter: str | None = None
    date_referenced: str | None = None  # ISO date
    date_approximate: str | None = None  # "August 1914"
    has_direct_quote: bool = False
    topics: list[str] | None = None
    word_count: int = 0


# Target passage size (characters)
MIN_PASSAGE_SIZE = 300
MAX_PASSAGE_SIZE = 1200
TARGET_PASSAGE_SIZE = 600

# Patterns for chapter/section detection
CHAPTER_PATTERNS = [
    r'^CHAPTER\s+([IVXLCDM]+|\d+)',  # CHAPTER I, CHAPTER 1
    r'^Chapter\s+([IVXLCDM]+|\d+)',
    r'^PART\s+([IVXLCDM]+|\d+)',
    r'^\d+\.\s+[A-Z]',  # "1. The Beginning"
    r'^[IVXLCDM]+\.\s+[A-Z]',  # "I. The Beginning"
]

# Patterns for detecting direct quotes
QUOTE_PATTERNS = [
    r'"[^"]{20,}"',  # Double quotes with at least 20 chars
    r"'[^']{20,}'",  # Single quotes with at least 20 chars
    r'"[^"]{20,}"',  # Smart quotes
]


def has_direct_quote(text: str) -> bool:
    """Check if passage contains a substantial direct quote."""
    for pattern in QUOTE_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def detect_chapter(text: str) -> str | None:
    """Detect if text starts with a chapter heading."""
    first_line = text.strip().split('\n')[0] if text else ""

    for pattern in CHAPTER_PATTERNS:
        match = re.match(pattern, first_line)
        if match:
            return first_line.strip()

    return None


def find_split_point(text: str, target_pos: int) -> int:
    """Find a good split point near target position.

    Prefers splitting at paragraph breaks, then sentence ends.
    """
    # Look for paragraph break near target
    search_start = max(0, target_pos - 200)
    search_end = min(len(text), target_pos + 200)
    search_region = text[search_start:search_end]

    # Prefer double newline (paragraph break)
    para_break = search_region.rfind('\n\n')
    if para_break != -1:
        return search_start + para_break + 2

    # Try single newline
    newline = search_region.rfind('\n')
    if newline != -1:
        return search_start + newline + 1

    # Try sentence end (. followed by space or newline)
    sentence_end = -1
    for match in re.finditer(r'[.!?]\s+', search_region):
        if match.end() <= target_pos - search_start + 100:
            sentence_end = match.end()

    if sentence_end != -1:
        return search_start + sentence_end

    # Fallback to target position
    return target_pos


def split_into_passages(text: str, source_id: str) -> list[Passage]:
    """Split text into passages of appropriate size.

    Args:
        text: The full text to split
        source_id: ID of the source this text comes from

    Returns:
        List of Passage objects
    """
    passages = []
    current_chapter = None
    sequence_num = 0

    # Normalize whitespace
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    pos = 0
    while pos < len(text):
        # Check for chapter at current position
        remaining = text[pos:]
        chapter = detect_chapter(remaining)
        if chapter:
            current_chapter = chapter

        # Find end of this passage
        end_pos = find_split_point(text, pos + TARGET_PASSAGE_SIZE)

        # Ensure minimum size
        if end_pos - pos < MIN_PASSAGE_SIZE and end_pos < len(text):
            end_pos = find_split_point(text, pos + MIN_PASSAGE_SIZE)

        # Extract passage content
        content = text[pos:end_pos].strip()

        if len(content) > 50:  # Skip very short fragments
            # Extract date info
            date_ref, date_approx = extract_date_references(content)

            passage_id = hashlib.md5(
                f"{source_id}:{sequence_num}:{content[:100]}".encode()
            ).hexdigest()[:16]

            passages.append(Passage(
                id=passage_id,
                source_id=source_id,
                content=content,
                sequence_num=sequence_num,
                page_or_chapter=current_chapter,
                date_referenced=date_ref,
                date_approximate=date_approx,
                has_direct_quote=has_direct_quote(content),
                word_count=len(content.split()),
            ))
            sequence_num += 1

        pos = end_pos

    return passages


def parse_source_text(
    source_id: str,
    text: str,
    topics: list[str] | None = None,
) -> list[Passage]:
    """Parse a source text into passages with metadata.

    Args:
        source_id: ID of the source
        text: Full text content
        topics: Optional list of topics to tag all passages with

    Returns:
        List of Passage objects ready for database insertion
    """
    passages = split_into_passages(text, source_id)

    # Apply topics if provided
    if topics:
        for passage in passages:
            passage.topics = topics

    return passages


def save_passages(conn: sqlite3.Connection, passages: list[Passage]) -> int:
    """Save passages to database.

    Args:
        conn: Database connection
        passages: List of Passage objects

    Returns:
        Number of passages inserted
    """
    import json

    count = 0
    for passage in passages:
        topics_json = json.dumps(passage.topics) if passage.topics else None

        conn.execute(
            """INSERT OR REPLACE INTO source_passages
            (id, source_id, content, sequence_num, page_or_chapter,
             date_referenced, date_approximate, has_direct_quote, topics, word_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                passage.id,
                passage.source_id,
                passage.content,
                passage.sequence_num,
                passage.page_or_chapter,
                passage.date_referenced,
                passage.date_approximate,
                passage.has_direct_quote,
                topics_json,
                passage.word_count,
            )
        )
        count += 1

    conn.commit()
    return count


def get_passages_for_source(
    conn: sqlite3.Connection,
    source_id: str,
) -> list[dict]:
    """Get all passages for a source, ordered by sequence."""
    cursor = conn.execute(
        """SELECT id, source_id, content, sequence_num, page_or_chapter,
                  date_referenced, date_approximate, has_direct_quote, topics, word_count
           FROM source_passages
           WHERE source_id = ?
           ORDER BY sequence_num""",
        (source_id,)
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def search_passages(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
) -> list[dict]:
    """Search passages using full-text search.

    Args:
        conn: Database connection
        query: FTS query string
        limit: Maximum results to return

    Returns:
        List of passage dicts with source info
    """
    cursor = conn.execute(
        """SELECT sp.id, sp.source_id, sp.content, sp.date_approximate,
                  sp.has_direct_quote, sp.word_count,
                  cs.title as source_title, cs.author as source_author
           FROM source_passages_fts fts
           JOIN source_passages sp ON fts.rowid = sp.rowid
           JOIN canonical_sources cs ON sp.source_id = cs.id
           WHERE source_passages_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (query, limit)
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_passages_with_quotes(
    conn: sqlite3.Connection,
    source_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Get passages that contain direct quotes.

    Args:
        conn: Database connection
        source_id: Optional source ID to filter by
        limit: Maximum results

    Returns:
        List of passage dicts
    """
    if source_id:
        cursor = conn.execute(
            """SELECT sp.id, sp.source_id, sp.content, sp.date_approximate,
                      cs.title as source_title, cs.author as source_author
               FROM source_passages sp
               JOIN canonical_sources cs ON sp.source_id = cs.id
               WHERE sp.has_direct_quote = 1 AND sp.source_id = ?
               ORDER BY sp.sequence_num
               LIMIT ?""",
            (source_id, limit)
        )
    else:
        cursor = conn.execute(
            """SELECT sp.id, sp.source_id, sp.content, sp.date_approximate,
                      cs.title as source_title, cs.author as source_author
               FROM source_passages sp
               JOIN canonical_sources cs ON sp.source_id = cs.id
               WHERE sp.has_direct_quote = 1
               ORDER BY RANDOM()
               LIMIT ?""",
            (limit,)
        )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
