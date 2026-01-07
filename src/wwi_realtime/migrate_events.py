"""Migrate events from original database to story engine schema.

Maps events to narrative arcs based on keywords, location, and date.
"""

import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()

# Keywords that map to specific arcs
ARC_KEYWORDS = {
    # Major battles/campaigns
    "verdun": "verdun",
    "somme": "somme",
    "passchendaele": "passchendaele",
    "ypres": "western_front",
    "marne": "first_marne",
    "tannenberg": "tannenberg",
    "gallipoli": "gallipoli",
    "dardanelles": "gallipoli",
    "anzac": "gallipoli",
    "jutland": "jutland",
    "isonzo": "isonzo_battles",
    "caporetto": "caporetto",
    "brusilov": "brusilov_offensive",
    "gorlice": "gorlice_tarnow",

    # Theaters by location
    "belgium": "western_front",
    "flanders": "western_front",
    "artois": "western_front",
    "champagne": "western_front",
    "picardy": "western_front",
    "lorraine": "western_front",
    "alsace": "western_front",
    "france": "western_front",
    "western front": "western_front",

    "eastern front": "eastern_front",
    "russia": "eastern_front",
    "poland": "eastern_front",
    "galicia": "eastern_front",
    "prussia": "eastern_front",
    "romanian": "eastern_front",

    "italy": "italian_front",
    "italian": "italian_front",
    "alps": "italian_front",
    "trentino": "italian_front",

    "mesopotamia": "mesopotamian_campaign",
    "baghdad": "mesopotamian_campaign",
    "basra": "mesopotamian_campaign",
    "kut": "mesopotamian_campaign",

    "palestine": "sinai_palestine",
    "sinai": "sinai_palestine",
    "suez": "sinai_palestine",
    "jerusalem": "sinai_palestine",
    "gaza": "sinai_palestine",

    "africa": "african_theatre",
    "cameroon": "african_theatre",
    "togoland": "african_theatre",
    "east africa": "african_theatre",
    "lettow": "african_theatre",

    # Naval
    "submarine": "uboat_campaign",
    "u-boat": "uboat_campaign",
    "naval": "naval_warfare",
    "fleet": "naval_warfare",
    "battleship": "naval_warfare",
    "dreadnought": "naval_warfare",
    "lusitania": "naval_warfare",
    "blockade": "naval_warfare",

    # German offensives 1918
    "spring offensive": "spring_offensive",
    "kaiserschlacht": "spring_offensive",
    "michael offensive": "spring_offensive",

    # Allied offensives 1918
    "hundred days": "hundred_days",
    "amiens": "hundred_days",
    "meuse-argonne": "hundred_days",
}

# Date-based arc assignments for events without keyword matches
DATE_ARCS = {
    # Pre-war (assassination period)
    (date(1914, 6, 28), date(1914, 7, 27)): "wwi_overall",
    # 1914 Western Front
    (date(1914, 8, 1), date(1914, 9, 14)): "western_1914",
    # First Marne
    (date(1914, 9, 5), date(1914, 9, 12)): "first_marne",
    # Tannenberg
    (date(1914, 8, 26), date(1914, 8, 30)): "tannenberg",
    # Verdun
    (date(1916, 2, 21), date(1916, 12, 18)): "verdun",
    # Somme
    (date(1916, 7, 1), date(1916, 11, 18)): "somme",
    # Brusilov
    (date(1916, 6, 4), date(1916, 9, 20)): "brusilov_offensive",
    # Passchendaele
    (date(1917, 7, 31), date(1917, 11, 10)): "passchendaele",
    # Caporetto
    (date(1917, 10, 24), date(1917, 11, 19)): "caporetto",
    # Spring Offensive
    (date(1918, 3, 21), date(1918, 7, 18)): "spring_offensive",
    # Hundred Days
    (date(1918, 8, 8), date(1918, 11, 11)): "hundred_days",
}


def classify_event(title: str, summary: str, event_date: date | None) -> str | None:
    """Classify an event into an arc based on title, summary, and date.

    Returns arc_id or None if no match found.
    """
    # Combine text for searching
    text = f"{title} {summary}".lower()

    # Check keywords first (more specific)
    for keyword, arc_id in ARC_KEYWORDS.items():
        if keyword in text:
            return arc_id

    # Check date-based arcs
    if event_date:
        for (start, end), arc_id in DATE_ARCS.items():
            if start <= event_date <= end:
                return arc_id

    # Default to overall WWI arc
    return "wwi_overall"


