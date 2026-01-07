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


MONTH_GENERATION_PROMPT = """You are turning soldier memoirs into tweets for {month} during WWI.

## YOUR TASK
The passages below are from soldiers who lived through WWI. Turn them into tweets.
The passages ARE the content. Events just tell you when things happened.

## SOLDIER MEMOIRS - THESE ARE YOUR TWEETS
{passages_section}

## WHAT HAPPENED THIS MONTH (for context/timing only)
{events_by_date}

## HOW TO WRITE EACH TWEET

1. COPY the soldier's exact words. The memoir IS the tweet.
   - Passage: "The shells burst around us. I saw men falling everywhere."
   - Tweet: Robert Graves at the Somme: "The shells burst around us. I saw men falling everywhere."

2. Add minimal framing - who, where, that's it.
   - "Ernst Jünger, 19, in his first assault: '[quote from passage]'"
   - "Arthur Empey in the trenches: '[quote from passage]'"

3. Match passages to events by topic, not exact date. A trench warfare passage can go on any trench warfare day.

## EXAMPLES

GOOD (memoir IS the tweet):
- "Remarque: 'We have become wild beasts. We are filled with fear and rage.'"
- "Robert Graves at Loos: 'The sergeant said to me: It's murder, sir. Of course it's murder, you bloody fool, I agreed.'"
- "Arthur Empey on a night raid: 'I was trembling all over. My teeth were chattering.'"

BAD (summarizing events instead of quoting):
- "British forces attack German positions at Loos. Heavy casualties reported." (no memoir voice)
- "The Battle of the Somme begins with artillery bombardment." (event summary, not soldier experience)

## RULES
- 70% of tweets MUST be direct quotes from the passages above
- 280 characters max per tweet
- NO exclamation marks
- NO historian commentary ("this marked", "the war would never", "proving that")
- Present tense throughout
- Assign tweets to dates that make sense for the topic

## OUTPUT FORMAT
JSON object:
{{
  "days": {{
    "YYYY-MM-DD": {{
      "tweets": [
        {{"text": "Author at location: 'quote from passage'", "has_quote": true, "source_attribution": "Author, Book Title"}}
      ],
      "threads": [
        {{
          "event_title": "Event Name",
          "arc_id": "arc_id",
          "arc_title": "Arc Title",
          "tweets": [
            {{"text": "Tweet 1", "position": 1, "total": 2, "has_quote": true, "source_attribution": "Author, Book"}},
            {{"text": "Tweet 2", "position": 2, "total": 2, "has_quote": true, "source_attribution": "Author, Book"}}
          ]
        }}
      ],
      "summary": "Brief summary"
    }}
  }},
  "month_summary": "Key events"
}}

Generate tweets for {month}. The soldier memoirs ARE your content."""


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


def format_passages_for_prompt(passages_by_event: dict[str, list[PassageResult]], max_chars: int = 10000) -> str:
    """Format passages for prompt, making them easy to quote directly."""
    if not passages_by_event:
        return "No primary sources available for this month."

    lines = []
    total_chars = 0

    for event_title, passages in passages_by_event.items():
        if total_chars >= max_chars:
            break

        for p in passages[:3]:  # Max 3 passages per event
            # Format for easy quoting
            author_short = p.source_author.split()[-1] if p.source_author else "Unknown"  # Last name
            perspective = f", {p.source_perspective}" if p.source_perspective else ""

            entry = f"""
SOURCE: {p.source_author}, "{p.source_title}"{perspective}
QUOTE THIS: "{p.content[:500]}"
---"""
            if total_chars + len(entry) > max_chars:
                break

            lines.append(entry)
            total_chars += len(entry)

    return "\n".join(lines)


def format_vivid_passages(passages: list[PassageResult], max_chars: int = 12000) -> str:
    """Format vivid passages for passage-first generation."""
    if not passages:
        return "No passages available."

    lines = []
    total_chars = 0

    for i, p in enumerate(passages, 1):
        perspective = f" ({p.source_perspective})" if p.source_perspective else ""

        entry = f"""
PASSAGE {i}:
Author: {p.source_author}{perspective}
Book: {p.source_title}
Text: "{p.content}"
---"""
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


def generate_month_vivid(
    month: str,
    events_by_date: dict[str, list[dict]],
    vivid_passages: list[PassageResult],
    model: str = "claude-sonnet-4-20250514",
) -> MonthOutput:
    """Generate tweets using vivid passage-first approach.

    Instead of event-first generation, this uses the soldier memoirs
    as the primary content, with events only for timing context.

    Args:
        month: Month in YYYY-MM format
        events_by_date: Dict mapping date strings to list of events
        vivid_passages: List of vivid, tweetable passages
        model: Claude model to use

    Returns:
        MonthOutput with all generated content
    """
    client = get_client()

    prompt = MONTH_GENERATION_PROMPT.format(
        month=month,
        events_by_date=format_events_for_prompt(events_by_date),
        passages_section=format_vivid_passages(vivid_passages),
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

    # Convert to dataclasses (same as generate_month_tweets)
    days = {}
    for date_str, day_data in data.get("days", {}).items():
        tweets = []
        for t in day_data.get("tweets", []):
            tweets.append(GeneratedTweet(
                text=t.get("text", ""),
                position=1,
                total=1,
                has_quote=t.get("has_quote", False),
                source_attribution=t.get("source_attribution"),
            ))

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
