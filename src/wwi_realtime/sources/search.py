"""Source passage search and retrieval.

Query passages relevant to events, arcs, dates, and topics.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date


@dataclass
class PassageResult:
    """A passage search result with source metadata."""
    passage_id: str
    source_id: str
    content: str
    source_title: str
    source_author: str
    source_type: str | None
    source_perspective: str | None
    has_direct_quote: bool
    date_approximate: str | None
    word_count: int
    relevance_score: float = 0.0


def sanitize_fts_query(query: str) -> str:
    """Sanitize a query string for FTS5.

    Removes or escapes special characters that break FTS5 syntax.
    """
    import re
    # Remove special FTS5 operators and punctuation
    # Keep only alphanumeric, spaces, and basic operators
    sanitized = re.sub(r'[^\w\s]', ' ', query)
    # Collapse multiple spaces
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized


def search_passages_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
) -> list[PassageResult]:
    """Search passages using full-text search.

    Args:
        conn: Database connection
        query: FTS query (supports AND, OR, phrase matching)
        limit: Maximum results

    Returns:
        List of PassageResult objects
    """
    # Sanitize query to prevent FTS5 syntax errors
    safe_query = sanitize_fts_query(query)
    if not safe_query:
        return []

    cursor = conn.execute(
        """SELECT sp.id, sp.source_id, sp.content,
                  cs.title, cs.author, cs.type, cs.perspective,
                  sp.has_direct_quote, sp.date_approximate, sp.word_count,
                  rank
           FROM source_passages_fts fts
           JOIN source_passages sp ON fts.rowid = sp.rowid
           JOIN canonical_sources cs ON sp.source_id = cs.id
           WHERE source_passages_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (safe_query, limit)
    )

    results = []
    for row in cursor.fetchall():
        results.append(PassageResult(
            passage_id=row[0],
            source_id=row[1],
            content=row[2],
            source_title=row[3],
            source_author=row[4],
            source_type=row[5],
            source_perspective=row[6],
            has_direct_quote=bool(row[7]),
            date_approximate=row[8],
            word_count=row[9],
            relevance_score=abs(row[10]) if row[10] else 0,
        ))

    return results


def get_passages_for_arc(
    conn: sqlite3.Connection,
    arc_id: str,
    with_quotes_only: bool = False,
    limit: int = 50,
) -> list[PassageResult]:
    """Get passages from sources that cover a specific arc.

    Args:
        conn: Database connection
        arc_id: Arc ID to get passages for
        with_quotes_only: Only return passages with direct quotes
        limit: Maximum results

    Returns:
        List of PassageResult objects
    """
    quote_filter = "AND sp.has_direct_quote = 1" if with_quotes_only else ""

    cursor = conn.execute(
        f"""SELECT DISTINCT sp.id, sp.source_id, sp.content,
                   cs.title, cs.author, cs.type, cs.perspective,
                   sp.has_direct_quote, sp.date_approximate, sp.word_count
            FROM source_passages sp
            JOIN canonical_sources cs ON sp.source_id = cs.id
            JOIN source_coverage sc ON cs.id = sc.source_id
            WHERE sc.arc_id = ? {quote_filter}
            ORDER BY cs.priority, sp.sequence_num
            LIMIT ?""",
        (arc_id, limit)
    )

    results = []
    for row in cursor.fetchall():
        results.append(PassageResult(
            passage_id=row[0],
            source_id=row[1],
            content=row[2],
            source_title=row[3],
            source_author=row[4],
            source_type=row[5],
            source_perspective=row[6],
            has_direct_quote=bool(row[7]),
            date_approximate=row[8],
            word_count=row[9],
        ))

    return results


def get_passages_for_date(
    conn: sqlite3.Connection,
    target_date: date,
    tolerance_days: int = 7,
    limit: int = 30,
) -> list[PassageResult]:
    """Get passages mentioning dates near a target date.

    Args:
        conn: Database connection
        target_date: Target date to search for
        tolerance_days: Days before/after to include
        limit: Maximum results

    Returns:
        List of PassageResult objects
    """
    start = (target_date.toordinal() - tolerance_days)
    end = (target_date.toordinal() + tolerance_days)

    cursor = conn.execute(
        """SELECT sp.id, sp.source_id, sp.content,
                  cs.title, cs.author, cs.type, cs.perspective,
                  sp.has_direct_quote, sp.date_approximate, sp.word_count,
                  sp.date_referenced
           FROM source_passages sp
           JOIN canonical_sources cs ON sp.source_id = cs.id
           WHERE sp.date_referenced IS NOT NULL
             AND julianday(sp.date_referenced) BETWEEN julianday(?) AND julianday(?)
           ORDER BY ABS(julianday(sp.date_referenced) - julianday(?))
           LIMIT ?""",
        (
            date.fromordinal(start).isoformat(),
            date.fromordinal(end).isoformat(),
            target_date.isoformat(),
            limit,
        )
    )

    results = []
    for row in cursor.fetchall():
        results.append(PassageResult(
            passage_id=row[0],
            source_id=row[1],
            content=row[2],
            source_title=row[3],
            source_author=row[4],
            source_type=row[5],
            source_perspective=row[6],
            has_direct_quote=bool(row[7]),
            date_approximate=row[8],
            word_count=row[9],
        ))

    return results


