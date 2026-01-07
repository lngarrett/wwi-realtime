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


MONTH_GENERATION_PROMPT = """Generate tweets for {month} during World War I (1914-1918). You are a wire service correspondent reporting events as they happen.

CRITICAL: This is WWI, not WWII. Russia is the Russian Empire (not Soviet). Germany is the German Empire/Kaiser's Germany.

## STYLE GUIDE - FOLLOW EXACTLY:

GOOD tweet examples (copy this style):
- "French Corporal Jules-André Peugeot, 21, shot by German patrol near Joncherey. First French soldier killed in the war."
- "Ernst Jünger, 19, in first assault: 'I was soaked in sweat and quite out of breath. The moment I had longed for was here.'"
- "Private Sidney Godley mans machine gun alone at Nimy Bridge. Wounded in head and back, captured only when ammunition runs out."
- "32 German cavalrymen killed, 150 Russian dead, 600 prisoners taken as confused infantry retreat."

BAD tweets (NEVER write like this):
- "Spectacular cavalry charge at Lagarde!" (no exclamation marks)
- "The cult of the offensive proves deadly." (historian commentary - you're a reporter, not a historian)
- "What may be history's last great mounted assault." (editorializing, you don't know the future)
- "The Empire strikes back in Africa." (modern reference, editorializing)
- "Will Belgian forts hold? Only time will tell." (rhetorical questions)
- "This marks a turning point in the war." (historian hindsight)

## RULES:
1. NAME INDIVIDUALS: "Private Ernst Jünger, 19", "Nurse Edith Cavell", "Corporal Adolf Hitler"
2. QUOTE THE PRIMARY SOURCES PROVIDED BELOW - copy their exact words in quotation marks
3. NO exclamation marks. NO editorializing. NO historian commentary. You report facts only.
4. NO rhetorical questions. NO "will this...?" or "what does this mean?"
5. NO phrases like "last great X", "the war spreads", "marking the end of", "ushering in a new era"
6. Specific numbers: "57,000 casualties", "19 killed, 43 wounded"
7. Present tense, active voice. Report as if happening now.
8. For each event, choose EITHER a single tweet OR a thread - NEVER both. Major events get threads, minor events get single tweets.
9. 280 characters max per tweet
10. Use quotes from the PRIMARY SOURCES section below - these are memoirs from actual soldiers

## PREVIOUS MONTH:
{previous_month_summary}

## EVENTS BY DATE:
{events_by_date}

## PRIMARY SOURCES - USE THESE QUOTES:
{passages_section}

When you see a passage above, copy the most vivid part EXACTLY and attribute it:
- Ernst Jünger writes: "The trench was a mess of blood and torn equipment..."
- From a letter home: "We have not slept in three days. The shelling never stops."
- Remarque: "We have become wild beasts."

## OUTPUT FORMAT:
JSON object with this structure:
{{
  "days": {{
    "YYYY-MM-DD": {{
      "tweets": [
        {{"text": "Tweet text here", "has_quote": true/false, "source_attribution": "Author, Source" or null}}
      ],
      "threads": [
        {{
          "event_title": "Event Name",
          "arc_id": "arc_id",
          "arc_title": "Arc Title",
          "tweets": [
            {{"text": "First tweet", "position": 1, "total": 3, "has_quote": false, "source_attribution": null}},
            {{"text": "Quote tweet", "position": 2, "total": 3, "has_quote": true, "source_attribution": "Author, Book"}}
          ]
        }}
      ],
      "summary": "Brief factual summary"
    }}
  }},
  "month_summary": "Key events this month"
}}

Generate coverage for {month}. Focus on individuals. Quote the sources. No editorializing."""


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
