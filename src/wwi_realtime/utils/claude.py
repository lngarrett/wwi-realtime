"""Claude API integration for tweet generation."""

import json
import os
from dataclasses import dataclass

from anthropic import Anthropic


@dataclass
class GeneratedTweet:
    """A single generated tweet."""
    text: str
    facts_used: list[str]
    event_id: str | None = None


@dataclass
class DayTweets:
    """All tweets for a single day."""
    date: str
    tweets: list[GeneratedTweet]
    summary: str


@dataclass
class MonthOutput:
    """Output from generating a full month of tweets."""
    month: str
    days: dict[str, DayTweets]
    month_summary: str


MONTH_GENERATION_PROMPT = """You are generating tweets for {month} during World War I, as if reporting from that time.

Your task is to write historically accurate tweets in the voice of a news wire service or newspaper correspondent. Use present tense. Be factual and measured.

ONGOING MULTI-DAY EVENTS:
{ongoing_events}

EVENTS BY DATE:
{events_by_date}

PREVIOUS MONTH SUMMARY (for continuity):
{previous_month_summary}

{primary_sources_section}

RULES:
1. Generate 0-15 tweets per day (280 characters each maximum)
2. Voice: Neutral news correspondent, present tense ("Fighting continues..." not "Fighting continued...")
3. TONE: Measured and factual. Avoid sensationalism. Do NOT use words like "BREAKING", "ALERT", "VICTORY!", or excessive exclamation points. Write like a serious newspaper, not a tabloid.
4. CRITICAL: Only state facts present in the EVENTS and PRIMARY SOURCES provided above. Do not invent details, quotes, numbers, or specifics not explicitly mentioned.
5. Reference multi-day events with context ("Day 5 of the Somme offensive...")
6. Pace coverage: Don't front-load if later days are more significant
7. Some quiet days may have 0-1 tweets; that's acceptable
8. For each tweet, cite which facts from the events you used
9. When PRIMARY SOURCES are available, use their specific details - casualty figures, place names, unit designations. Quote headlines when relevant, but don't be breathless about it.
10. Let the facts speak for themselves. "200 killed in Mostar fighting" is more powerful than "CARNAGE! Massive death toll!"

Output a JSON object with this exact structure:
{{
  "days": {{
    "YYYY-MM-DD": {{
      "tweets": [
        {{"text": "Tweet text here", "facts_used": ["fact1 from events", "fact2 from events"], "event_id": "optional_event_id"}}
      ],
      "summary": "Brief summary of this day for next month's context"
    }}
  }},
  "month_summary": "Key events this month for continuity with next month"
}}

Generate tweets for all days in {month}, even if some days have empty tweet arrays."""


