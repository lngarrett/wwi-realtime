"""Add source metadata to generated tweets by matching back to database."""

import json
import sqlite3
from pathlib import Path

import click
from rich.console import Console

console = Console()


def get_events_for_date(conn: sqlite3.Connection, date_str: str) -> list[dict]:
    """Get all events for a date with their sources."""
    cursor = conn.execute(
        """
        SELECT id, title, wikipedia_url, summary, image_url, image_caption
        FROM events
        WHERE date = ?
        """,
        (date_str,),
    )
    return [
        {
            "id": row[0],
            "title": row[1],
            "wikipedia_url": row[2],
            "summary": row[3],
            "image_url": row[4],
            "image_caption": row[5],
        }
        for row in cursor.fetchall()
    ]


def get_articles_for_event(conn: sqlite3.Connection, event_id: str) -> list[dict]:
    """Get all articles linked to an event."""
    cursor = conn.execute(
        """
        SELECT a.id, a.newspaper, a.headline, a.page_url, a.date
        FROM articles a
        JOIN event_articles ea ON a.id = ea.article_id
        WHERE ea.event_id = ?
        """,
        (event_id,),
    )
    return [
        {
            "id": row[0],
            "newspaper": row[1],
            "headline": row[2],
            "url": row[3],
            "date": row[4],
        }
        for row in cursor.fetchall()
    ]


def match_tweet_to_event(tweet_text: str, events: list[dict]) -> dict | None:
    """Try to match a tweet to an event based on content overlap."""
    tweet_lower = tweet_text.lower()

    best_match = None
    best_score = 0

    for event in events:
        score = 0
        title_words = event["title"].lower().split()

        # Count how many title words appear in tweet
        for word in title_words:
            if len(word) > 3 and word in tweet_lower:
                score += 1

        # Check summary overlap too
        if event.get("summary"):
            summary_words = event["summary"].lower().split()[:20]
            for word in summary_words:
                if len(word) > 4 and word in tweet_lower:
                    score += 0.5

        if score > best_score:
            best_score = score
            best_match = event

    return best_match if best_score >= 2 else None


def add_sources_to_day(conn: sqlite3.Connection, day_file: Path) -> int:
    """Add source metadata to a single day's tweets. Returns count of sourced tweets."""
    data = json.loads(day_file.read_text())
    date_str = data["date"]

    # Get events for this date
    events = get_events_for_date(conn, date_str)

    # Build article lookup by event
    articles_by_event = {}
    for event in events:
        articles_by_event[event["id"]] = get_articles_for_event(conn, event["id"])

    sourced_count = 0

    for tweet in data.get("tweets", []):
        # Try to match tweet to an event
        matched_event = match_tweet_to_event(tweet["text"], events)

        if matched_event:
            sourced_count += 1
            tweet["sources"] = {
                "event": {
                    "id": matched_event["id"],
                    "title": matched_event["title"],
                    "wikipedia_url": matched_event["wikipedia_url"],
                },
                "articles": articles_by_event.get(matched_event["id"], []),
            }
            # Add image if available
            if matched_event.get("image_url"):
                tweet["image"] = {
                    "url": matched_event["image_url"],
                    "caption": matched_event.get("image_caption"),
                    "source": "Wikimedia Commons",
                }
        else:
            tweet["sources"] = {"event": None, "articles": []}

    # Write back
    day_file.write_text(json.dumps(data, indent=2))
    return sourced_count


@click.command()
@click.option("--db", default="data/events.db", help="Path to events database")
@click.option("--tweets", default="tweets", help="Path to tweets directory")
@click.option("--month", help="Specific month to process (YYYY-MM)")
def main(db: str, tweets: str, month: str | None):
    """Add source metadata to generated tweets."""
    db_path = Path(db)
    tweets_path = Path(tweets)

    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        return

    conn = sqlite3.connect(db_path)

    # Find month directories to process
    if month:
        month_dirs = [tweets_path / month]
    else:
        month_dirs = sorted(tweets_path.glob("????-??"))

    total_tweets = 0
    total_sourced = 0

    for month_dir in month_dirs:
        if not month_dir.is_dir():
            continue

        console.print(f"\n[bold]Processing {month_dir.name}[/bold]")

        for day_file in sorted(month_dir.glob("*.json")):
            sourced = add_sources_to_day(conn, day_file)
            data = json.loads(day_file.read_text())
            tweet_count = len(data.get("tweets", []))

            total_tweets += tweet_count
            total_sourced += sourced

            if tweet_count > 0:
                console.print(f"  {day_file.name}: {sourced}/{tweet_count} tweets sourced")

    console.print(f"\n[green]Total: {total_sourced}/{total_tweets} tweets with sources[/green]")
    conn.close()


if __name__ == "__main__":
    main()
