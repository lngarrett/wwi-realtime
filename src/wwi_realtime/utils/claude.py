"""Claude API integration for tweet generation using the story engine."""

import json
import os
import re
from dataclasses import dataclass, asdict

from anthropic import Anthropic

from wwi_realtime.generate.prompts import (
    SYSTEM_PROMPT,
    build_month_prompt,
    build_thread_prompt,
    EventContext,
)
from wwi_realtime.sources.search import PassageResult


@dataclass
class GeneratedTweet:
    """A single generated tweet."""
    text: str
    position: int = 1
    total: int = 1
    event_id: str | None = None
    source_attribution: str | None = None
    has_quote: bool = False


@dataclass
class TweetThread:
    """A thread of connected tweets for a major event."""
    event_title: str
    event_date: str
    arc_id: str | None
    arc_title: str | None
    tweets: list[GeneratedTweet]


@dataclass
class DayOutput:
    """All content for a single day."""
    date: str
    tweets: list[GeneratedTweet]
    threads: list[TweetThread]
    summary: str


@dataclass
class MonthOutput:
    """Output from generating a full month."""
    month: str
    days: dict[str, DayOutput]
    month_summary: str


MONTH_GENERATION_PROMPT = """You are generating tweets for {month} during World War I, as if reporting from that time.

Your task is to write historically accurate tweets that tell HUMAN stories, not just facts. Use present tense. Be vivid and specific.

## PREVIOUS MONTH CONTEXT:
{previous_month_summary}

## ACTIVE NARRATIVE ARCS THIS MONTH:
{arc_narratives}

## EVENTS BY DATE:
{events_by_date}

## PRIMARY SOURCE MATERIAL:
Use these passages to add human voices and specific details. QUOTE THEM DIRECTLY when relevant.
{passages_section}

## RULES:
1. Generate 1-10 tweets per day (280 characters max each)
2. Voice: Present tense ("Fighting continues..." not "Fighting continued...")
3. HUMAN FOCUS: Name individuals, give ages, quote their words
4. USE THE SOURCES: Include direct quotes with attribution ("As Jünger wrote: '...'")
5. THREAD MAJOR EVENTS: Generate 2-4 connected tweets for significant events
6. Balance perspectives: Show British, German, French viewpoints
7. Connect to arcs: Reference the larger narrative ("Day 5 of the Somme offensive...")
8. Quiet days may have 0-1 tweets

## THREAD FORMAT:
For major events, create threads like:
{{"type": "thread", "event_title": "Battle Name", "arc_id": "arc_id", "arc_title": "Arc Name", "tweets": [
  {{"text": "Tweet 1 text", "position": 1, "total": 3, "has_quote": false}},
  {{"text": "\\"Quote here\\" - Author", "position": 2, "total": 3, "has_quote": true, "source_attribution": "Author Name, Book Title"}},
  {{"text": "Tweet 3 text", "position": 3, "total": 3, "has_quote": false}}
]}}

## OUTPUT FORMAT:
Output a JSON object:
{{
  "days": {{
    "YYYY-MM-DD": {{
      "tweets": [
        {{"text": "Single tweet text", "has_quote": false}}
      ],
      "threads": [
        {{"type": "thread", "event_title": "Major Event", "arc_id": "arc", "arc_title": "Arc Title", "tweets": [...]}}
      ],
      "summary": "Brief day summary"
    }}
  }},
  "month_summary": "Key events and narrative threads this month"
}}

Generate compelling, human-centered coverage for {month}."""


def get_client() -> Anthropic:
    """Get configured Anthropic client."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    return Anthropic(api_key=api_key)


def format_arc_narratives(arc_narratives: dict[str, str]) -> str:
    """Format arc narratives for prompt."""
    if not arc_narratives:
        return "No specific arcs active."

    lines = []
    for arc_id, narrative in arc_narratives.items():
        arc_name = arc_id.replace("_", " ").title()
        lines.append(f"### {arc_name}")
        lines.append(narrative[:400] if narrative else "Ongoing military operations.")
        lines.append("")

    return "\n".join(lines)


def format_events_for_prompt(events_by_date: dict[str, list[dict]]) -> str:
    """Format events grouped by date."""
    if not events_by_date:
        return "No events recorded."

    lines = []
    for date_str, events in sorted(events_by_date.items()):
        lines.append(f"\n### {date_str}")
        for event in events:
            title = event.get("title", "Unknown")
            summary = event.get("summary", "")[:300]
            arc_id = event.get("arc_id", "")
            lines.append(f"- **{title}**")
            if summary:
                lines.append(f"  {summary}")
            if arc_id:
                lines.append(f"  Arc: {arc_id}")

    return "\n".join(lines)


def format_passages_for_prompt(passages_by_event: dict[str, list[PassageResult]], max_chars: int = 8000) -> str:
    """Format passages for prompt, grouping by event."""
    if not passages_by_event:
        return "No primary sources available for this month."

    lines = []
    total_chars = 0

    for event_title, passages in passages_by_event.items():
        if total_chars >= max_chars:
            break

        lines.append(f"\n### For: {event_title}")

        for p in passages[:3]:  # Max 3 passages per event
            attribution = f"{p.source_title} by {p.source_author}"
            if p.source_perspective:
                attribution += f" ({p.source_perspective})"

            quote_marker = " [HAS QUOTE]" if p.has_direct_quote else ""

            entry = f"""
