"""Research module for assembling generation context.

Queries sources, arcs, and passages to build complete context
for tweet generation.
"""

import sqlite3
from datetime import date

from wwi_realtime.framework.arcs import get_arc, get_arcs_for_date, get_all_arcs
from wwi_realtime.sources.search import (
    PassageResult,
    get_passages_for_arc,
    get_quotes_for_event,
    get_diverse_perspectives,
    get_passages_for_date,
    get_vivid_passages,
)
from wwi_realtime.generate.prompts import EventContext, GenerationContext


def get_event_context(
    conn: sqlite3.Connection,
    event: dict,
) -> EventContext:
    """Build EventContext from an event dict.

    Args:
        conn: Database connection
        event: Event dict from database

    Returns:
        EventContext object
    """
    # Parse date
    event_date = event.get("date")
    if isinstance(event_date, str):
        event_date = date.fromisoformat(event_date)

    # Get arc info if arc_id present
    arc_id = event.get("arc_id")
    arc_title = None
    arc_narrative = None

    if arc_id:
        arc = get_arc(conn, arc_id)
        if arc:
            arc_title = arc["title"]
            arc_narrative = arc.get("narrative_summary")

    # If no arc_id, try to infer from date
    if not arc_id and event_date:
        active_arcs = get_arcs_for_date(conn, event_date)
        if active_arcs:
            # Use first active arc (typically the most specific)
            arc = active_arcs[0]
            arc_id = arc["id"]
            arc_title = arc["title"]
            arc_narrative = arc.get("narrative_summary")

    return EventContext(
        title=event.get("title", "Unknown Event"),
        date=event_date,
        summary=event.get("summary", ""),
        wikipedia_url=event.get("wikipedia_url"),
        arc_id=arc_id,
        arc_title=arc_title,
        arc_narrative=arc_narrative,
    )


def research_event(
    conn: sqlite3.Connection,
    event: dict,
    max_passages: int = 5,
    include_perspectives: bool = True,
) -> GenerationContext:
    """Research an event and build full generation context.

    Args:
        conn: Database connection
        event: Event dict from database
        max_passages: Maximum passages to include
        include_perspectives: Whether to include multi-perspective section

    Returns:
        GenerationContext with all relevant material
    """
    event_context = get_event_context(conn, event)

    # Get relevant passages
    passages = get_quotes_for_event(
        conn,
        event_context.title,
        arc_id=event_context.arc_id,
        event_date=event_context.date,
        limit=max_passages,
    )

    # Get diverse perspectives if requested and arc available
    diverse_perspectives = None
    if include_perspectives and event_context.arc_id:
        diverse_perspectives = get_diverse_perspectives(
            conn,
            event_context.arc_id,
            limit_per_perspective=2,
        )

    return GenerationContext(
        event=event_context,
        passages=passages,
        diverse_perspectives=diverse_perspectives,
    )


def research_month(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    events_by_date: dict[str, list[dict]],
    max_passages_per_event: int = 3,
) -> dict:
    """Research all events in a month.

    Args:
        conn: Database connection
        year: Year
        month: Month (1-12)
        events_by_date: Events grouped by date
        max_passages_per_event: Max passages per event

    Returns:
        Dict with:
        - event_contexts: list of EventContext
        - passages_by_event: dict mapping event title to passages
        - arc_narratives: dict mapping arc_id to narrative
        - active_arcs: list of arcs active this month
    """
    event_contexts = []
    passages_by_event = {}
    arc_narratives = {}
    seen_arcs = set()

    for date_str, events in events_by_date.items():
        for event in events:
            # Build context
            ctx = get_event_context(conn, event)
            event_contexts.append(ctx)

            # Get passages for this event
            passages = get_quotes_for_event(
                conn,
                ctx.title,
                arc_id=ctx.arc_id,
                event_date=ctx.date,
                limit=max_passages_per_event,
            )
            if passages:
                passages_by_event[ctx.title] = passages

            # Collect arc narrative
            if ctx.arc_id and ctx.arc_id not in seen_arcs:
                seen_arcs.add(ctx.arc_id)
                arc = get_arc(conn, ctx.arc_id)
                if arc and arc.get("narrative_summary"):
                    arc_narratives[ctx.arc_id] = arc["narrative_summary"]

    # Get all active arcs for the month
    # Use middle of month for query
    mid_month = date(year, month, 15)
    active_arcs = get_arcs_for_date(conn, mid_month)

    return {
        "event_contexts": event_contexts,
        "passages_by_event": passages_by_event,
        "arc_narratives": arc_narratives,
        "active_arcs": active_arcs,
    }


