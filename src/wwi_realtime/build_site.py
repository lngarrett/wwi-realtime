"""Build static HTML site from generated tweets.

Supports both single tweets and multi-tweet threads with source attributions.
"""

import json
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

console = Console()


# Thread styling additions
THREAD_STYLES = """
        /* Thread container */
        .tweet-thread {
            border-left: 3px solid #1da1f2;
            margin-left: 0;
        }

        .tweet-thread .tweet {
            border-left: none;
            position: relative;
        }

        .tweet-thread .tweet::before {
            content: '';
            position: absolute;
            left: -16px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: #38444d;
        }

        .tweet-thread .tweet:last-child::before {
            bottom: 50%;
        }

        /* Thread position indicator */
        .thread-position {
            display: inline-block;
            background: #1da1f2;
            color: #fff;
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 10px;
            margin-right: 8px;
        }

        /* Quote styling */
        .tweet-quote {
            font-style: italic;
            color: #e8e8e8;
        }

        .tweet-attribution {
            margin-top: 8px;
            font-size: 13px;
            color: #8899a6;
        }

        .tweet-attribution .author {
            color: #1da1f2;
        }

        /* Primary source styling */
        .primary-source {
            background: #192734;
            border-left: 3px solid #17bf63;
            padding: 8px 12px;
            margin-top: 8px;
            border-radius: 0 8px 8px 0;
        }

        .primary-source .source-quote {
            font-style: italic;
            color: #e8e8e8;
        }

        .primary-source .source-meta {
            margin-top: 4px;
            font-size: 12px;
            color: #8899a6;
        }

        .primary-source .source-meta .author {
            color: #17bf63;
            font-weight: 600;
        }

        /* Arc badge */
        .arc-badge {
            display: inline-block;
            background: #38444d;
            color: #8899a6;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 12px;
            margin-bottom: 8px;
        }
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WWI Real-Time | {month_display}</title>
    <meta name="description" content="World War I events as they happened, {month_display}">
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #15202b;
            color: #d9d9d9;
            line-height: 1.5;
        }}

        .container {{
            max-width: 600px;
            margin: 0 auto;
            border-left: 1px solid #38444d;
            border-right: 1px solid #38444d;
            min-height: 100vh;
        }}

        /* Header */
        .profile-header {{
            padding: 16px;
            border-bottom: 1px solid #38444d;
            background: #192734;
        }}

        .profile-header h1 {{
            font-size: 20px;
            font-weight: 800;
            color: #fff;
            margin-bottom: 4px;
        }}

        .profile-header .handle {{
            color: #8899a6;
            font-size: 15px;
        }}

        .profile-header .bio {{
            margin-top: 12px;
            font-size: 15px;
            color: #d9d9d9;
        }}

        .profile-header .meta {{
            margin-top: 12px;
            font-size: 14px;
            color: #8899a6;
        }}

        .profile-header .meta a {{
            color: #1da1f2;
            text-decoration: none;
        }}

        /* Month navigation */
        .month-nav {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            border-bottom: 1px solid #38444d;
            background: #192734;
        }}

        .month-nav h2 {{
            font-size: 18px;
            font-weight: 700;
            color: #fff;
        }}

        .month-nav a {{
            color: #1da1f2;
            text-decoration: none;
            font-size: 14px;
        }}

        /* Day separator */
        .day-header {{
            padding: 12px 16px;
            background: #192734;
            border-bottom: 1px solid #38444d;
            position: sticky;
            top: 0;
            z-index: 10;
        }}

        .day-header h3 {{
            font-size: 15px;
            font-weight: 700;
            color: #fff;
        }}

        .day-header .day-summary {{
            font-size: 13px;
            color: #8899a6;
            margin-top: 2px;
        }}

        /* Tweet */
        .tweet {{
            padding: 12px 16px;
            border-bottom: 1px solid #38444d;
            transition: background 0.2s;
        }}

        .tweet:hover {{
            background: #192734;
        }}

        .tweet-content {{
            font-size: 15px;
            color: #d9d9d9;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}

        .tweet-image {{
            margin-top: 12px;
            border-radius: 16px;
            overflow: hidden;
            border: 1px solid #38444d;
        }}

        .tweet-image img {{
            width: 100%;
            max-height: 400px;
            object-fit: cover;
            display: block;
        }}

        .tweet-image .caption {{
            padding: 8px 12px;
            font-size: 13px;
            color: #8899a6;
            background: #192734;
        }}

        /* Sources */
        .tweet-sources {{
            margin-top: 12px;
            padding-top: 8px;
            border-top: 1px solid #38444d;
        }}

        .tweet-sources summary {{
            font-size: 13px;
            color: #8899a6;
            cursor: pointer;
            user-select: none;
        }}

        .tweet-sources summary:hover {{
            color: #1da1f2;
        }}

        .source-list {{
            margin-top: 8px;
            font-size: 13px;
        }}

        .source-list a {{
            color: #1da1f2;
            text-decoration: none;
        }}

        .source-list a:hover {{
            text-decoration: underline;
        }}

        .source-item {{
            margin: 4px 0;
            padding-left: 12px;
            border-left: 2px solid #38444d;
        }}

        .source-item .label {{
            color: #8899a6;
            font-size: 12px;
            text-transform: uppercase;
        }}

        /* Footer */
        .footer {{
            padding: 20px 16px;
            text-align: center;
            color: #8899a6;
            font-size: 13px;
            border-top: 1px solid #38444d;
        }}

        .footer a {{
            color: #1da1f2;
            text-decoration: none;
        }}

        /* No tweets message */
        .no-tweets {{
            padding: 40px 16px;
            text-align: center;
            color: #8899a6;
        }}
{thread_styles}
    </style>
</head>
<body>
    <div class="container">
        <div class="profile-header">
            <h1>World War I in Real Time</h1>
            <div class="handle">@RealTimeWWI</div>
            <div class="bio">Events of the Great War as they happened, 110 years ago today. Sourced from contemporary newspapers and historical records.</div>
            <div class="meta">
                <a href="https://github.com/example/wwi-realtime">GitHub</a> ·
                <a href="https://chroniclingamerica.loc.gov/">Library of Congress</a>
            </div>
        </div>

        <div class="month-nav">
            <a href="#">← Previous</a>
            <h2>{month_display}</h2>
            <a href="#">Next →</a>
        </div>

        {content}

        <div class="footer">
            Generated from Wikipedia events and Library of Congress newspaper archives.<br>
            <a href="https://chroniclingamerica.loc.gov/">Chronicling America</a> ·
            <a href="https://en.wikipedia.org/">Wikipedia</a>
        </div>
    </div>
</body>
</html>
"""

