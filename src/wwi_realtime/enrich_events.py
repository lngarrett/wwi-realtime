"""Enrich events with primary sources from Chronicling America."""

import json
import sqlite3
import time
from datetime import date
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress

from wwi_realtime.utils.chronicling_america import (
    NewspaperArticle,
    format_article_for_prompt,
    search_for_event,
)

console = Console()

ARTICLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    headline TEXT,
    content TEXT,
    newspaper TEXT,
    state TEXT,
    city TEXT,
    page_url TEXT,
    event_ids TEXT,  -- JSON array of related event IDs
    search_query TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(date);
CREATE INDEX IF NOT EXISTS idx_articles_newspaper ON articles(newspaper);

-- Junction table for event-article relationships
CREATE TABLE IF NOT EXISTS event_articles (
    event_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    relevance_score REAL DEFAULT 1.0,
    PRIMARY KEY (event_id, article_id),
    FOREIGN KEY (event_id) REFERENCES events(id),
    FOREIGN KEY (article_id) REFERENCES articles(id)
);

CREATE INDEX IF NOT EXISTS idx_event_articles_event ON event_articles(event_id);
CREATE INDEX IF NOT EXISTS idx_event_articles_article ON event_articles(article_id);
"""


def init_articles_schema(conn: sqlite3.Connection) -> None:
    """Add the articles tables to an existing database."""
    conn.executescript(ARTICLES_SCHEMA)
    conn.commit()
    console.print("[green]Articles schema initialized[/green]")


def insert_article(
    conn: sqlite3.Connection,
    article: NewspaperArticle,
    event_id: str,
    search_query: str,
) -> bool:
    """Insert an article and link it to an event. Returns True if new article."""
    try:
        # Insert or update article
        conn.execute(
            """
            INSERT OR IGNORE INTO articles
            (id, date, headline, content, newspaper, state, city, page_url, search_query)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.id,
                str(article.date),
                article.headline,
                article.content,
                article.newspaper,
                article.state,
                article.city,
                article.page_url,
                search_query,
            ),
        )

        # Link to event
        conn.execute(
            """
            INSERT OR IGNORE INTO event_articles (event_id, article_id)
            VALUES (?, ?)
            """,
            (event_id, article.id),
        )

        return conn.total_changes > 0
    except sqlite3.Error as e:
        console.print(f"[yellow]Warning: Failed to insert article: {e}[/yellow]")
        return False


def get_events_to_enrich(
    conn: sqlite3.Connection,
    start_date: date | None = None,
    end_date: date | None = None,
    significance: str | None = None,
    limit: int | None = None,
) -> list[tuple[str, str, date, str | None]]:
    """Get events that need enrichment.

    Returns list of (event_id, title, date, summary) tuples.
    """
    query = """
        SELECT e.id, e.title, e.date, e.summary
        FROM events e
        LEFT JOIN event_articles ea ON e.id = ea.event_id
        WHERE ea.event_id IS NULL
    """
    params = []

    if start_date:
        query += " AND e.date >= ?"
        params.append(str(start_date))

    if end_date:
        query += " AND e.date <= ?"
        params.append(str(end_date))

    if significance:
        query += " AND e.significance = ?"
        params.append(significance)

    query += " ORDER BY e.date"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    cursor = conn.execute(query, params)
    results = []
    for row in cursor.fetchall():
        event_date = date.fromisoformat(row[2])
        results.append((row[0], row[1], event_date, row[3]))

    return results


def enrich_event(
    conn: sqlite3.Connection,
    event_id: str,
    event_title: str,
    event_date: date,
    event_summary: str | None,
    max_articles: int = 3,
) -> int:
    """Search for and store articles related to an event.

    Returns number of articles found.
    """
    articles = search_for_event(
        event_title=event_title,
        event_date=event_date,
        event_summary=event_summary,
        max_results=max_articles,
    )

    # Build search query string for reference
    stop_words = {"the", "of", "at", "in", "on", "a", "an", "and", "or", "to", "for"}
    words = event_title.lower().replace("(", "").replace(")", "").split()
    key_words = [w for w in words if w not in stop_words and len(w) > 2]
    search_query = " ".join(key_words[:5])

    inserted = 0
    for article in articles:
        if insert_article(conn, article, event_id, search_query):
            inserted += 1

    conn.commit()
    return len(articles)


