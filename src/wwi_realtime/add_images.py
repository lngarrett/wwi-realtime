"""Add Wikipedia images to events in the database."""

import sqlite3
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress

from wwi_realtime.utils.wikipedia import get_page_image

console = Console()


def init_image_columns(conn: sqlite3.Connection) -> None:
    """Add image columns to events table if they don't exist."""
    try:
        conn.execute("ALTER TABLE events ADD COLUMN image_url TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        conn.execute("ALTER TABLE events ADD COLUMN image_caption TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()


@click.command()
@click.option("--db", default="data/events.db", help="Path to events database")
@click.option("--limit", type=int, help="Maximum events to process")
@click.option("--force", is_flag=True, help="Re-fetch images even if already present")
def main(db: str, limit: int | None, force: bool):
    """Add Wikipedia images to events."""
    db_path = Path(db)

    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        return

    conn = sqlite3.connect(db_path)
    init_image_columns(conn)

    # Get events needing images
    if force:
        query = "SELECT id, title FROM events"
    else:
        query = "SELECT id, title FROM events WHERE image_url IS NULL"

    if limit:
        query += f" LIMIT {limit}"

    cursor = conn.execute(query)
    events = cursor.fetchall()

    if not events:
        console.print("[yellow]No events need images[/yellow]")
        return

    console.print(f"[green]Processing {len(events)} events[/green]")

    found = 0
    with Progress() as progress:
        task = progress.add_task("[green]Fetching images...", total=len(events))

        for event_id, title in events:
            progress.update(task, description=f"[cyan]{title[:40]}...")

            image_url, caption = get_page_image(title)

            if image_url:
                conn.execute(
                    "UPDATE events SET image_url = ?, image_caption = ? WHERE id = ?",
                    (image_url, caption, event_id),
                )
                found += 1

            progress.update(task, advance=1)

        conn.commit()

    console.print(f"\n[green]Found images for {found}/{len(events)} events[/green]")
    conn.close()


if __name__ == "__main__":
    main()
