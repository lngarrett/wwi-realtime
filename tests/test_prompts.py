"""Tests for prompt templates."""

from datetime import date

import pytest

from wwi_realtime.generate.prompts import (
    EventContext,
    GenerationContext,
    PassageResult,
    SYSTEM_PROMPT,
    format_passage_for_prompt,
    format_perspectives_for_prompt,
    build_event_prompt,
    build_month_prompt,
    build_thread_prompt,
)


@pytest.fixture
def sample_passage():
    """Create a sample passage."""
    return PassageResult(
        passage_id="p1",
        source_id="over_the_top",
        content="The shells came over like rain. We crouched in our trenches waiting.",
        source_title="Over the Top",
        source_author="Arthur Guy Empey",
        source_type="memoir",
        source_perspective="american",
        has_direct_quote=False,
        date_approximate="July 1916",
        word_count=12,
    )


@pytest.fixture
def sample_passage_with_quote():
    """Create a passage with a direct quote."""
    return PassageResult(
        passage_id="p2",
        source_id="over_the_top",
        content='"Over the top, lads!" shouted the sergeant, and we climbed into hell.',
        source_title="Over the Top",
        source_author="Arthur Guy Empey",
        source_type="memoir",
        source_perspective="american",
        has_direct_quote=True,
        date_approximate="July 1916",
        word_count=14,
    )


@pytest.fixture
def sample_event():
    """Create a sample event context."""
    return EventContext(
        title="First Day of the Battle of the Somme",
        date=date(1916, 7, 1),
        summary="The British Army launched its major offensive. 57,470 casualties on the first day alone, including 19,240 dead - the worst day in British military history.",
        wikipedia_url="https://en.wikipedia.org/wiki/First_day_on_the_Somme",
        arc_id="somme",
        arc_title="Battle of the Somme",
        arc_narrative="The 'Big Push' intended to break German lines and relieve pressure on Verdun.",
    )


class TestSystemPrompt:
    """Tests for system prompt."""

    def test_system_prompt_exists(self):
        """Verify system prompt is defined."""
        assert len(SYSTEM_PROMPT) > 100

    def test_system_prompt_content(self):
        """Verify system prompt has key guidance."""
        assert "World War I" in SYSTEM_PROMPT
        assert "quote" in SYSTEM_PROMPT.lower()
        assert "human" in SYSTEM_PROMPT.lower()


class TestFormatPassage:
    """Tests for passage formatting."""

    def test_format_basic_passage(self, sample_passage):
        """Verify basic passage formatting."""
        formatted = format_passage_for_prompt(sample_passage)

        assert "Over the Top" in formatted
        assert "Arthur Guy Empey" in formatted
        assert "american perspective" in formatted
        assert "July 1916" in formatted
        assert "shells came over" in formatted

    def test_format_passage_with_quote(self, sample_passage_with_quote):
        """Verify quote marker included."""
        formatted = format_passage_for_prompt(sample_passage_with_quote)

        assert "[contains direct quote]" in formatted

    def test_format_passage_without_quote(self, sample_passage):
        """Verify no quote marker for non-quoted passage."""
        formatted = format_passage_for_prompt(sample_passage)

        assert "[contains direct quote]" not in formatted


class TestFormatPerspectives:
    """Tests for perspectives formatting."""

    def test_format_multiple_perspectives(self, sample_passage, sample_passage_with_quote):
        """Verify multiple perspectives formatted."""
        perspectives = {
            "british": [sample_passage],
            "german": [sample_passage_with_quote],
        }

        formatted = format_perspectives_for_prompt(perspectives)

        assert "BRITISH PERSPECTIVE" in formatted
        assert "GERMAN PERSPECTIVE" in formatted

    def test_empty_perspectives(self):
        """Verify empty dict handled."""
        formatted = format_perspectives_for_prompt({})
        assert formatted == ""


class TestBuildEventPrompt:
    """Tests for event prompt building."""

    def test_build_event_prompt(self, sample_event, sample_passage):
        """Verify event prompt structure."""
        context = GenerationContext(
            event=sample_event,
            passages=[sample_passage],
        )

        prompt = build_event_prompt(context)

        # Check key sections present
        assert "First Day of the Battle of the Somme" in prompt
        assert "July 01, 1916" in prompt or "July 1, 1916" in prompt
        assert "57,470 casualties" in prompt
        assert "Battle of the Somme" in prompt
        assert "PRIMARY SOURCE MATERIAL" in prompt

    def test_prompt_includes_arc_context(self, sample_event, sample_passage):
        """Verify arc context included."""
        context = GenerationContext(
            event=sample_event,
            passages=[sample_passage],
        )

        prompt = build_event_prompt(context)

        assert "NARRATIVE ARC" in prompt
        assert "Big Push" in prompt

    def test_prompt_includes_task(self, sample_event):
        """Verify task instructions included."""
        context = GenerationContext(
            event=sample_event,
            passages=[],
        )

        prompt = build_event_prompt(context)

        assert "YOUR TASK" in prompt
        assert "TWEET 1:" in prompt

    def test_prompt_with_perspectives(self, sample_event, sample_passage, sample_passage_with_quote):
        """Verify perspectives section included."""
        context = GenerationContext(
            event=sample_event,
            passages=[sample_passage],
            diverse_perspectives={
                "british": [sample_passage],
                "american": [sample_passage_with_quote],
            },
        )

        prompt = build_event_prompt(context)

        assert "MULTIPLE PERSPECTIVES" in prompt


class TestBuildMonthPrompt:
    """Tests for month prompt building."""

    def test_build_month_prompt(self, sample_event, sample_passage):
        """Verify month prompt structure."""
        events = [sample_event]
        passages = {"First Day of the Battle of the Somme": [sample_passage]}
        arcs = {"somme": "The Battle of the Somme was the major British offensive of 1916."}

        prompt = build_month_prompt(1916, 7, events, passages, arcs)

        assert "JULY 1916" in prompt
        assert "EVENTS THIS MONTH" in prompt
        assert "ACTIVE NARRATIVE ARCS" in prompt
        assert "PRIMARY SOURCE PASSAGES" in prompt

    def test_month_prompt_with_previous(self, sample_event, sample_passage):
        """Verify previous month context included."""
        prompt = build_month_prompt(
            1916, 7,
            [sample_event],
            {},
            {},
            previous_month_summary="The Battle of Verdun continued..."
        )

        assert "PREVIOUS MONTH SUMMARY" in prompt
        assert "Verdun" in prompt


class TestBuildThreadPrompt:
    """Tests for thread prompt building."""

    def test_build_thread_prompt(self, sample_event, sample_passage, sample_passage_with_quote):
        """Verify thread prompt structure."""
        prompt = build_thread_prompt(
            sample_event,
            [sample_passage, sample_passage_with_quote],
            thread_length=4,
        )

        assert "TWEET THREAD" in prompt
        assert "4-tweet thread" in prompt
        assert "TWEET 1/4" in prompt
        assert "TWEET 4/4" in prompt

    def test_thread_includes_sources(self, sample_event, sample_passage):
        """Verify sources included in thread prompt."""
        prompt = build_thread_prompt(sample_event, [sample_passage])

        assert "PRIMARY SOURCES" in prompt
        assert "Over the Top" in prompt
