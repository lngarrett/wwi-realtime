"""CLI entry point for WWI Real-Time."""

import click


@click.group()
def main():
    """WWI Real-Time Tweet Generation System."""
    pass


@main.command("build-index")
@click.pass_context
def build_index(ctx):
    """Build the event index from Wikipedia."""
    from wwi_realtime.build_event_index import main as build_main
    ctx.invoke(build_main)


@main.command("generate-month")
@click.pass_context
def generate_month_cmd(ctx):
    """Generate tweets for a single month."""
    from wwi_realtime.generate_month import main as gen_main
    ctx.invoke(gen_main)


@main.command("generate-all")
@click.pass_context
def generate_all_cmd(ctx):
    """Generate tweets for the entire war."""
    from wwi_realtime.generate_all import main as gen_all_main
    ctx.invoke(gen_all_main)


@main.command("enrich")
@click.pass_context
def enrich_cmd(ctx):
    """Enrich events with primary sources from Chronicling America."""
    from wwi_realtime.enrich_events import main as enrich_main
    ctx.invoke(enrich_main)


@main.command("stats")
@click.option("--db", default="data/events.db", help="Path to events database")
def stats(db: str):
    """Show statistics about the event index."""
    import sqlite3
    from pathlib import Path

    from rich.console import Console
    from rich.table import Table

    console = Console()
    db_path = Path(db)

    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        return

    conn = sqlite3.connect(db_path)

    # Total events
    cursor = conn.execute("SELECT COUNT(*) FROM events")
    total = cursor.fetchone()[0]

    # Multi-day events
    cursor = conn.execute("SELECT COUNT(*) FROM events WHERE is_multi_day = 1")
    multi_day = cursor.fetchone()[0]

    # By year
    cursor = conn.execute("""
        SELECT strftime('%Y', date) as year, COUNT(*) as count
        FROM events
        GROUP BY year
        ORDER BY year
    """)
    by_year = cursor.fetchall()

    # By significance
    cursor = conn.execute("""
        SELECT significance, COUNT(*) as count
        FROM events
        GROUP BY significance
    """)
    by_sig = cursor.fetchall()

    # Busiest days
    cursor = conn.execute("""
        SELECT date, COUNT(*) as count
        FROM events
        GROUP BY date
        ORDER BY count DESC
        LIMIT 10
    """)
    busiest = cursor.fetchall()

    console.print(f"\n[bold]Event Index Statistics[/bold]")
    console.print(f"  Total events: {total}")
    console.print(f"  Multi-day events: {multi_day}")

    table = Table(title="Events by Year")
    table.add_column("Year")
    table.add_column("Count")
    for year, count in by_year:
        table.add_row(year, str(count))
    console.print(table)

    table = Table(title="Events by Significance")
    table.add_column("Significance")
    table.add_column("Count")
    for sig, count in by_sig:
        table.add_row(sig or "unknown", str(count))
    console.print(table)

    table = Table(title="Busiest Days")
    table.add_column("Date")
    table.add_column("Events")
    for day, count in busiest:
        table.add_row(day, str(count))
    console.print(table)

    conn.close()


if __name__ == "__main__":
    main()