def get_client() -> Anthropic:
    """Get configured Anthropic client."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    return Anthropic(api_key=api_key)


def format_events_for_prompt(events: list[dict]) -> str:
    """Format events list for inclusion in prompt."""
    if not events:
        return "No events recorded for this date."

    lines = []
    for event in events:
        date = event.get("date", "Unknown date")
        title = event.get("title", "Unknown event")
        summary = event.get("summary", "")
        location = event.get("location", "")

        line = f"- {date}: {title}"
        if location:
            line += f" (Location: {location})"
        if summary:
            line += f"\n  Summary: {summary[:300]}"
        lines.append(line)

    return "\n".join(lines)


def format_ongoing_events(multi_day_events: list[dict], month: str) -> str:
    """Format ongoing multi-day events for the prompt."""
    if not multi_day_events:
        return "None"

    lines = []
    for event in multi_day_events:
        title = event.get("title", "Unknown")
        start = event.get("start_date", "?")
        end = event.get("end_date", "ongoing")
        lines.append(f"- {title} (started {start}, ends {end})")

    return "\n".join(lines)


def format_primary_sources(articles_by_event: dict[str, list[dict]], max_total_chars: int = 6000) -> str:
    """Format primary sources for inclusion in prompt.

    Args:
        articles_by_event: Dict mapping event_id to list of article dicts
        max_total_chars: Maximum total characters for all sources

    Returns:
        Formatted string for prompt
    """
    if not articles_by_event:
        return ""

    parts = ["PRIMARY SOURCES (contemporary newspaper accounts):"]
    total_chars = 0

    for event_id, articles in articles_by_event.items():
        for article in articles:
            newspaper = article.get("newspaper", "Unknown newspaper")
            article_date = article.get("date", "Unknown date")
            headline = article.get("headline", "")
            content = article.get("content", "")[:500]  # Limit content per article

            # Build article entry
            entry_parts = [f"\n[{newspaper}, {article_date}]"]
            if headline:
                entry_parts.append(f"Headline: {headline}")
            if content:
                # Clean up OCR text
                import re
                content = re.sub(r'\s+', ' ', content).strip()
                entry_parts.append(f"Extract: {content}")

            entry = "\n".join(entry_parts)

            if total_chars + len(entry) > max_total_chars:
                break

            parts.append(entry)
            total_chars += len(entry)

        if total_chars >= max_total_chars:
            break

    if len(parts) == 1:  # Only header, no articles
        return ""

    return "\n".join(parts)


def generate_month_tweets(
    month: str,
    events_by_date: dict[str, list[dict]],
    ongoing_events: list[dict],
    previous_month_summary: str = "None - this is the first month.",
    articles_by_event: dict[str, list[dict]] | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> MonthOutput:
    """Generate tweets for an entire month.

    Args:
        month: Month in YYYY-MM format
        events_by_date: Dict mapping date strings to list of events
        ongoing_events: List of multi-day events active during this month
        previous_month_summary: Summary from previous month for continuity
        articles_by_event: Dict mapping event_id to list of newspaper articles
        model: Claude model to use

    Returns:
        MonthOutput with all generated tweets
    """
    client = get_client()

    # Format events for prompt
    events_text = []
    for date, events in sorted(events_by_date.items()):
        events_text.append(f"\n{date}:")
        for event in events:
            events_text.append(f"  - {event.get('title', 'Unknown')}")
            if event.get("summary"):
                events_text.append(f"    {event['summary'][:200]}")

    # Format primary sources
    primary_sources_section = format_primary_sources(articles_by_event or {})

    prompt = MONTH_GENERATION_PROMPT.format(
        month=month,
        ongoing_events=format_ongoing_events(ongoing_events, month),
        events_by_date="\n".join(events_text) if events_text else "No events recorded.",
        previous_month_summary=previous_month_summary,
        primary_sources_section=primary_sources_section,
    )

    response = client.messages.create(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )

    # Parse JSON response
    response_text = response.content[0].text

    # Try to extract JSON from response (handle markdown code blocks)
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0]
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0]

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse Claude response as JSON: {e}\nResponse: {response_text[:500]}")

    # Convert to dataclasses
    days = {}
    for date_str, day_data in data.get("days", {}).items():
        tweets = [
            GeneratedTweet(
                text=t.get("text", ""),
                facts_used=t.get("facts_used", []),
                event_id=t.get("event_id"),
            )
            for t in day_data.get("tweets", [])
        ]
        days[date_str] = DayTweets(
            date=date_str,
            tweets=tweets,
            summary=day_data.get("summary", ""),
        )

    return MonthOutput(
        month=month,
        days=days,
        month_summary=data.get("month_summary", ""),
    )


def validate_tweets(month_output: MonthOutput) -> list[str]:
    """Validate generated tweets for common issues.

    Returns list of warning messages.
    """
    warnings = []

    for date, day in month_output.days.items():
        for i, tweet in enumerate(day.tweets):
            # Check tweet length
            if len(tweet.text) > 280:
                warnings.append(f"{date} tweet {i+1}: Exceeds 280 chars ({len(tweet.text)})")

            # Check for empty facts_used (might indicate hallucination)
            if not tweet.facts_used:
                warnings.append(f"{date} tweet {i+1}: No facts cited")

            # Check for common hallucination indicators
            hallucination_indicators = [
                "it is said",
                "reportedly",
                "according to sources",
                "historians believe",
            ]
            text_lower = tweet.text.lower()
            for indicator in hallucination_indicators:
                if indicator in text_lower:
                    warnings.append(f"{date} tweet {i+1}: Contains '{indicator}' - verify accuracy")

    return warnings
