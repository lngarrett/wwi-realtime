"""Compare old vs new generation pipeline output.

Generates sample prompts for a set of events to show the difference
between Wikipedia-summary tweets and the new narrative engine.
"""

import sqlite3
from datetime import date
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from wwi_realtime.generate.research import research_event, research_month
from wwi_realtime.generate.prompts import (
    build_event_prompt,
    build_month_prompt,
    EventContext,
)
from wwi_realtime.generate.threads import (
    TweetThread,
    create_thread_from_passages,
    format_thread_for_display,
)

console = Console()


def get_sample_events(conn: sqlite3.Connection, count: int = 5) -> list[dict]:
    """Get a diverse sample of events for comparison."""
    cursor = conn.execute("""
        SELECT e.id, e.title, e.date, e.summary, e.arc_id, a.title as arc_title
        FROM events e
        LEFT JOIN arcs a ON e.arc_id = a.id
        WHERE e.summary IS NOT NULL AND LENGTH(e.summary) > 50
        ORDER BY RANDOM()
        LIMIT ?
    """, (count,))

    return [
        {
            "id": row[0],
            "title": row[1],
            "date": row[2],
            "summary": row[3],
            "arc_id": row[4],
            "arc_title": row[5],
        }
        for row in cursor.fetchall()
    ]


def get_key_events(conn: sqlite3.Connection) -> list[dict]:
    """Get key historical events for comparison."""
    key_titles = [
        "Assassination of Archduke Franz Ferdinand",
        "Battle of Tannenberg",
        "First Battle of the Marne",
        "Battle of Verdun",
        "Battle of the Somme",
    ]

    events = []
    for title in key_titles:
        cursor = conn.execute("""
            SELECT e.id, e.title, e.date, e.summary, e.arc_id, a.title as arc_title
            FROM events e
            LEFT JOIN arcs a ON e.arc_id = a.id
            WHERE e.title LIKE ?
            LIMIT 1
        """, (f"%{title}%",))
        row = cursor.fetchone()
        if row:
            events.append({
                "id": row[0],
                "title": row[1],
                "date": row[2],
                "summary": row[3],
                "arc_id": row[4],
                "arc_title": row[5],
            })

    return events


def generate_old_style(event: dict) -> str:
    """Generate old-style Wikipedia summary tweet."""
    date_str = event["date"]
    title = event["title"]
    summary = event["summary"]

    # Truncate to fit tweet
    text = f"{date_str}: {title}. {summary}"
    if len(text) > 280:
        text = text[:277] + "..."

    return text


def generate_new_style(conn: sqlite3.Connection, event: dict) -> dict:
    """Generate new-style narrative prompt and sample thread."""
    context = research_event(conn, event)
    prompt = build_event_prompt(context)

    # Create sample thread
    thread = create_thread_from_passages(
        context.event,
        context.passages,
        thread_length=3,
    )

    return {
        "prompt": prompt,
        "thread": thread,
        "passages_found": len(context.passages),
        "quotes_found": sum(1 for p in context.passages if p.has_direct_quote),
        "perspectives": list(context.diverse_perspectives.keys()) if context.diverse_perspectives else [],
    }


def compare_event(conn: sqlite3.Connection, event: dict) -> None:
    """Show comparison for a single event."""
    console.print(f"\n[bold cyan]{'=' * 60}[/bold cyan]")
    console.print(f"[bold]{event['title']}[/bold]")
    console.print(f"Date: {event['date']}")
    console.print(f"Arc: {event['arc_title'] or 'None'}")
    console.print(f"[bold cyan]{'=' * 60}[/bold cyan]\n")

    # Old style
    old_tweet = generate_old_style(event)
    console.print(Panel(
        old_tweet,
        title="[red]OLD STYLE (Wikipedia Summary)[/red]",
        border_style="red",
    ))

    # New style
    new_data = generate_new_style(conn, event)

    console.print(f"\n[green]NEW STYLE - Found {new_data['passages_found']} passages, "
                  f"{new_data['quotes_found']} with quotes[/green]")
    if new_data['perspectives']:
        console.print(f"Perspectives: {', '.join(new_data['perspectives'])}")

    console.print(Panel(
        format_thread_for_display(new_data['thread']),
        title="[green]NEW STYLE (Sample Thread)[/green]",
        border_style="green",
    ))


def show_statistics(conn: sqlite3.Connection) -> None:
    """Show overall statistics about the new pipeline."""
    console.print("\n[bold]Pipeline Statistics[/bold]\n")

    # Events with arcs
    cursor = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN arc_id IS NOT NULL THEN 1 ELSE 0 END) as with_arc
        FROM events
    """)
    row = cursor.fetchone()
    console.print(f"Events: {row[0]} total, {row[1]} with arc assignments")

    # Passages
    cursor = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN has_direct_quote THEN 1 ELSE 0 END) as with_quote
        FROM source_passages
    """)
    row = cursor.fetchone()
    console.print(f"Passages: {row[0]} total, {row[1]} with direct quotes")

    # Sources
    cursor = conn.execute("SELECT COUNT(*) FROM canonical_sources WHERE ingested = 1")
    console.print(f"Sources ingested: {cursor.fetchone()[0]}")

    # Perspectives
    cursor = conn.execute("""
        SELECT perspective, COUNT(*) as count
        FROM canonical_sources
        WHERE ingested = 1 AND perspective IS NOT NULL
        GROUP BY perspective
        ORDER BY count DESC
    """)
    console.print("\nPerspectives available:")
    for row in cursor.fetchall():
        console.print(f"  {row[0]}: {row[1]} sources")


@click.command()
@click.option("--db", default="data/story_engine.db", help="Database path")
@click.option("--count", default=3, help="Number of random events to compare")
@click.option("--key-events", is_flag=True, help="Compare key historical events")
@click.option("--stats", is_flag=True, help="Show pipeline statistics")
def main(db: str, count: int, key_events: bool, stats: bool):
    """Compare old vs new generation pipeline output."""
    db_path = Path(db)
    if not db_path.exists():
        console.print(f"[red]Database not found: {db}[/red]")
        return

    conn = sqlite3.connect(db_path)

    if stats:
        show_statistics(conn)
        return

    console.print("[bold]WWI Story Engine - Quality Comparison[/bold]")
    console.print("Comparing old Wikipedia-summary style with new narrative engine\n")

    if key_events:
        events = get_key_events(conn)
        console.print(f"Comparing {len(events)} key historical events")
    else:
        events = get_sample_events(conn, count)
        console.print(f"Comparing {len(events)} random events")

    for event in events:
        compare_event(conn, event)

    show_statistics(conn)
    conn.close()


if __name__ == "__main__":
    main()
