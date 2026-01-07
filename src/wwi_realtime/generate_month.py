"""Generate tweets for a single month using the story engine."""

import json
import sqlite3
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from wwi_realtime.generate.research import research_month, research_month_vivid, research_month_hybrid
from wwi_realtime.utils.claude import (
    MonthOutput,
    generate_month_tweets,
    generate_month_vivid,
    generate_month_hybrid,
    validate_tweets,
    validate_event_coverage,
    output_to_dict,
)

console = Console()


def get_events_for_month(conn: sqlite3.Connection, year: int, month: int) -> dict[str, list[dict]]:
    """Get all events for a given month from story_engine.db, grouped by date."""
    _, last_day = monthrange(year, month)
    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

    cursor = conn.execute(
        """
        SELECT e.id, e.date, e.title, e.summary, e.arc_id, a.title as arc_title
        FROM events e
        LEFT JOIN arcs a ON e.arc_id = a.id
        WHERE e.date >= ? AND e.date <= ?
        ORDER BY e.date
        """,
        (start_date, end_date),
    )

    events_by_date: dict[str, list[dict]] = {}
    for row in cursor.fetchall():
        event = {
            "id": row[0],
            "date": row[1],
            "title": row[2],
            "summary": row[3],
            "arc_id": row[4],
            "arc_title": row[5],
        }
        if event["date"] not in events_by_date:
            events_by_date[event["date"]] = []
        events_by_date[event["date"]].append(event)

    return events_by_date


def load_previous_summary(summaries_dir: Path, year: int, month: int) -> str:
    """Load summary from previous month."""
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    summary_file = summaries_dir / f"{prev_year:04d}-{prev_month:02d}.json"
    if summary_file.exists():
        data = json.loads(summary_file.read_text())
        return data.get("month_summary", "No summary available.")

    return "This is the beginning of the war coverage."


def save_month_output(
    output: MonthOutput,
    tweets_dir: Path,
    summaries_dir: Path,
) -> None:
    """Save generated tweets and summary to disk."""
    # Convert to dict for serialization
    output_dict = output_to_dict(output)

    # Save month summary
    summaries_dir.mkdir(parents=True, exist_ok=True)
    summary_file = summaries_dir / f"{output.month}.json"
    summary_file.write_text(json.dumps({
        "month": output.month,
        "month_summary": output.month_summary,
    }, indent=2))

    # Save individual day files
    month_dir = tweets_dir / output.month
    month_dir.mkdir(parents=True, exist_ok=True)

    for date_str, day_data in output_dict["days"].items():
        day_num = date_str.split("-")[2]
        day_file = month_dir / f"{day_num}.json"
        day_file.write_text(json.dumps(day_data, indent=2))


@click.command()
@click.option("--month", required=True, help="Month to generate (YYYY-MM)")
@click.option("--db", default="data/story_engine.db", help="Path to story engine database")
@click.option("--output", default="tweets", help="Output directory for tweets")
@click.option("--summaries", default="data/month_summaries", help="Directory for month summaries")
@click.option("--model", default="claude-sonnet-4-20250514", help="Claude model to use")
@click.option("--dry-run", is_flag=True, help="Don't call Claude, just show research")
@click.option("--mode", type=click.Choice(["hybrid", "vivid", "legacy"]), default="hybrid",
              help="Generation mode: hybrid (events+voices), vivid (passages-first), legacy (events-first)")
