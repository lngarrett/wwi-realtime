"""Source ingestion pipeline.

Downloads sources from Gutenberg, parses into passages, and stores in database.
"""

import sqlite3
import time
from pathlib import Path

from wwi_realtime.sources.gutenberg import (
    download_text,
    clean_gutenberg_text,
    get_book_metadata,
)
from wwi_realtime.sources.parser import parse_source_text, save_passages
from wwi_realtime.sources.curator import get_available_sources


def ingest_source(
    conn: sqlite3.Connection,
    source_id: str,
    gutenberg_id: str,
    topics: list[str] | None = None,
    save_raw: bool = False,
    raw_dir: Path | str = "data/sources",
) -> int:
    """Ingest a single source from Gutenberg.

    Args:
        conn: Database connection
        source_id: Internal source ID
        gutenberg_id: Gutenberg book ID
        topics: Optional topics to tag passages with
        save_raw: Whether to save raw text to file
        raw_dir: Directory for raw text files

    Returns:
        Number of passages created, or -1 on error
    """
    print(f"Ingesting {source_id} (Gutenberg #{gutenberg_id})...")

    # Download text
    text = download_text(gutenberg_id)
    if not text:
        print(f"  Failed to download")
        return -1

    # Clean boilerplate
    cleaned = clean_gutenberg_text(text)
    word_count = len(cleaned.split())
    print(f"  Downloaded {word_count:,} words")

    # Optionally save raw text
    if save_raw:
        raw_dir = Path(raw_dir)
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{source_id}.txt"
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(cleaned)
        print(f"  Saved to {raw_path}")

    # Parse into passages
    passages = parse_source_text(source_id, cleaned, topics=topics)
    print(f"  Parsed into {len(passages)} passages")

    # Check for quotes
    quote_count = sum(1 for p in passages if p.has_direct_quote)
    print(f"  Found {quote_count} passages with direct quotes")

    # Save to database
    count = save_passages(conn, passages)

    # Mark source as ingested
    conn.execute(
        "UPDATE canonical_sources SET ingested = 1 WHERE id = ?",
        (source_id,)
    )
    conn.commit()

    print(f"  Stored {count} passages in database")
    return count


def ingest_available_sources(
    conn: sqlite3.Connection,
    priority_max: int = 2,
    limit: int | None = None,
    delay: float = 1.0,
    save_raw: bool = True,
) -> dict:
    """Ingest all available Gutenberg sources.

    Args:
        conn: Database connection
        priority_max: Maximum priority to ingest (1 = highest only)
        limit: Maximum number of sources to ingest
        delay: Delay between downloads (be nice to servers)
        save_raw: Whether to save raw text files

    Returns:
        Dict with counts: {ingested: N, skipped: N, failed: N}
    """
    cursor = conn.execute(
        """SELECT id, gutenberg_id, title
           FROM canonical_sources
           WHERE gutenberg_id IS NOT NULL
             AND available = 1
             AND ingested = 0
             AND priority <= ?
           ORDER BY priority, title""",
        (priority_max,)
    )
    sources = cursor.fetchall()

    if limit:
        sources = sources[:limit]

    results = {"ingested": 0, "skipped": 0, "failed": 0}

    for source_id, gutenberg_id, title in sources:
        print(f"\n{'='*60}")
        print(f"Source: {title}")

        # Get topics from source coverage
        topic_cursor = conn.execute(
            "SELECT topic FROM source_coverage WHERE source_id = ?",
            (source_id,)
        )
        topics = [row[0] for row in topic_cursor.fetchall() if row[0]]

        count = ingest_source(
            conn,
            source_id,
            gutenberg_id,
            topics=topics or None,
            save_raw=save_raw,
        )

        if count > 0:
            results["ingested"] += 1
        elif count == 0:
            results["skipped"] += 1
        else:
            results["failed"] += 1

        time.sleep(delay)

    return results


def get_ingestion_stats(conn: sqlite3.Connection) -> dict:
    """Get statistics about ingested sources."""
    stats = {}

    # Source counts
    cursor = conn.execute(
        "SELECT COUNT(*) FROM canonical_sources WHERE available = 1"
    )
    stats["available"] = cursor.fetchone()[0]

    cursor = conn.execute(
        "SELECT COUNT(*) FROM canonical_sources WHERE ingested = 1"
    )
    stats["ingested"] = cursor.fetchone()[0]

    cursor = conn.execute(
        "SELECT COUNT(*) FROM canonical_sources WHERE gutenberg_id IS NOT NULL"
    )
    stats["gutenberg"] = cursor.fetchone()[0]

    # Passage counts
    cursor = conn.execute("SELECT COUNT(*) FROM source_passages")
    stats["passages"] = cursor.fetchone()[0]

    cursor = conn.execute(
        "SELECT COUNT(*) FROM source_passages WHERE has_direct_quote = 1"
    )
    stats["passages_with_quotes"] = cursor.fetchone()[0]

    cursor = conn.execute("SELECT SUM(word_count) FROM source_passages")
    stats["total_words"] = cursor.fetchone()[0] or 0

    return stats


def verify_ingestion(conn: sqlite3.Connection, source_id: str) -> dict | None:
    """Verify a source was ingested correctly.

    Returns passage stats or None if not ingested.
    """
    cursor = conn.execute(
        "SELECT ingested FROM canonical_sources WHERE id = ?",
        (source_id,)
    )
    row = cursor.fetchone()
    if not row or not row[0]:
        return None

    cursor = conn.execute(
        """SELECT COUNT(*) as count,
                  SUM(word_count) as words,
                  SUM(CASE WHEN has_direct_quote THEN 1 ELSE 0 END) as quotes
           FROM source_passages WHERE source_id = ?""",
        (source_id,)
    )
    row = cursor.fetchone()

    return {
        "passages": row[0],
        "words": row[1] or 0,
        "quotes": row[2] or 0,
    }