**{attribution}**{quote_marker}
"{p.content[:400]}"
"""
            if total_chars + len(entry) > max_chars:
                break

            lines.append(entry)
            total_chars += len(entry)

    return "\n".join(lines)


def generate_month_tweets(
    month: str,
    events_by_date: dict[str, list[dict]],
    passages_by_event: dict[str, list[PassageResult]],
    arc_narratives: dict[str, str],
    previous_month_summary: str = "This is the beginning of the war.",
    model: str = "claude-sonnet-4-20250514",
) -> MonthOutput:
    """Generate tweets for an entire month using the story engine.

    Args:
        month: Month in YYYY-MM format
        events_by_date: Dict mapping date strings to list of events
        passages_by_event: Dict mapping event titles to relevant passages
        arc_narratives: Dict mapping arc_id to narrative summary
        previous_month_summary: Summary from previous month
        model: Claude model to use

    Returns:
        MonthOutput with all generated content
    """
    client = get_client()

    prompt = MONTH_GENERATION_PROMPT.format(
        month=month,
        previous_month_summary=previous_month_summary or "This is the beginning of the war.",
        arc_narratives=format_arc_narratives(arc_narratives),
        events_by_date=format_events_for_prompt(events_by_date),
        passages_section=format_passages_for_prompt(passages_by_event),
    )

    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = response.content[0].text

    # Extract JSON from response
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
        # Parse single tweets
        tweets = []
        for t in day_data.get("tweets", []):
            tweets.append(GeneratedTweet(
                text=t.get("text", ""),
                position=1,
                total=1,
                has_quote=t.get("has_quote", False),
                source_attribution=t.get("source_attribution"),
            ))

        # Parse threads
        threads = []
        for thread_data in day_data.get("threads", []):
            thread_tweets = []
            for t in thread_data.get("tweets", []):
                thread_tweets.append(GeneratedTweet(
                    text=t.get("text", ""),
                    position=t.get("position", 1),
                    total=t.get("total", len(thread_data.get("tweets", []))),
                    has_quote=t.get("has_quote", False),
                    source_attribution=t.get("source_attribution"),
                ))

            threads.append(TweetThread(
                event_title=thread_data.get("event_title", ""),
                event_date=date_str,
                arc_id=thread_data.get("arc_id"),
                arc_title=thread_data.get("arc_title"),
                tweets=thread_tweets,
            ))

        days[date_str] = DayOutput(
            date=date_str,
            tweets=tweets,
            threads=threads,
            summary=day_data.get("summary", ""),
        )

    return MonthOutput(
        month=month,
        days=days,
        month_summary=data.get("month_summary", ""),
    )


def validate_tweets(month_output: MonthOutput) -> list[str]:
    """Validate generated content for common issues."""
    warnings = []

    for date_str, day in month_output.days.items():
        # Check single tweets
        for i, tweet in enumerate(day.tweets):
            if len(tweet.text) > 280:
                warnings.append(f"{date_str} tweet {i+1}: Exceeds 280 chars ({len(tweet.text)})")

        # Check thread tweets
        for thread in day.threads:
            for i, tweet in enumerate(thread.tweets):
                if len(tweet.text) > 280:
                    warnings.append(f"{date_str} thread '{thread.event_title}' tweet {i+1}: Exceeds 280 chars ({len(tweet.text)})")

            # Check thread has quotes (should have at least one)
            has_any_quote = any(t.has_quote for t in thread.tweets)
            if not has_any_quote and len(thread.tweets) >= 3:
                warnings.append(f"{date_str} thread '{thread.event_title}': No quotes in {len(thread.tweets)}-tweet thread")

    return warnings


def output_to_dict(month_output: MonthOutput) -> dict:
    """Convert MonthOutput to serializable dict."""
    return {
        "month": month_output.month,
        "month_summary": month_output.month_summary,
        "days": {
            date_str: {
                "date": day.date,
                "summary": day.summary,
                "tweets": [asdict(t) for t in day.tweets],
                "threads": [
                    {
                        "event_title": thread.event_title,
                        "event_date": thread.event_date,
                        "arc_id": thread.arc_id,
                        "arc_title": thread.arc_title,
                        "tweets": [asdict(t) for t in thread.tweets],
                    }
                    for thread in day.threads
                ],
            }
            for date_str, day in month_output.days.items()
        },
    }