def get_passages_for_topic(
    conn: sqlite3.Connection,
    topic: str,
    with_quotes_only: bool = False,
    limit: int = 30,
) -> list[PassageResult]:
    """Get passages from sources covering a specific topic.

    Args:
        conn: Database connection
        topic: Topic to search for
        with_quotes_only: Only return passages with direct quotes
        limit: Maximum results

    Returns:
        List of PassageResult objects
    """
    quote_filter = "AND sp.has_direct_quote = 1" if with_quotes_only else ""

    cursor = conn.execute(
        f"""SELECT DISTINCT sp.id, sp.source_id, sp.content,
                   cs.title, cs.author, cs.type, cs.perspective,
                   sp.has_direct_quote, sp.date_approximate, sp.word_count
            FROM source_passages sp
            JOIN canonical_sources cs ON sp.source_id = cs.id
            JOIN source_coverage sc ON cs.id = sc.source_id
            WHERE sc.topic = ? {quote_filter}
            ORDER BY cs.priority, RANDOM()
            LIMIT ?""",
        (topic, limit)
    )

    results = []
    for row in cursor.fetchall():
        results.append(PassageResult(
            passage_id=row[0],
            source_id=row[1],
            content=row[2],
            source_title=row[3],
            source_author=row[4],
            source_type=row[5],
            source_perspective=row[6],
            has_direct_quote=bool(row[7]),
            date_approximate=row[8],
            word_count=row[9],
        ))

    return results


