"""Build the WWI event index from Wikipedia."""

import hashlib
import json
import sqlite3
import time
from datetime import date
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, TaskID

from wwi_realtime.utils.wikipedia import (
    WWI_END,
    WWI_START,
    WikipediaEvent,
    fetch_wwi_event,
    get_category_members,
    get_wwi_categories,
)

console = Console()

DATABASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    location TEXT,
    significance TEXT DEFAULT 'medium',
    wikipedia_url TEXT,
    wikidata_id TEXT,
    categories TEXT,
    sources TEXT,
    start_date DATE,
    end_date DATE,
    is_multi_day BOOLEAN DEFAULT FALSE,
    raw_extract TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_start_date ON events(start_date);
CREATE INDEX IF NOT EXISTS idx_events_end_date ON events(end_date);
CREATE INDEX IF NOT EXISTS idx_events_is_multi_day ON events(is_multi_day);
"""


def generate_event_id(title: str, date_str: str) -> str:
    """Generate a unique event ID from title and date."""
    key = f"{title}:{date_str}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def estimate_significance(event: WikipediaEvent) -> str:
    """Estimate event significance based on various signals."""
    # High significance indicators
    high_keywords = [
        "battle of", "armistice", "treaty of", "declaration of war",
        "assassination", "offensive", "surrender", "revolution",
        "sinking of", "massacre", "genocide",
    ]

    title_lower = event.title.lower()

    for keyword in high_keywords:
        if keyword in title_lower:
            return "high"

    # Check extract length and citation count as proxy for importance
    if len(event.raw_extract) > 3000 and len(event.citations) > 10:
        return "high"

    if len(event.raw_extract) > 1500 and len(event.citations) > 5:
        return "medium"

    return "low"


def init_database(db_path: Path) -> sqlite3.Connection:
    """Initialize the SQLite database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(DATABASE_SCHEMA)
    conn.commit()
    return conn


def insert_event(conn: sqlite3.Connection, event: WikipediaEvent) -> int:
    """Insert an event into the database. Returns number of rows inserted."""
    if not event.dates and not event.start_date:
        return 0

    # Determine the primary date
    primary_date = event.start_date or (event.dates[0] if event.dates else None)
    if not primary_date:
        return 0

    # Check if within WWI range
    if not (WWI_START <= primary_date <= WWI_END):
        return 0

    event_id = generate_event_id(event.title, str(primary_date))
    is_multi_day = event.end_date is not None and event.end_date != event.start_date

    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO events
            (id, date, title, summary, location, significance, wikipedia_url,
             wikidata_id, categories, sources, start_date, end_date, is_multi_day, raw_extract)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                str(primary_date),
                event.title,
                event.summary,
                event.location,
                estimate_significance(event),
                event.wikipedia_url,
                event.wikidata_id,
                json.dumps(event.categories),
                json.dumps(event.citations),
                str(event.start_date) if event.start_date else None,
                str(event.end_date) if event.end_date else None,
                is_multi_day,
                event.raw_extract,
            ),
        )
        return 1
    except sqlite3.IntegrityError:
        return 0


def scrape_category(
    category: str,
    conn: sqlite3.Connection,
    progress: Progress,
    task: TaskID,
    delay: float = 0.5,
) -> int:
    """Scrape all events from a Wikipedia category."""
    inserted = 0
    seen_titles = set()

    for member in get_category_members(category):
        title = member.get("title", "")

        # Skip if already processed
        if title in seen_titles:
            continue
        seen_titles.add(title)

        # Skip category pages and disambiguation pages
        if title.startswith("Category:") or "(disambiguation)" in title:
            continue

        progress.update(task, description=f"[cyan]{title[:50]}...")

        try:
            event = fetch_wwi_event(title)
            if event:
                inserted += insert_event(conn, event)
                conn.commit()
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to fetch {title}: {e}[/yellow]")

        # Rate limiting
        time.sleep(delay)

    return inserted


@click.command()
@click.option(
    "--db",
    default="data/events.db",
    help="Path to SQLite database",
)
@click.option(
    "--delay",
    default=0.5,
    help="Delay between API requests (seconds)",
)
@click.option(
    "--categories",
    multiple=True,
    help="Specific categories to scrape (default: all WWI categories)",
)
def main(db: str, delay: float, categories: tuple[str]):
    """Build the WWI event index from Wikipedia."""
    db_path = Path(db)
    conn = init_database(db_path)

    console.print(f"[green]Database initialized at {db_path}[/green]")

    cats_to_scrape = list(categories) if categories else get_wwi_categories()
    total_inserted = 0

    with Progress() as progress:
        main_task = progress.add_task("[green]Scraping Wikipedia...", total=len(cats_to_scrape))

        for category in cats_to_scrape:
            console.print(f"\n[bold blue]Scraping: {category}[/bold blue]")

            cat_task = progress.add_task(f"[cyan]{category}", total=None)
            inserted = scrape_category(category, conn, progress, cat_task, delay)
            progress.remove_task(cat_task)

            console.print(f"  [green]Inserted {inserted} events[/green]")
            total_inserted += inserted

            progress.update(main_task, advance=1)

    # Print summary
    cursor = conn.execute("SELECT COUNT(*) FROM events")
    total_events = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM events WHERE is_multi_day = 1")
    multi_day_events = cursor.fetchone()[0]

    cursor = conn.execute(
        "SELECT date, COUNT(*) as count FROM events GROUP BY date ORDER BY count DESC LIMIT 10"
    )
    busiest_days = cursor.fetchall()

    console.print("\n[bold green]Summary:[/bold green]")
    console.print(f"  Total events: {total_events}")
    console.print(f"  Multi-day events: {multi_day_events}")
    console.print(f"  Newly inserted: {total_inserted}")
    console.print("\n[bold]Busiest days:[/bold]")
    for day, count in busiest_days:
        console.print(f"  {day}: {count} events")

    conn.close()


if __name__ == "__main__":
    main()