def get_passages_for_month(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    limit: int = 50,
) -> list[PassageResult]:
    """Get all relevant passages for a month.

    Combines passages from:
    - Date references in the month
    - Topics relevant to active arcs

    Args:
        conn: Database connection
        year: Year
        month: Month
        limit: Maximum total passages

    Returns:
        List of PassageResult objects
    """
    results = []

    # Get passages with dates in this month
    # Check multiple dates across the month
    for day in [1, 8, 15, 22]:
        try:
            target = date(year, month, day)
            date_passages = get_passages_for_date(
                conn, target, tolerance_days=7, limit=limit // 4
            )
            for p in date_passages:
                if p.passage_id not in {r.passage_id for r in results}:
                    results.append(p)
        except ValueError:
            pass  # Invalid date (e.g., Feb 30)

    # Get passages from active arcs
    mid_month = date(year, month, 15)
    active_arcs = get_arcs_for_date(conn, mid_month)

    for arc in active_arcs[:3]:  # Limit arcs
        arc_passages = get_passages_for_arc(
            conn, arc["id"], with_quotes_only=True, limit=10
        )
        for p in arc_passages:
            if p.passage_id not in {r.passage_id for r in results}:
                results.append(p)
                if len(results) >= limit:
                    break
        if len(results) >= limit:
            break

    return results[:limit]


def format_research_summary(research: dict) -> str:
    """Format research results into a readable summary.

    Args:
        research: Output from research_month

    Returns:
        Formatted string summary
    """
    lines = []

    lines.append(f"Events: {len(research['event_contexts'])}")
    lines.append(f"Events with passages: {len(research['passages_by_event'])}")
    lines.append(f"Active arcs: {len(research['arc_narratives'])}")

    total_passages = sum(len(p) for p in research['passages_by_event'].values())
    lines.append(f"Total passages: {total_passages}")

    if research['arc_narratives']:
        lines.append("\nActive arcs:")
        for arc_id in research['arc_narratives']:
            lines.append(f"  - {arc_id.replace('_', ' ').title()}")

    return "\n".join(lines)


def research_month_vivid(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    events_by_date: dict[str, list[dict]],
    max_vivid_passages: int = 40,
) -> dict:
    """Research a month using vivid passage-first approach.

    Instead of searching for passages by event title (which returns junk),
    this finds the most vivid, tweetable passages and lets the LLM match
    them to events by topic.

    Args:
        conn: Database connection
        year: Year
        month: Month (1-12)
        events_by_date: Events grouped by date
        max_vivid_passages: Max vivid passages to include

    Returns:
        Dict with:
        - vivid_passages: list of best tweetable passages
        - events_by_date: events for context
        - event_count: total events
    """
    # Get vivid passages - these ARE the content
    vivid_passages = get_vivid_passages(
        conn,
        limit=max_vivid_passages,
        min_words=30,
        max_words=120,
    )

    # Count events
    event_count = sum(len(events) for events in events_by_date.values())

    return {
        "vivid_passages": vivid_passages,
        "events_by_date": events_by_date,
        "event_count": event_count,
    }