def get_quotes_for_event(
    conn: sqlite3.Connection,
    event_title: str,
    arc_id: str | None = None,
    event_date: date | None = None,
    limit: int = 10,
) -> list[PassageResult]:
    """Get relevant quoted passages for an event.

    Searches by:
    1. FTS match on event title keywords
    2. Arc coverage if arc_id provided
    3. Date proximity if event_date provided

    Args:
        conn: Database connection
        event_title: Event title for keyword search
        arc_id: Optional arc ID for coverage filtering
        event_date: Optional event date for date proximity
        limit: Maximum results

    Returns:
        List of PassageResult objects with direct quotes
    """
    results = []

    # Extract meaningful keywords from title
    stop_words = {'the', 'of', 'at', 'in', 'on', 'a', 'an', 'and', 'or', 'first', 'second', 'third'}
    keywords = [w for w in event_title.lower().split() if w not in stop_words and len(w) > 2]

    # FTS search for keywords
    if keywords:
        query = ' OR '.join(keywords[:5])  # Limit keywords
        fts_results = search_passages_fts(conn, query, limit=limit * 2)
        # Filter to only quotes
        results.extend([r for r in fts_results if r.has_direct_quote][:limit // 2])

    # Arc-based search
    if arc_id:
        arc_results = get_passages_for_arc(conn, arc_id, with_quotes_only=True, limit=limit)
        for r in arc_results:
            if r.passage_id not in {p.passage_id for p in results}:
                results.append(r)
                if len(results) >= limit:
                    break

    # Date-based search
    if event_date and len(results) < limit:
        date_results = get_passages_for_date(conn, event_date, tolerance_days=30, limit=limit)
        for r in date_results:
            if r.has_direct_quote and r.passage_id not in {p.passage_id for p in results}:
                results.append(r)
                if len(results) >= limit:
                    break

    return results[:limit]


def get_diverse_perspectives(
    conn: sqlite3.Connection,
    arc_id: str,
    limit_per_perspective: int = 3,
) -> dict[str, list[PassageResult]]:
    """Get passages from multiple perspectives for an arc.

    Args:
        conn: Database connection
        arc_id: Arc ID
        limit_per_perspective: Max passages per perspective

    Returns:
        Dict mapping perspective to list of passages
    """
    # Get all perspectives for this arc
    cursor = conn.execute(
        """SELECT DISTINCT cs.perspective
           FROM canonical_sources cs
           JOIN source_coverage sc ON cs.id = sc.source_id
           WHERE sc.arc_id = ? AND cs.perspective IS NOT NULL""",
        (arc_id,)
    )
    perspectives = [row[0] for row in cursor.fetchall()]

    results = {}
    for perspective in perspectives:
        cursor = conn.execute(
            """SELECT sp.id, sp.source_id, sp.content,
                      cs.title, cs.author, cs.type, cs.perspective,
                      sp.has_direct_quote, sp.date_approximate, sp.word_count
               FROM source_passages sp
               JOIN canonical_sources cs ON sp.source_id = cs.id
               JOIN source_coverage sc ON cs.id = sc.source_id
               WHERE sc.arc_id = ? AND cs.perspective = ?
               ORDER BY sp.has_direct_quote DESC, RANDOM()
               LIMIT ?""",
            (arc_id, perspective, limit_per_perspective)
        )

        perspective_results = []
        for row in cursor.fetchall():
            perspective_results.append(PassageResult(
                passage_id=row[0],
                source_id=row[1],
                content=row[2],
                source_title=row[3],
                source_author=row[4],
                source_type=row[5],
                source_perspective=row[6],
                has_direct_quote=bool(row[7]),
                date_approximate=row[8],
                word_count=row[9],
            ))

        if perspective_results:
            results[perspective] = perspective_results

    return results


def get_vivid_passages(
    conn: sqlite3.Connection,
    limit: int = 50,
    min_words: int = 30,
    max_words: int = 120,
) -> list[PassageResult]:
    """Get the most vivid, tweetable passages from all sources.

    Finds passages with:
    - Direct quotes
    - Combat/emotional keywords
    - Good length for tweets
    - Diverse sources

    Args:
        conn: Database connection
        limit: Maximum results
        min_words: Minimum word count
        max_words: Maximum word count

    Returns:
        List of vivid PassageResult objects
    """
    # Keywords that indicate vivid, tweetable content
    vivid_keywords = [
        # Combat action
        "attack", "assault", "charge", "shell", "bullet",
        "machine gun", "artillery", "trench", "wire", "bayonet",
        "bombardment", "barrage", "explosion", "fire",
        # Death and wounds
        "killed", "wounded", "dead", "dying", "blood",
        "stretcher", "hospital", "casualty", "casualties",
        # First person intensity
        "I saw", "I heard", "I felt", "we went", "we were",
        "my heart", "my hands", "terrified", "afraid",
        # Sensory/emotional
        "screaming", "crying", "silence", "noise", "stench",
        "mud", "rain", "cold", "exhausted", "sleep",
        # Dialogue markers (good for tweets)
        "he said", "she said", "I said", "replied", "shouted",
        "whispered", "yelled", "asked", "answered",
    ]

    # Build SQL with keyword matching
    keyword_conditions = " OR ".join([f"sp.content LIKE '%{kw}%'" for kw in vivid_keywords])

    cursor = conn.execute(
        f"""SELECT sp.id, sp.source_id, sp.content,
                  cs.title, cs.author, cs.type, cs.perspective,
                  sp.has_direct_quote, sp.date_approximate, sp.word_count
           FROM source_passages sp
           JOIN canonical_sources cs ON sp.source_id = cs.id
           WHERE sp.has_direct_quote = 1
           AND sp.word_count BETWEEN ? AND ?
           AND ({keyword_conditions})
           ORDER BY RANDOM()
           LIMIT ?""",
        (min_words, max_words, limit * 3)  # Get extra to filter
    )

    results = []
    seen_content_starts = set()  # Dedupe similar passages

    for row in cursor.fetchall():
        content = row[2]
        # Skip if we have similar content
        content_start = content[:50]
        if content_start in seen_content_starts:
            continue
        seen_content_starts.add(content_start)

        results.append(PassageResult(
            passage_id=row[0],
            source_id=row[1],
            content=content,
            source_title=row[3],
            source_author=row[4],
            source_type=row[5],
            source_perspective=row[6],
            has_direct_quote=bool(row[7]),
            date_approximate=row[8],
            word_count=row[9],
        ))

        if len(results) >= limit:
            break

    return results


def get_passages_for_period(
    conn: sqlite3.Connection,
    year: int,
    sources_to_include: list[str] | None = None,
    limit: int = 40,
) -> list[PassageResult]:
    """Get vivid passages relevant to a time period.

    Uses source metadata and date_approximate to find period-relevant content.

    Args:
        conn: Database connection
        year: Year to find passages for
        sources_to_include: Optional list of source IDs to limit to
        limit: Maximum results

    Returns:
        List of PassageResult objects
    """
    # Find passages with approximate dates matching this year
    year_patterns = [f"%{year}%", f"%{year-1}%", f"%{year+1}%"]

    conditions = []
    params = []

    for pattern in year_patterns:
        conditions.append("sp.date_approximate LIKE ?")
        params.append(pattern)

    where_clause = " OR ".join(conditions)

    if sources_to_include:
        placeholders = ",".join(["?" for _ in sources_to_include])
        where_clause = f"({where_clause}) AND sp.source_id IN ({placeholders})"
        params.extend(sources_to_include)

    params.extend([30, 150, limit])

    cursor = conn.execute(
        f"""SELECT sp.id, sp.source_id, sp.content,
                  cs.title, cs.author, cs.type, cs.perspective,
                  sp.has_direct_quote, sp.date_approximate, sp.word_count
           FROM source_passages sp
           JOIN canonical_sources cs ON sp.source_id = cs.id
           WHERE ({where_clause})
           AND sp.has_direct_quote = 1
           AND sp.word_count BETWEEN ? AND ?
           ORDER BY RANDOM()
           LIMIT ?""",
        params
    )

    results = []
    for row in cursor.fetchall():
        results.append(PassageResult(
            passage_id=row[0],
            source_id=row[1],
            content=row[2],
            source_title=row[3],
            source_author=row[4],
            source_type=row[5],
            source_perspective=row[6],
            has_direct_quote=bool(row[7]),
            date_approximate=row[8],
            word_count=row[9],
        ))

    return results
