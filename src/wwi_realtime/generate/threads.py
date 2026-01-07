"""Multi-tweet thread generation for major events.

Generates connected tweet threads that tell a narrative story.
"""

import re
from dataclasses import dataclass

from wwi_realtime.generate.prompts import (
    EventContext,
    GenerationContext,
    PassageResult,
    build_thread_prompt,
    format_passage_for_prompt,
)


@dataclass
class Tweet:
    """A single tweet in a thread."""
    text: str
    position: int  # 1-indexed position in thread
    total: int  # Total tweets in thread
    event_id: str | None = None
    source_attribution: str | None = None
    has_quote: bool = False


@dataclass
class TweetThread:
    """A thread of connected tweets."""
    tweets: list[Tweet]
    event_title: str
    event_date: str
    arc_id: str | None = None


def parse_thread_response(response: str, event_id: str | None = None) -> list[Tweet]:
    """Parse Claude's response into a list of Tweet objects.

    Expects format like:
    TWEET 1/4: text here
    TWEET 2/4: more text
    etc.

    Args:
        response: Raw response from Claude
        event_id: Optional event ID to attach

    Returns:
        List of Tweet objects
    """
    tweets = []

    # Pattern: TWEET N/M: or TWEET N:
    pattern = r'TWEET\s+(\d+)(?:/(\d+))?:\s*(.+?)(?=TWEET\s+\d+|$)'
    matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)

    for match in matches:
        position = int(match[0])
        total = int(match[1]) if match[1] else len(matches)
        text = match[2].strip()

        # Clean up the text
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s+', ' ', text)

        # Check if it contains a quote (simple heuristic)
        has_quote = '"' in text or '"' in text or "'" in text

        # Extract attribution if present
        attribution = None
        attr_match = re.search(r'(?:As|wrote|said)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', text)
        if attr_match:
            attribution = attr_match.group(1)

        tweets.append(Tweet(
            text=text,
            position=position,
            total=total,
            event_id=event_id,
            source_attribution=attribution,
            has_quote=has_quote,
        ))

    return tweets


def validate_thread(tweets: list[Tweet]) -> list[str]:
    """Validate a tweet thread.

    Returns list of warnings/errors.
    """
    warnings = []

    if not tweets:
        warnings.append("Empty thread")
        return warnings

    # Check for correct numbering
    positions = [t.position for t in tweets]
    expected = list(range(1, len(tweets) + 1))
    if positions != expected:
        warnings.append(f"Position mismatch: got {positions}, expected {expected}")

    # Check for character limits
    for tweet in tweets:
        if len(tweet.text) > 280:
            warnings.append(f"Tweet {tweet.position} exceeds 280 chars ({len(tweet.text)})")

    # Check for at least one quote
    if not any(t.has_quote for t in tweets):
        warnings.append("Thread has no quoted material")

    return warnings


def estimate_thread_length(event: EventContext, passages: list[PassageResult]) -> int:
    """Estimate appropriate thread length based on event significance.

    Args:
        event: Event context
        passages: Available passages

    Returns:
        Recommended number of tweets (2-6)
    """
    # Base on available material
    quote_count = sum(1 for p in passages if p.has_direct_quote)

    if quote_count >= 4:
        return 5  # Lots of material
    elif quote_count >= 2:
        return 4  # Good material
    elif quote_count >= 1:
        return 3  # Some material
    else:
        return 2  # Limited material


def build_thread_context(
    event: EventContext,
    passages: list[PassageResult],
    thread_length: int | None = None,
) -> str:
    """Build the full prompt for thread generation.

    Args:
        event: Event context
        passages: Relevant passages
        thread_length: Target thread length (auto-estimated if None)

    Returns:
        Complete prompt string
    """
    if thread_length is None:
        thread_length = estimate_thread_length(event, passages)

    return build_thread_prompt(event, passages, thread_length)


def format_thread_for_display(thread: TweetThread) -> str:
    """Format a thread for display/review.

    Args:
        thread: TweetThread object

    Returns:
        Formatted string
    """
    lines = [
        f"=== {thread.event_title} ({thread.event_date}) ===",
        f"Arc: {thread.arc_id or 'None'}",
        f"Tweets: {len(thread.tweets)}",
        "",
    ]

    for tweet in thread.tweets:
        lines.append(f"[{tweet.position}/{tweet.total}] {tweet.text}")
        if tweet.source_attribution:
            lines.append(f"   └─ Source: {tweet.source_attribution}")
        lines.append(f"   └─ {len(tweet.text)} chars")
        lines.append("")

    return "\n".join(lines)


def merge_short_tweets(tweets: list[Tweet], min_length: int = 100) -> list[Tweet]:
    """Merge very short tweets together.

    Args:
        tweets: Original tweet list
        min_length: Minimum tweet length

    Returns:
        Merged tweet list
    """
    if len(tweets) <= 1:
        return tweets

    merged = []
    current = None

    for tweet in tweets:
        if current is None:
            current = tweet
        elif len(current.text) < min_length and len(current.text) + len(tweet.text) + 1 <= 280:
            # Merge
            current = Tweet(
                text=current.text + " " + tweet.text,
                position=current.position,
                total=current.total,
                event_id=current.event_id,
                source_attribution=current.source_attribution or tweet.source_attribution,
                has_quote=current.has_quote or tweet.has_quote,
            )
        else:
            merged.append(current)
            current = tweet

    if current:
        merged.append(current)

    # Renumber
    for i, tweet in enumerate(merged):
        tweet.position = i + 1
        tweet.total = len(merged)

    return merged


def create_thread_from_passages(
    event: EventContext,
    passages: list[PassageResult],
    thread_length: int = 4,
) -> TweetThread:
    """Create a sample thread directly from passages (without Claude).

    Useful for testing and demos.

    Args:
        event: Event context
        passages: Passages to use
        thread_length: Target length

    Returns:
        TweetThread with sample tweets
    """
    tweets = []

    # Tweet 1: Hook with event summary
    hook = f"{event.date.strftime('%B %d, %Y')}: {event.title}. {event.summary[:180]}..."
    tweets.append(Tweet(
        text=hook[:280],
        position=1,
        total=thread_length,
        event_id=None,
        has_quote=False,
    ))

    # Tweets 2-N: Quotes from passages
    quote_passages = [p for p in passages if p.has_direct_quote][:thread_length - 1]

    for i, passage in enumerate(quote_passages):
        # Extract a quote from the passage
        quote_match = re.search(r'"([^"]{20,150})"', passage.content)
        if quote_match:
            quote = quote_match.group(1)
            text = f'"{quote}" - {passage.source_author}, {passage.source_title}'
        else:
            text = f"From {passage.source_title}: {passage.content[:200]}..."

        tweets.append(Tweet(
            text=text[:280],
            position=i + 2,
            total=thread_length,
            event_id=None,
            source_attribution=passage.source_author,
            has_quote=True,
        ))

    # Fill remaining with context
    while len(tweets) < thread_length:
        pos = len(tweets) + 1
        if event.arc_title:
            text = f"This was part of {event.arc_title}. {event.arc_narrative or ''}..."
        else:
            text = "The war continued to reshape the world..."

        tweets.append(Tweet(
            text=text[:280],
            position=pos,
            total=thread_length,
            has_quote=False,
        ))

    return TweetThread(
        tweets=tweets,
        event_title=event.title,
        event_date=event.date.strftime('%Y-%m-%d'),
        arc_id=event.arc_id,
    )