def get_articles_for_event(conn: sqlite3.Connection, event_id: str) -> list[dict]:
    """Get all articles linked to an event."""
    cursor = conn.execute(
        """
        SELECT a.id, a.date, a.headline, a.content, a.newspaper,
               a.state, a.city, a.page_url
        FROM articles a
        JOIN event_articles ea ON a.id = ea.article_id
        WHERE ea.event_id = ?
        ORDER BY a.date
        """,
        (event_id,),
    )

    articles = []
    for row in cursor.fetchall():
        articles.append({
            "id": row[0],
            "date": row[1],
            "headline": row[2],
            "content": row[3],
            "newspaper": row[4],
            "state": row[5],
            "city": row[6],
            "page_url": row[7],
        })

    return articles


def format_articles_for_prompt(articles: list[dict], max_length: int = 2000) -> str:
    """Format multiple articles for inclusion in an LLM prompt."""
    if not articles:
        return ""

    parts = []
    total_len = 0

    for article in articles:
        # Reconstruct NewspaperArticle for formatting
        na = NewspaperArticle(
            id=article["id"],
            date=date.fromisoformat(article["date"]),
            newspaper=article["newspaper"],
            headline=article["headline"],
            content=article["content"],
            page_url=article["page_url"],
            state=article["state"],
            city=article["city"],
        )

        formatted = format_article_for_prompt(na)

        if total_len + len(formatted) > max_length:
            break

        parts.append(formatted)
        total_len += len(formatted) + 2  # +2 for newlines

    return "\n\n".join(parts)


@click.command()
@click.option(
    "--db",
    default="data/events.db",
    help="Path to SQLite database",
)
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Start date for enrichment (YYYY-MM-DD)",
)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="End date for enrichment (YYYY-MM-DD)",
)
@click.option(
    "--significance",
    type=click.Choice(["high", "medium", "low"]),
    help="Only enrich events of this significance",
)
@click.option(
    "--limit",
    type=int,
    help="Maximum number of events to enrich",
)
@click.option(
    "--delay",
    default=1.0,
    help="Delay between API requests (seconds)",
)
@click.option(
    "--max-articles",
    default=3,
    help="Maximum articles per event",
)
@click.option(
    "--init-schema",
    is_flag=True,
    help="Initialize articles schema (run once)",
)
def main(
    db: str,
    start_date,
    end_date,
    significance: str | None,
    limit: int | None,
    delay: float,
    max_articles: int,
    init_schema: bool,
):
    """Enrich events with primary sources from Chronicling America."""
    db_path = Path(db)

    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        console.print("Run 'wwi build-index' first to create the event index.")
        raise SystemExit(1)

    conn = sqlite3.connect(db_path)

    if init_schema:
        init_articles_schema(conn)

    # Get events to enrich
    events = get_events_to_enrich(
        conn,
        start_date=start_date.date() if start_date else None,
        end_date=end_date.date() if end_date else None,
        significance=significance,
        limit=limit,
    )

    if not events:
        console.print("[yellow]No events found to enrich[/yellow]")
        conn.close()
        return

    console.print(f"[green]Found {len(events)} events to enrich[/green]")

    total_articles = 0
    events_with_articles = 0

    with Progress() as progress:
        task = progress.add_task("[green]Enriching events...", total=len(events))

        for event_id, title, event_date, summary in events:
            progress.update(task, description=f"[cyan]{title[:40]}...")

            found = enrich_event(
                conn,
                event_id=event_id,
                event_title=title,
                event_date=event_date,
                event_summary=summary,
                max_articles=max_articles,
            )

            if found > 0:
                events_with_articles += 1
                total_articles += found
                console.print(f"  [green]✓ {title}: {found} articles[/green]")
            else:
                console.print(f"  [yellow]○ {title}: no articles found[/yellow]")

            progress.update(task, advance=1)

            # Rate limiting
            time.sleep(delay)

    # Summary
    console.print("\n[bold green]Enrichment Summary:[/bold green]")
    console.print(f"  Events processed: {len(events)}")
    console.print(f"  Events with articles: {events_with_articles}")
    console.print(f"  Total articles found: {total_articles}")

    # Show overall article stats
    cursor = conn.execute("SELECT COUNT(*) FROM articles")
    total_stored = cursor.fetchone()[0]
    console.print(f"  Total articles in database: {total_stored}")

    conn.close()


if __name__ == "__main__":
    main()