def main(month: str, db: str, output: str, summaries: str, model: str, dry_run: bool, mode: str):
    """Generate tweets for a single month using the story engine."""
    # Parse month
    try:
        year, month_num = map(int, month.split("-"))
    except ValueError:
        console.print("[red]Invalid month format. Use YYYY-MM[/red]")
        return

    # Connect to story engine database
    db_path = Path(db)
    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        console.print("[yellow]Run 'python -m wwi_realtime.init_story_engine' first[/yellow]")
        return

    conn = sqlite3.connect(db_path)

    # Get events for the month
    events_by_date = get_events_for_month(conn, year, month_num)
    total_events = sum(len(e) for e in events_by_date.values())

    if mode == "hybrid":
        # HYBRID approach: events + matched passages by arc
        console.print(f"\n[bold]Researching {month} (hybrid: events + voices)...[/bold]")
        research = research_month_hybrid(conn, year, month_num, events_by_date, max_passages_per_arc=15)

        console.print(f"\n[bold]Month: {month}[/bold]")
        console.print(f"  Events found: {total_events}")
        console.print(f"  Arcs active: {len(research['events_by_arc'])}")
        total_passages = sum(len(p) for p in research['passages_by_arc'].values())
        console.print(f"  Matched passages: {total_passages}")

        if dry_run:
            console.print("\n[yellow]Dry run - showing hybrid research[/yellow]")

            console.print("\n[bold]Events by Arc:[/bold]")
            for arc_id, events in research['events_by_arc'].items():
                arc_name = arc_id.replace("_", " ").title()
                console.print(f"\n  {arc_name} ({len(events)} events):")
                for e in events[:3]:
                    console.print(f"    - {e['date']}: {e['title']}")

            # Show event-matched passages
            passages_by_event = research.get('passages_by_event', {})
            if passages_by_event:
                console.print(f"\n[bold]Event-Matched Passages ({len(passages_by_event)} events with matches):[/bold]")
                for event_title, passages in list(passages_by_event.items())[:5]:
                    console.print(f"\n  {event_title}:")
                    for p in passages[:2]:
                        console.print(f"    {p.source_author}: \"{p.content[:100]}...\"")

            console.print("\n[bold]Additional Arc Passages:[/bold]")
            for arc_id, passages in research['passages_by_arc'].items():
                arc_name = arc_id.replace("_", " ").title()
                console.print(f"\n  {arc_name} ({len(passages)} passages):")
                for p in passages[:2]:
                    console.print(f"    {p.source_author}: \"{p.content[:100]}...\"")
            return

        # Generate tweets with hybrid approach
        console.print("\n[bold blue]Calling Claude API (hybrid mode)...[/bold blue]")
        output_data = generate_month_hybrid(
            month=month,
            events_by_arc=research['events_by_arc'],
            passages_by_arc=research['passages_by_arc'],
            passages_by_event=research.get('passages_by_event', {}),
            arc_summaries=research['arc_summaries'],
            model=model,
        )

    elif mode == "vivid":
        # VIVID approach: passages first, events for context
        console.print(f"\n[bold]Researching {month} (vivid passage-first)...[/bold]")
        research = research_month_vivid(conn, year, month_num, events_by_date, max_vivid_passages=40)

        console.print(f"\n[bold]Month: {month}[/bold]")
        console.print(f"  Events found: {total_events}")
        console.print(f"  Days with events: {len(events_by_date)}")
        console.print(f"  Vivid passages: {len(research['vivid_passages'])}")

        if dry_run:
            console.print("\n[yellow]Dry run - showing sample vivid passages[/yellow]")
            console.print("\n[bold]Sample vivid passages:[/bold]")
            for p in research['vivid_passages'][:5]:
                console.print(f"\n  {p.source_author}:")
                console.print(f"    \"{p.content[:150]}...\"")

            console.print("\n[bold]Sample events for context:[/bold]")
            for date_str, events in list(sorted(events_by_date.items()))[:5]:
                console.print(f"\n  {date_str}:")
                for e in events[:2]:
                    console.print(f"    - {e['title']}")
            return

        # Generate tweets with vivid approach
        console.print("\n[bold blue]Calling Claude API (vivid mode)...[/bold blue]")
        output_data = generate_month_vivid(
            month=month,
            events_by_date=events_by_date,
            vivid_passages=research['vivid_passages'],
            model=model,
        )

    else:  # legacy mode
        # LEGACY approach: events first, passages as decoration
        console.print(f"\n[bold]Researching {month} (legacy event-first)...[/bold]")
        research = research_month(conn, year, month_num, events_by_date, max_passages_per_event=3)

        # Load previous month summary
        previous_summary = load_previous_summary(Path(summaries), year, month_num)

        console.print(f"\n[bold]Month: {month}[/bold]")
        console.print(f"  Events found: {total_events}")
        console.print(f"  Days with events: {len(events_by_date)}")
        console.print(f"  Events with passages: {len(research['passages_by_event'])}")
        console.print(f"  Active arcs: {len(research['arc_narratives'])}")

        total_passages = sum(len(p) for p in research['passages_by_event'].values())
        console.print(f"  Total passages: {total_passages}")

        if research['arc_narratives']:
            console.print("\n[bold]Active arcs:[/bold]")
            for arc_id in list(research['arc_narratives'].keys())[:5]:
                console.print(f"  - {arc_id.replace('_', ' ').title()}")

        if dry_run:
            console.print("\n[yellow]Dry run - showing sample research[/yellow]")
            console.print("\n[bold]Sample events by date:[/bold]")
            for date_str, events in list(sorted(events_by_date.items()))[:5]:
                console.print(f"\n  {date_str}:")
                for e in events[:2]:
                    console.print(f"    - {e['title']}")
                    if e.get('arc_title'):
                        console.print(f"      Arc: {e['arc_title']}")

            console.print("\n[bold]Sample passages:[/bold]")
            for event_title, passages in list(research['passages_by_event'].items())[:3]:
                console.print(f"\n  For: {event_title}")
                for p in passages[:1]:
                    console.print(f"    \"{p.content[:100]}...\"")
                    console.print(f"    - {p.source_author}, {p.source_title}")

            return

        # Generate tweets with legacy approach
        console.print("\n[bold blue]Calling Claude API (legacy mode)...[/bold blue]")
        output_data = generate_month_tweets(
            month=month,
            events_by_date=events_by_date,
            passages_by_event=research['passages_by_event'],
            arc_narratives=research['arc_narratives'],
            previous_month_summary=previous_summary,
            model=model,
        )

    # Validate tweets
    warnings = validate_tweets(output_data)
    if warnings:
        console.print("\n[yellow]Tweet Warnings:[/yellow]")
        for w in warnings[:10]:
            console.print(f"  - {w}")

    # Validate event coverage
    coverage = validate_event_coverage(output_data, events_by_date)
    console.print(f"\n[bold]Event Coverage:[/bold] {coverage['covered_events']}/{coverage['total_events']} ({coverage['coverage_pct']:.0f}%)")
    if coverage['uncovered'] and len(coverage['uncovered']) <= 10:
        console.print("[yellow]Uncovered events:[/yellow]")
        for e in coverage['uncovered'][:10]:
            console.print(f"  - {e['date']}: {e['title']}")

    # Save output
    save_month_output(output_data, Path(output), Path(summaries))

    # Show summary
    total_tweets = sum(len(d.tweets) for d in output_data.days.values())
    total_threads = sum(len(d.threads) for d in output_data.days.values())
    thread_tweets = sum(
        len(t.tweets)
        for d in output_data.days.values()
        for t in d.threads
    )

    console.print(f"\n[green]Generated content for {month}:[/green]")
    console.print(f"  Single tweets: {total_tweets}")
    console.print(f"  Threads: {total_threads} ({thread_tweets} tweets)")
    console.print(f"  Output: {Path(output) / month}")

    # Show sample
    table = Table(title="Sample Content")
    table.add_column("Date")
    table.add_column("Type")
    table.add_column("Content")

    shown = 0
    for date_str, day in sorted(output_data.days.items()):
        # Show single tweets
        for tweet in day.tweets[:1]:
            text = tweet.text[:80] + "..." if len(tweet.text) > 80 else tweet.text
            table.add_row(date_str, "tweet", text)
            shown += 1

        # Show threads
        for thread in day.threads[:1]:
            text = f"[{len(thread.tweets)} tweets] {thread.event_title}"
            table.add_row(date_str, "thread", text)
            shown += 1

        if shown >= 8:
            break

    console.print(table)
    conn.close()


if __name__ == "__main__":
    main()
