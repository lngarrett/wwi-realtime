"""Generate tweets for the entire WWI timeline."""

import json
import sqlite3
from datetime import date
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress

from wwi_realtime.generate_month import (
    get_events_for_month,
    get_ongoing_events,
    load_previous_summary,
    save_month_output,
)
from wwi_realtime.utils.claude import generate_month_tweets, validate_tweets

console = Console()

# WWI timeline
WWI_START_YEAR, WWI_START_MONTH = 1914, 6  # June 1914 (assassination)
WWI_END_YEAR, WWI_END_MONTH = 1918, 11      # November 1918 (armistice)


def get_all_months() -> list[tuple[int, int]]:
    """Get list of all months in WWI."""
    months = []
    year, month = WWI_START_YEAR, WWI_START_MONTH

    while (year, month) <= (WWI_END_YEAR, WWI_END_MONTH):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1

    return months


def month_already_generated(tweets_dir: Path, year: int, month: int) -> bool:
    """Check if a month has already been generated."""
    month_dir = tweets_dir / f"{year:04d}-{month:02d}"
    return month_dir.exists() and any(month_dir.glob("*.json"))


@click.command()
@click.option("--db", default="data/events.db", help="Path to events database")
@click.option("--output", default="tweets", help="Output directory for tweets")
@click.option("--summaries", default="data/month_summaries", help="Directory for month summaries")
@click.option("--model", default="claude-sonnet-4-20250514", help="Claude model to use")
@click.option("--start-month", default=None, help="Start from specific month (YYYY-MM)")
@click.option("--end-month", default=None, help="End at specific month (YYYY-MM)")
@click.option("--skip-existing", is_flag=True, help="Skip months already generated")
@click.option("--dry-run", is_flag=True, help="Don't actually generate, just show plan")
def main(
    db: str,
    output: str,
    summaries: str,
    model: str,
    start_month: str | None,
    end_month: str | None,
    skip_existing: bool,
    dry_run: bool,
):
    """Generate tweets for the entire war (June 1914 - November 1918)."""
    db_path = Path(db)
    tweets_dir = Path(output)
    summaries_dir = Path(summaries)

    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        return

    conn = sqlite3.connect(db_path)

    # Get all months
    all_months = get_all_months()

    # Filter by start/end if specified
    if start_month:
        start_y, start_m = map(int, start_month.split("-"))
        all_months = [(y, m) for y, m in all_months if (y, m) >= (start_y, start_m)]

    if end_month:
        end_y, end_m = map(int, end_month.split("-"))
        all_months = [(y, m) for y, m in all_months if (y, m) <= (end_y, end_m)]

    # Filter out existing if requested
    if skip_existing:
        all_months = [
            (y, m) for y, m in all_months
            if not month_already_generated(tweets_dir, y, m)
        ]

    console.print(f"\n[bold]WWI Tweet Generation[/bold]")
    console.print(f"  Database: {db_path}")
    console.print(f"  Output: {tweets_dir}")
    console.print(f"  Model: {model}")
    console.print(f"  Months to generate: {len(all_months)}")

    if dry_run:
        console.print("\n[yellow]Dry run - showing planned months:[/yellow]")
        for year, month in all_months:
            month_str = f"{year:04d}-{month:02d}"
            events = get_events_for_month(conn, year, month)
            total_events = sum(len(e) for e in events.values())
            console.print(f"  {month_str}: {total_events} events")
        return

    if not all_months:
        console.print("[yellow]No months to generate.[/yellow]")
        return

    # Generate each month
    total_tweets = 0
    total_warnings = 0

    with Progress() as progress:
        task = progress.add_task("[green]Generating tweets...", total=len(all_months))

        for year, month in all_months:
            month_str = f"{year:04d}-{month:02d}"
            progress.update(task, description=f"[cyan]{month_str}")

            try:
                # Get data for this month
                events_by_date = get_events_for_month(conn, year, month)
                ongoing_events = get_ongoing_events(conn, year, month)
                previous_summary = load_previous_summary(summaries_dir, year, month)

                total_events = sum(len(e) for e in events_by_date.values())

                if total_events == 0 and not ongoing_events:
                    console.print(f"  [yellow]{month_str}: No events, skipping[/yellow]")
                    progress.update(task, advance=1)
                    continue

                # Generate tweets
                output_data = generate_month_tweets(
                    month=month_str,
                    events_by_date=events_by_date,
                    ongoing_events=ongoing_events,
                    previous_month_summary=previous_summary,
                    model=model,
                )

                # Validate
                warnings = validate_tweets(output_data)
                total_warnings += len(warnings)

                # Save
                save_month_output(output_data, tweets_dir, summaries_dir)

                month_tweets = sum(len(d.tweets) for d in output_data.days.values())
                total_tweets += month_tweets
                console.print(f"  [green]{month_str}: {month_tweets} tweets generated[/green]")

            except Exception as e:
                console.print(f"  [red]{month_str}: Error - {e}[/red]")

            progress.update(task, advance=1)

    console.print(f"\n[bold green]Generation complete![/bold green]")
    console.print(f"  Total tweets: {total_tweets}")
    console.print(f"  Total warnings: {total_warnings}")
    console.print(f"  Output directory: {tweets_dir}")

    conn.close()


if __name__ == "__main__":
    main()