def parse_date(date_str: str | None) -> date | None:
    """Parse a date string to date object."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def migrate_events(
    source_db: Path,
    target_db: Path,
    dry_run: bool = False,
) -> dict:
    """Migrate events from source to target database.

    Args:
        source_db: Path to original events.db
        target_db: Path to story_engine.db
        dry_run: If True, don't actually modify target

    Returns:
        Migration statistics
    """
    source_conn = sqlite3.connect(source_db)
    target_conn = sqlite3.connect(target_db)

    stats = {
        "total": 0,
        "migrated": 0,
        "skipped": 0,
        "arc_assignments": {},
    }

    # Get all events from source
    cursor = source_conn.execute("""
        SELECT id, title, date, summary, significance, wikipedia_url,
               start_date, end_date, is_multi_day, location
        FROM events
        ORDER BY date
    """)

    events = cursor.fetchall()
    stats["total"] = len(events)

    # Check for existing events in target
    target_cursor = target_conn.execute("SELECT id FROM events")
    existing_ids = {row[0] for row in target_cursor.fetchall()}

    for event in events:
        event_id, title, date_str, summary, significance, wiki_url, \
            start_date, end_date, is_multi_day, location = event

        if event_id in existing_ids:
            stats["skipped"] += 1
            continue

        event_date = parse_date(date_str)
        arc_id = classify_event(title, summary or "", event_date)

        # Track arc assignments
        if arc_id:
            stats["arc_assignments"][arc_id] = stats["arc_assignments"].get(arc_id, 0) + 1

        if not dry_run:
            target_conn.execute("""
                INSERT INTO events (id, title, date, summary, significance,
                    wikipedia_url, start_date, end_date, is_multi_day, location, arc_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (event_id, title, date_str, summary, significance, wiki_url,
                  start_date, end_date, is_multi_day, location, arc_id))

        stats["migrated"] += 1

    if not dry_run:
        target_conn.commit()

    source_conn.close()
    target_conn.close()

    return stats


def show_arc_distribution(target_db: Path) -> None:
    """Show distribution of events across arcs."""
    conn = sqlite3.connect(target_db)

    cursor = conn.execute("""
        SELECT a.title, COUNT(e.id) as event_count
        FROM arcs a
        LEFT JOIN events e ON e.arc_id = a.id
        GROUP BY a.id
        ORDER BY event_count DESC
    """)

    table = Table(title="Events by Arc")
    table.add_column("Arc")
    table.add_column("Events", justify="right")

    for row in cursor.fetchall():
        table.add_row(row[0], str(row[1]))

    console.print(table)
    conn.close()


@click.command()
@click.option("--source", default="data/events.db", help="Source events database")
@click.option("--target", default="data/story_engine.db", help="Target story engine database")
@click.option("--dry-run", is_flag=True, help="Don't actually migrate, just show what would happen")
@click.option("--show-distribution", is_flag=True, help="Show event distribution by arc")
def main(source: str, target: str, dry_run: bool, show_distribution: bool):
    """Migrate events to story engine schema with arc assignments."""
    source_path = Path(source)
    target_path = Path(target)

    if not source_path.exists():
        console.print(f"[red]Source database not found: {source}[/red]")
        return

    if not target_path.exists():
        console.print(f"[red]Target database not found: {target}[/red]")
        return

    if show_distribution:
        show_arc_distribution(target_path)
        return

    console.print(f"\n[bold]Migrating events from {source} to {target}[/bold]")
    if dry_run:
        console.print("[yellow]DRY RUN - no changes will be made[/yellow]")

    stats = migrate_events(source_path, target_path, dry_run)

    console.print(f"\n  Total events: {stats['total']}")
    console.print(f"  [green]Migrated: {stats['migrated']}[/green]")
    console.print(f"  [yellow]Skipped (already exist): {stats['skipped']}[/yellow]")

    if stats["arc_assignments"]:
        console.print("\n  Arc assignments:")
        for arc_id, count in sorted(stats["arc_assignments"].items(),
                                     key=lambda x: x[1], reverse=True):
            console.print(f"    {arc_id}: {count}")

    if not dry_run:
        console.print("\n[bold green]Migration complete![/bold green]")
        show_arc_distribution(target_path)


if __name__ == "__main__":
    main()