def research_month_hybrid(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    events_by_date: dict[str, list[dict]],
    max_passages_per_arc: int = 15,
) -> dict:
    """Research a month using hybrid approach: events + matched passages.

    The key insight from WWII account:
    - Events provide STRUCTURE (what happened, when)
    - Passages provide VOICE (quotes from people AT those events/arcs)
    - Arcs provide NARRATIVE (how events connect to larger story)

    Args:
        conn: Database connection
        year: Year
        month: Month (1-12)
        events_by_date: Events grouped by date
        max_passages_per_arc: Max passages per arc

    Returns:
        Dict with:
        - events_by_arc: events grouped by arc for narrative structure
        - passages_by_arc: passages from sources covering each arc
        - passages_by_event: passages matched to specific events
        - arc_summaries: narrative summary for each arc
    """
    # Group events by arc
    events_by_arc: dict[str, list[dict]] = {}
    for date_str, events in events_by_date.items():
        for event in events:
            arc_id = event.get("arc_id") or "general"
            if arc_id not in events_by_arc:
                events_by_arc[arc_id] = []
            events_by_arc[arc_id].append({**event, "date": date_str})

    # For each arc, find passages from sources that cover it
    passages_by_arc: dict[str, list[PassageResult]] = {}
    arc_summaries: dict[str, str] = {}

    for arc_id in events_by_arc.keys():
        # Get arc info
        arc = get_arc(conn, arc_id)
        if arc:
            arc_summaries[arc_id] = arc.get("narrative_summary") or arc.get("title", arc_id)

        # Find passages from sources that cover this arc
        passages = get_passages_for_arc(
            conn,
            arc_id,
            with_quotes_only=True,
            limit=max_passages_per_arc,
        )

        # If no arc-specific passages, try vivid passages with arc keywords
        if not passages:
            # Search for passages mentioning arc-related terms
            arc_title = arc.get("title", "") if arc else arc_id.replace("_", " ")
            passages = _search_passages_for_topic(conn, arc_title, limit=max_passages_per_arc)

        if passages:
            passages_by_arc[arc_id] = passages

    # NEW: Match passages to specific events by keywords
    passages_by_event: dict[str, list[PassageResult]] = {}
    all_events = [e for events in events_by_date.values() for e in events]

    for event in all_events:
        title = event.get("title", "")
        event_passages = _find_passages_for_event(conn, title, max_passages=5)
        if event_passages:
            passages_by_event[title] = event_passages

    return {
        "events_by_arc": events_by_arc,
        "passages_by_arc": passages_by_arc,
        "passages_by_event": passages_by_event,
        "arc_summaries": arc_summaries,
        "events_by_date": events_by_date,
    }


def _find_passages_for_event(
    conn: sqlite3.Connection,
    event_title: str,
    max_passages: int = 5,
) -> list[PassageResult]:
    """Find passages that might relate to a specific event.

    Uses keyword matching from event title to find relevant passages.
    Prioritizes quoted passages but includes narrative ones too.
    """
    from wwi_realtime.sources.search import search_passages_fts

    # Extract meaningful keywords from event title
    stop_words = {
        'the', 'of', 'at', 'in', 'on', 'a', 'an', 'and', 'or', 'to', 'for',
        'first', 'second', 'third', 'battle', 'siege', 'attack', 'offensive',
        'day', 'begins', 'ends', 'start', 'end', 'capture'
    }
    words = event_title.lower().split()
    keywords = [w for w in words if w not in stop_words and len(w) > 3]

    if not keywords:
        return []

    # Search for passages with these keywords
    query = ' '.join(keywords[:4])  # Limit keywords
    passages = search_passages_fts(conn, query, limit=max_passages * 4)

    # Filter to reasonable length
    passages = [p for p in passages if 20 <= p.word_count <= 200]

    # Prioritize quoted passages, then by word count
    passages.sort(key=lambda p: (not p.has_direct_quote, -p.word_count))

    return passages[:max_passages]


def _search_passages_for_topic(
    conn: sqlite3.Connection,
    topic: str,
    limit: int = 15,
) -> list[PassageResult]:
    """Search for vivid passages related to a topic."""
    from wwi_realtime.sources.search import search_passages_fts, get_vivid_passages

    # First try FTS search
    passages = search_passages_fts(conn, topic, limit=limit)

    # Filter to ones with quotes and good length
    passages = [p for p in passages if p.has_direct_quote and 30 <= p.word_count <= 150]

    # If not enough, supplement with general vivid passages
    if len(passages) < limit // 2:
        vivid = get_vivid_passages(conn, limit=limit - len(passages))
        seen = {p.passage_id for p in passages}
        for p in vivid:
            if p.passage_id not in seen:
                passages.append(p)

    return passages[:limit]