DAY_TEMPLATE = """
<div class="day-header">
    <h3>{date_display}</h3>
    <div class="day-summary">{summary}</div>
</div>
{tweets}
"""

TWEET_TEMPLATE = """
<div class="tweet">
    <div class="tweet-content">{text}</div>
    {image_html}
    {sources_html}
</div>
"""

IMAGE_TEMPLATE = """
<div class="tweet-image">
    <a href="{url}" target="_blank">
        <img src="{url}" alt="{caption}" loading="lazy">
    </a>
    <div class="caption">{caption} — Wikimedia Commons</div>
</div>
"""

SOURCES_TEMPLATE = """
<details class="tweet-sources">
    <summary>Sources ({count})</summary>
    <div class="source-list">
        {sources}
    </div>
</details>
"""

THREAD_TEMPLATE = """
<div class="tweet-thread">
    {arc_badge}
    {tweets}
</div>
"""

THREAD_TWEET_TEMPLATE = """
<div class="tweet">
    <div class="tweet-content">
        <span class="thread-position">{position}/{total}</span>
        {text}
    </div>
    {attribution_html}
    {primary_source_html}
    {image_html}
</div>
"""

ARC_BADGE_TEMPLATE = """
<div style="padding: 8px 16px;">
    <span class="arc-badge">{arc_title}</span>
</div>
"""

PRIMARY_SOURCE_TEMPLATE = """
<div class="primary-source">
    <div class="source-quote">"{quote}"</div>
    <div class="source-meta">
        — <span class="author">{author}</span>, <em>{title}</em>
    </div>
</div>
"""

ATTRIBUTION_TEMPLATE = """
<div class="tweet-attribution">
    — <span class="author">{author}</span>
</div>
"""


