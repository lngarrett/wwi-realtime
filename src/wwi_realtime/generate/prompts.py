"""Prompt templates for WWI story generation.

Builds prompts that include arc context, source passages, and event information
for generating human-centered narrative tweets.
"""

from dataclasses import dataclass
from datetime import date

from wwi_realtime.sources.search import PassageResult


@dataclass
class EventContext:
    """Context for a single event."""
    title: str
    date: date
    summary: str
    wikipedia_url: str | None = None
    arc_id: str | None = None
    arc_title: str | None = None
    arc_narrative: str | None = None


@dataclass
class GenerationContext:
    """Full context for tweet generation."""
    event: EventContext
    passages: list[PassageResult]
    diverse_perspectives: dict[str, list[PassageResult]] | None = None
    previous_context: str | None = None
    newspaper_excerpts: list[str] | None = None


SYSTEM_PROMPT = """You are a historical narrator for a World War I real-time Twitter account.
Your job is to transform historical events into compelling, human-centered tweets.

Guidelines:
- Write as if reporting from 1914-1918, not looking back
- Include specific details: names, ages, places, numbers
- Use direct quotes from primary sources when provided
- Connect events to larger narrative arcs
- Balance different perspectives (British, German, French, etc.)
- Convey the human experience, not just facts
- Keep tweets concise but impactful (max 280 chars per tweet)
- Use present tense for immediacy

When quoting sources:
- Attribute quotes: 'As [Author] wrote: "..."'
- Include context for the quote
- Preserve the original voice and emotion"""


def format_passage_for_prompt(passage: PassageResult) -> str:
    """Format a single passage for inclusion in prompt."""
    attribution = f"{passage.source_title} by {passage.source_author}"
    if passage.source_perspective:
        attribution += f" ({passage.source_perspective} perspective)"

    quote_marker = " [contains direct quote]" if passage.has_direct_quote else ""

    return f"""---
Source: {attribution}{quote_marker}
{passage.date_approximate or 'Date unknown'}

{passage.content}
---"""


def format_perspectives_for_prompt(perspectives: dict[str, list[PassageResult]]) -> str:
    """Format diverse perspectives section."""
    if not perspectives:
        return ""

    sections = []
    for perspective, passages in perspectives.items():
        section = f"\n### {perspective.upper()} PERSPECTIVE:"
        for p in passages[:2]:  # Limit per perspective
            section += f"\n{format_passage_for_prompt(p)}"
        sections.append(section)

    return "\n".join(sections)


def build_event_prompt(context: GenerationContext) -> str:
    """Build a prompt for generating tweets about a single event.

    Args:
        context: GenerationContext with all relevant information

    Returns:
        Complete prompt string for Claude
    """
    event = context.event

    # Build arc context section
    arc_section = ""
    if event.arc_title:
        arc_section = f"""
## NARRATIVE ARC: {event.arc_title}
{event.arc_narrative or 'Part of the broader conflict.'}
"""

    # Build passages section
    passages_section = ""
    if context.passages:
        passages_section = "\n## PRIMARY SOURCE MATERIAL:\n"
        for passage in context.passages[:5]:  # Limit to 5 passages
            passages_section += format_passage_for_prompt(passage) + "\n"

    # Build perspectives section
    perspectives_section = ""
    if context.diverse_perspectives:
        perspectives_section = "\n## MULTIPLE PERSPECTIVES:\n"
        perspectives_section += format_perspectives_for_prompt(context.diverse_perspectives)

    # Build newspaper section
    newspaper_section = ""
    if context.newspaper_excerpts:
        newspaper_section = "\n## CONTEMPORARY NEWSPAPER COVERAGE:\n"
        for excerpt in context.newspaper_excerpts[:3]:
            newspaper_section += f"- {excerpt}\n"

    # Build previous context
    previous_section = ""
    if context.previous_context:
        previous_section = f"""
## PREVIOUS NARRATIVE CONTEXT:
{context.previous_context}
"""

    prompt = f"""# EVENT: {event.title}
Date: {event.date.strftime('%B %d, %Y')}

## HISTORICAL SUMMARY:
{event.summary}
{arc_section}
{previous_section}
{passages_section}
{perspectives_section}
{newspaper_section}

## YOUR TASK:
Generate 1-3 tweets about this event. Requirements:
1. At least one tweet should include a direct quote from the source material (if available)
2. Include specific human details (names, ages, locations)
3. Connect to the larger narrative arc
4. Write in present tense as if reporting live
5. Each tweet should be self-contained but they can form a thread

Format your response as:
TWEET 1: [your tweet here]
TWEET 2: [your tweet here if applicable]
TWEET 3: [your tweet here if applicable]
"""

    return prompt


