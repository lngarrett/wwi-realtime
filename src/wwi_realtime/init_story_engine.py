"""Initialize the story engine database.

Sets up schema, populates arcs, loads sources, and optionally ingests content.
"""

import sqlite3
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from wwi_realtime.framework.schema import create_schema, verify_schema
from wwi_realtime.framework.arcs import build_arc_hierarchy, populate_arcs_table, get_all_arcs
from wwi_realtime.sources.curator import (
    load_canonical_sources,
    populate_sources_table,
    populate_arc_coverage,
    get_coverage_stats,
)
from wwi_realtime.sources.ingest import (
    ingest_available_sources,
    get_ingestion_stats,
)

console = Console()


def init_database(db_path: Path) -> sqlite3.Connection:
    """Initialize database with story engine schema."""
    console.print(f"\n[bold]Initializing database: {db_path}[/bold]")

    # Check if events table exists (from original scraper)
    conn = sqlite3.connect(db_path)

    # Check for existing events table
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
    )
    has_events = cursor.fetchone() is not None

    if not has_events:
        console.print("  Creating events table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date DATE,
                summary TEXT,
                significance TEXT,
                wikipedia_url TEXT,
                start_date DATE,
                end_date DATE,
                is_multi_day BOOLEAN DEFAULT 0,
                location TEXT,
                arc_id TEXT
            )
        """)

    # Create story engine schema
    console.print("  Creating story engine schema...")
    create_schema(conn)

    # Verify
    status = verify_schema(conn)
    if status["all_exist"]:
        console.print("  [green]✓ Schema created successfully[/green]")
    else:
        console.print("  [red]✗ Schema creation failed[/red]")

    return conn


def populate_arcs(conn: sqlite3.Connection, fetch_wikipedia: bool = False) -> int:
    """Populate arcs table."""
    console.print("\n[bold]Populating arcs...[/bold]")

    if fetch_wikipedia:
        console.print("  Fetching from Wikipedia (this may take a minute)...")
        arcs = build_arc_hierarchy()
    else:
        # Use predefined arcs without fetching summaries
        from wwi_realtime.framework.arcs import WWI_THEATERS, WWI_CAMPAIGNS, Arc

        arcs = []
        for arc_id, info in WWI_THEATERS.items():
            arcs.append(Arc(
                id=arc_id,
                title=info["title"],
                wikipedia_url=info["wikipedia_url"],
                theater=info.get("theater"),
            ))

        # Add campaigns as children
        for arc_id, info in WWI_CAMPAIGNS.items():
            parent_id = info.get("parent")
            arc = Arc(
                id=arc_id,
                title=info["title"],
                parent_arc_id=parent_id,
                wikipedia_url=info.get("wikipedia_url"),
                theater=info.get("theater"),
            )
            arcs.append(arc)

    count = populate_arcs_table(conn, arcs)
    console.print(f"  [green]✓ Populated {count} arcs[/green]")

    return count


def populate_sources(conn: sqlite3.Connection) -> int:
    """Populate canonical sources from JSON."""
    console.print("\n[bold]Loading canonical sources...[/bold]")

    sources = load_canonical_sources()
    count = populate_sources_table(conn, sources)
    console.print(f"  [green]✓ Loaded {count} sources[/green]")

    # Populate arc coverage
    console.print("  Populating coverage mappings...")
    coverage_count = populate_arc_coverage(conn, sources)
    console.print(f"  [green]✓ Created {coverage_count} coverage mappings[/green]")

    return count


def show_status(conn: sqlite3.Connection) -> None:
    """Show current database status."""
    console.print("\n[bold]Database Status:[/bold]")

    # Schema status
    status = verify_schema(conn)
    console.print(f"  Schema version: {status['version']}")

    # Table counts
    table = Table(title="Table Counts")
    table.add_column("Table")
    table.add_column("Count", justify="right")

    for tbl, count in status["tables"].items():
        table.add_row(tbl, str(count) if count >= 0 else "[red]missing[/red]")

    console.print(table)

    # Coverage stats
    if status["tables"].get("source_coverage", 0) > 0:
        cov_stats = get_coverage_stats(conn)
        console.print(f"\n  Sources with arc coverage: {cov_stats['sources_with_arc']}")
        console.print(f"  Sources with topics: {cov_stats['sources_with_topic']}")

    # Ingestion stats
    if status["tables"].get("source_passages", 0) > 0:
        ing_stats = get_ingestion_stats(conn)
        console.print(f"\n  Sources ingested: {ing_stats['ingested']}/{ing_stats['available']}")
        console.print(f"  Total passages: {ing_stats['passages']}")
        console.print(f"  Passages with quotes: {ing_stats['passages_with_quotes']}")
        console.print(f"  Total words: {ing_stats['total_words']:,}")


@click.command()
@click.option("--db", default="data/events.db", help="Path to database")
@click.option("--fetch-wikipedia", is_flag=True, help="Fetch arc summaries from Wikipedia")
@click.option("--ingest", is_flag=True, help="Ingest sources from Gutenberg")
@click.option("--ingest-limit", default=None, type=int, help="Limit sources to ingest")
@click.option("--priority", default=2, help="Max priority level for ingestion (1=highest)")
@click.option("--status-only", is_flag=True, help="Only show status, don't modify")
def main(db: str, fetch_wikipedia: bool, ingest: bool, ingest_limit: int, priority: int, status_only: bool):
    """Initialize the WWI Story Engine database."""
    db_path = Path(db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if status_only:
        conn = sqlite3.connect(db_path)
        show_status(conn)
        conn.close()
        return

    # Initialize
    conn = init_database(db_path)

    # Check if arcs already populated
    cursor = conn.execute("SELECT COUNT(*) FROM arcs")
    arc_count = cursor.fetchone()[0]

    if arc_count == 0:
        populate_arcs(conn, fetch_wikipedia=fetch_wikipedia)
    else:
        console.print(f"\n[yellow]Arcs already populated ({arc_count} arcs)[/yellow]")

    # Check if sources already populated
    cursor = conn.execute("SELECT COUNT(*) FROM canonical_sources")
    source_count = cursor.fetchone()[0]

    if source_count == 0:
        populate_sources(conn)
    else:
        console.print(f"\n[yellow]Sources already populated ({source_count} sources)[/yellow]")

    # Ingest if requested
    if ingest:
        console.print(f"\n[bold]Ingesting sources (priority <= {priority})...[/bold]")
        results = ingest_available_sources(
            conn,
            priority_max=priority,
            limit=ingest_limit,
            delay=1.0,
            save_raw=True,
        )
        console.print(f"\n  [green]✓ Ingested: {results['ingested']}[/green]")
        if results['skipped']:
            console.print(f"  [yellow]Skipped: {results['skipped']}[/yellow]")
        if results['failed']:
            console.print(f"  [red]Failed: {results['failed']}[/red]")

    # Show final status
    show_status(conn)

    conn.close()
    console.print("\n[bold green]Done![/bold green]")


if __name__ == "__main__":
    main()