def format_date(date_str: str) -> str:
    """Format date string for display."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%A, %B %d, %Y")


def format_month(month_str: str) -> str:
    """Format month string for display."""
    year, month = month_str.split("-")
    dt = datetime(int(year), int(month), 1)
    return dt.strftime("%B %Y")


def render_sources(tweet: dict) -> str:
    """Render sources section for a tweet."""
    sources = tweet.get("sources", {})
    items = []

    # Event source
    event = sources.get("event")
    if event and event.get("wikipedia_url"):
        items.append(f'''
            <div class="source-item">
                <div class="label">Wikipedia</div>
                <a href="{event['wikipedia_url']}" target="_blank">{event['title']}</a>
            </div>
        ''')

    # Newspaper articles
    articles = sources.get("articles", [])
    for article in articles[:3]:  # Limit to 3
        items.append(f'''
            <div class="source-item">
                <div class="label">Newspaper</div>
                <a href="{article['url']}" target="_blank">{article['newspaper'][:50]}</a>
                <span style="color: #8899a6;"> ({article['date']})</span>
            </div>
        ''')

    if not items:
        return ""

    return SOURCES_TEMPLATE.format(
        count=len(items),
        sources="\n".join(items)
    )


def render_tweet(tweet: dict) -> str:
    """Render a single tweet."""
    # Image
    image_html = ""
    if tweet.get("image") and tweet["image"].get("url"):
        image_html = IMAGE_TEMPLATE.format(
            url=tweet["image"]["url"],
            caption=tweet["image"].get("caption", "Historical image")
        )

    # Sources
    sources_html = render_sources(tweet)

    return TWEET_TEMPLATE.format(
        text=tweet["text"],
        image_html=image_html,
        sources_html=sources_html
    )


def render_thread_tweet(tweet: dict, position: int, total: int) -> str:
    """Render a single tweet within a thread."""
    # Image
    image_html = ""
    if tweet.get("image") and tweet["image"].get("url"):
        image_html = IMAGE_TEMPLATE.format(
            url=tweet["image"]["url"],
            caption=tweet["image"].get("caption", "Historical image")
        )

    # Attribution (for quotes)
    attribution_html = ""
    if tweet.get("source_attribution"):
        attribution_html = ATTRIBUTION_TEMPLATE.format(
            author=tweet["source_attribution"]
        )

    # Primary source quote
    primary_source_html = ""
    if tweet.get("primary_source"):
        ps = tweet["primary_source"]
        primary_source_html = PRIMARY_SOURCE_TEMPLATE.format(
            quote=ps.get("quote", ""),
            author=ps.get("author", "Unknown"),
            title=ps.get("title", ""),
        )

    return THREAD_TWEET_TEMPLATE.format(
        position=position,
        total=total,
        text=tweet["text"],
        attribution_html=attribution_html,
        primary_source_html=primary_source_html,
        image_html=image_html,
    )


def render_thread(thread: dict) -> str:
    """Render a multi-tweet thread."""
    tweets = thread.get("tweets", [])
    if not tweets:
        return ""

    total = len(tweets)

    # Arc badge
    arc_badge = ""
    if thread.get("arc_title"):
        arc_badge = ARC_BADGE_TEMPLATE.format(arc_title=thread["arc_title"])

    # Render each tweet in the thread
    tweets_html = []
    for i, tweet in enumerate(tweets, 1):
        tweets_html.append(render_thread_tweet(tweet, i, total))

    return THREAD_TEMPLATE.format(
        arc_badge=arc_badge,
        tweets="\n".join(tweets_html)
    )


def render_day(day_file: Path) -> str:
    """Render all tweets for a day.

    Supports both single tweets and multi-tweet threads.
    Data format can include:
    - "tweets": list of individual tweets
    - "threads": list of thread objects with "tweets" arrays
    """
    data = json.loads(day_file.read_text())

    content_html = []

    # Render threads first (major events)
    threads = data.get("threads", [])
    for thread in threads:
        thread_html = render_thread(thread)
        if thread_html:
            content_html.append(thread_html)

    # Render individual tweets
    tweets = data.get("tweets", [])
    for tweet in tweets:
        content_html.append(render_tweet(tweet))

    if not content_html:
        return ""

    return DAY_TEMPLATE.format(
        date_display=format_date(data["date"]),
        summary=data.get("summary", ""),
        tweets="\n".join(content_html)
    )


def build_month_page(month_dir: Path, output_dir: Path) -> Path:
    """Build HTML page for a month."""
    month = month_dir.name

    # Collect all days
    day_files = sorted(month_dir.glob("*.json"))

    if not day_files:
        console.print(f"[yellow]No tweets found in {month_dir}[/yellow]")
        return None

    # Render each day
    days_html = []
    for day_file in day_files:
        day_html = render_day(day_file)
        if day_html:
            days_html.append(day_html)

    if not days_html:
        return None

    # Build full page with thread styles
    html = HTML_TEMPLATE.format(
        month_display=format_month(month),
        content="\n".join(days_html),
        thread_styles=THREAD_STYLES,
    )

    # Write output
    output_file = output_dir / f"{month}.html"
    output_file.write_text(html)

    return output_file


@click.command()
@click.option("--tweets", default="tweets", help="Path to tweets directory")
@click.option("--output", default="site", help="Output directory for HTML")
@click.option("--month", help="Specific month to build (YYYY-MM)")
def main(tweets: str, output: str, month: str | None):
    """Build static HTML site from tweets."""
    tweets_dir = Path(tweets)
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if month:
        month_dirs = [tweets_dir / month]
    else:
        month_dirs = sorted(tweets_dir.glob("????-??"))

    built = 0
    for month_dir in month_dirs:
        if not month_dir.is_dir():
            continue

        console.print(f"Building {month_dir.name}...")
        output_file = build_month_page(month_dir, output_dir)

        if output_file:
            console.print(f"  → {output_file}")
            built += 1

    console.print(f"\n[green]Built {built} pages in {output_dir}/[/green]")


if __name__ == "__main__":
    main()
