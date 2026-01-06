"""Generate tweets for a single month using Claude API."""

import json
import sqlite3
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from wwi_realtime.utils.claude import (
    MonthOutput,
    generate_month_tweets,
    validate_tweets,
)
from wwi_realtime.enrich_events import get_articles_for_event

console = Console()


def get_events_for_month(conn: sqlite3.Connection, year: int, month: int) -> dict[str, list[dict]]:
    """Get all events for a given month, grouped by date."""
    # Get first and last day of month
    _, last_day = monthrange(year, month)
    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

    cursor = conn.execute(
        """
        SELECT id, date, title, summary, location, significance, wikipedia_url,
               start_date, end_date, is_multi_day
        FROM events
        WHERE date >= ? AND date <= ?
        ORDER BY date, significance DESC
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
            "location": row[4],
            "significance": row[5],
            "wikipedia_url": row[6],
            "start_date": row[7],
            "end_date": row[8],
            "is_multi_day": row[9],
        }
        if event["date"] not in events_by_date:
            events_by_date[event["date"]] = []
        events_by_date[event["date"]].append(event)

    return events_by_date


def get_ongoing_events(conn: sqlite3.Connection, year: int, month: int) -> list[dict]:
    """Get multi-day events that span into or through this month."""
    _, last_day = monthrange(year, month)
    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

    cursor = conn.execute(
        """
        SELECT id, title, start_date, end_date, summary, location
        FROM events
        WHERE is_multi_day = 1
          AND start_date <= ?
          AND (end_date >= ? OR end_date IS NULL)
        ORDER BY start_date
        """,
        (end_date, start_date),
    )

    return [
        {
            "id": row[0],
            "title": row[1],
            "start_date": row[2],
            "end_date": row[3],
            "summary": row[4],
            "location": row[5],
        }
        for row in cursor.fetchall()
    ]


def load_previous_summary(summaries_dir: Path, year: int, month: int) -> str:
    """Load summary from previous month."""
    # Calculate previous month
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    summary_file = summaries_dir / f"{prev_year:04d}-{prev_month:02d}.json"
    if summary_file.exists():
        data = json.loads(summary_file.read_text())
        return data.get("month_summary", "No summary available.")

    return "None - this is the first month or previous month not yet generated."


def get_articles_for_month(
    conn: sqlite3.Connection,
    events_by_date: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Load all articles for events in a month.

    Args:
        conn: Database connection
        events_by_date: Events grouped by date (from get_events_for_month)

    Returns:
        Dict mapping event_id to list of article dicts
    """
    articles_by_event: dict[str, list[dict]] = {}

    # Check if articles table exists
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='articles'"
    )
    if not cursor.fetchone():
        return articles_by_event

    for date_str, events in events_by_date.items():
        for event in events:
            event_id = event.get("id")
            if event_id:
                articles = get_articles_for_event(conn, event_id)
                if articles:
                    articles_by_event[event_id] = articles

    return articles_by_event


def save_month_output(
    output: MonthOutput,
    tweets_dir: Path,
    summaries_dir: Path,
) -> None:
    """Save generated tweets and summary to disk."""
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

    for date_str, day_data in output.days.items():
        day_file = month_dir / f"{date_str.split('-')[2]}.json"
        day_output = {
            "date": date_str,
            "tweets": [
                {
                    "text": t.text,
                    "facts_used": t.facts_used,
                    "event_id": t.event_id,
                }
                for t in day_data.tweets
            ],
            "summary": day_data.summary,
        }
        day_file.write_text(json.dumps(day_output, indent=2))

    return output


@click.command()
@click.option("--month", required=True, help="Month to generate (YYYY-MM)")
@click.option("--db", default="data/events.db", help="Path to events database")
@click.option("--output", default="tweets", help="Output directory for tweets")
@click.option("--summaries", default="data/month_summaries", help="Directory for month summaries")
@click.option("--model", default="claude-sonnet-4-20250514", help="Claude model to use")
@click.option("--dry-run", is_flag=True, help="Don't actually call Claude, just show what would be sent")
def main(month: str, db: str, output: str, summaries: str, model: str, dry_run: bool):
    """Generate tweets for a single month."""
    # Parse month
    try:
        year, month_num = map(int, month.split("-"))
    except ValueError:
        console.print("[red]Invalid month format. Use YYYY-MM[/red]")
        return

    # Connect to database
    db_path = Path(db)
    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        return

    conn = sqlite3.connect(db_path)

    # Get events
    events_by_date = get_events_for_month(conn, year, month_num)
    ongoing_events = get_ongoing_events(conn, year, month_num)
    previous_summary = load_previous_summary(Path(summaries), year, month_num)

    # Get primary sources for events
    articles_by_event = get_articles_for_month(conn, events_by_date)
    total_articles = sum(len(a) for a in articles_by_event.values())

    # Show what we found
    total_events = sum(len(e) for e in events_by_date.values())
    console.print(f"\n[bold]Month: {month}[/bold]")
    console.print(f"  Events found: {total_events}")
    console.print(f"  Days with events: {len(events_by_date)}")
    console.print(f"  Ongoing multi-day events: {len(ongoing_events)}")
    console.print(f"  Events with primary sources: {len(articles_by_event)}")
    console.print(f"  Total newspaper articles: {total_articles}")

    if ongoing_events:
        console.print("\n[bold]Ongoing events:[/bold]")
        for e in ongoing_events:
            console.print(f"  - {e['title']} ({e['start_date']} to {e['end_date']})")

    if dry_run:
        console.print("\n[yellow]Dry run - not calling Claude[/yellow]")
        console.print("\n[bold]Events by date:[/bold]")
        for date_str, events in sorted(events_by_date.items()):
            console.print(f"\n  {date_str}:")
            for e in events:
                console.print(f"    - [{e['significance']}] {e['title']}")
        return

    # Generate tweets
    console.print("\n[bold blue]Calling Claude API...[/bold blue]")
    output_data = generate_month_tweets(
        month=month,
        events_by_date=events_by_date,
        ongoing_events=ongoing_events,
        previous_month_summary=previous_summary,
        articles_by_event=articles_by_event,
        model=model,
    )

    # Validate
    warnings = validate_tweets(output_data)
    if warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in warnings:
            console.print(f"  - {w}")

    # Save output
    save_month_output(output_data, Path(output), Path(summaries))

    # Show summary
    total_tweets = sum(len(d.tweets) for d in output_data.days.values())
    console.print(f"\n[green]Generated {total_tweets} tweets for {month}[/green]")

    # Show sample
    table = Table(title="Sample Tweets")
    table.add_column("Date")
    table.add_column("Tweet")

    shown = 0
    for date_str, day in sorted(output_data.days.items()):
        for tweet in day.tweets[:1]:  # Show max 1 tweet per day
            table.add_row(date_str, tweet.text[:100] + "..." if len(tweet.text) > 100 else tweet.text)
            shown += 1
            if shown >= 5:
                break
        if shown >= 5:
            break

    console.print(table)

    conn.close()


if __name__ == "__main__":
    main()