def build_month_prompt(
    year: int,
    month: int,
    events: list[EventContext],
    all_passages: dict[str, list[PassageResult]],
    arc_narratives: dict[str, str],
    previous_month_summary: str | None = None,
) -> str:
    """Build a prompt for generating a full month of tweets.

    Args:
        year: Year
        month: Month (1-12)
        events: List of events for the month
        all_passages: Dict mapping event titles to relevant passages
        arc_narratives: Dict mapping arc_id to narrative summary
        previous_month_summary: Summary of previous month's events

    Returns:
        Complete prompt string for Claude
    """
    month_name = date(year, month, 1).strftime('%B %Y')

    # Build events list
    events_section = "## EVENTS THIS MONTH:\n"
    for event in events:
        events_section += f"\n### {event.date.strftime('%B %d')}: {event.title}\n"
        events_section += f"{event.summary[:500]}\n"
        if event.arc_title:
            events_section += f"Arc: {event.arc_title}\n"

    # Build arc context
    arcs_section = "## ACTIVE NARRATIVE ARCS:\n"
    for arc_id, narrative in arc_narratives.items():
        arcs_section += f"\n### {arc_id.replace('_', ' ').title()}:\n{narrative[:300]}\n"

    # Build passages section
    passages_section = "\n## KEY PRIMARY SOURCE PASSAGES:\n"
    for event_title, passages in all_passages.items():
        if passages:
            passages_section += f"\n### For {event_title}:\n"
            for p in passages[:3]:
                passages_section += format_passage_for_prompt(p) + "\n"

    # Previous month context
    previous_section = ""
    if previous_month_summary:
        previous_section = f"""
## PREVIOUS MONTH SUMMARY:
{previous_month_summary}
"""

    prompt = f"""# GENERATE TWEETS FOR {month_name.upper()}

You are generating historical tweets for the entire month. The tweets should:
- Cover all major events
- Form a coherent narrative thread across the month
- Include direct quotes from sources where available
- Balance perspectives (don't only show one side)
- Build tension and drama appropriately
- Reference the larger narrative arcs

{previous_section}

{arcs_section}

{events_section}

{passages_section}

## OUTPUT FORMAT:
For each day with content, output:

DATE: [Month Day, Year]
TWEET 1: [tweet text]
TWEET 2: [optional second tweet]
---

Generate tweets for the significant events of this month. Include at least one tweet
with a direct quote from the primary sources. Maintain narrative continuity throughout
the month.
"""

    return prompt


def build_thread_prompt(
    event: EventContext,
    passages: list[PassageResult],
    thread_length: int = 4,
) -> str:
    """Build a prompt for generating a multi-tweet thread about a major event.

    Args:
        event: Event context
        passages: Relevant passages
        thread_length: Target number of tweets in thread

    Returns:
        Prompt string for Claude
    """
    passages_text = ""
    for p in passages[:6]:
        passages_text += format_passage_for_prompt(p) + "\n"

    prompt = f"""# GENERATE TWEET THREAD: {event.title}
Date: {event.date.strftime('%B %d, %Y')}

## EVENT SUMMARY:
{event.summary}

{f'## NARRATIVE ARC: {event.arc_title}' if event.arc_title else ''}
{event.arc_narrative or ''}

## PRIMARY SOURCES:
{passages_text}

## YOUR TASK:
Generate a {thread_length}-tweet thread about this major event.

Requirements:
1. First tweet should hook the reader with the most dramatic aspect
2. Include at least 2 direct quotes from the sources with attribution
3. Show multiple perspectives if sources allow
4. Build narrative tension across the thread
5. Final tweet should connect to the broader war narrative
6. Each tweet max 280 characters

Format:
TWEET 1/4: [hook tweet]
TWEET 2/4: [development]
TWEET 3/4: [quote/detail]
TWEET 4/4: [conclusion/connection to arc]
"""

    return prompt
