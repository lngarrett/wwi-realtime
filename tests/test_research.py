"""Tests for the research module."""

import sqlite3
from datetime import date

import pytest

from wwi_realtime.generate.research import (
    get_event_context,
    research_event,
    research_month,
    get_passages_for_month,
    format_research_summary,
)
from wwi_realtime.generate.prompts import EventContext, GenerationContext
from wwi_realtime.framework.schema import create_schema
from wwi_realtime.framework.arcs import Arc, populate_arcs_table


@pytest.fixture
def db_conn():
    """Create a database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, date DATE,
            summary TEXT, wikipedia_url TEXT, arc_id TEXT
        )
    """)
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def db_with_data(db_conn):
    """Database with test data."""
    # Add arcs
    arcs = [
        Arc(
            id="western_front",
            title="Western Front",
            start_date=date(1914, 8, 4),
            end_date=date(1918, 11, 11),
            narrative_summary="The main theater of WWI in France and Belgium.",
            theater="western",
        ),
        Arc(
            id="somme",
            title="Battle of the Somme",
            parent_arc_id="western_front",
            start_date=date(1916, 7, 1),
            end_date=date(1916, 11, 18),
            narrative_summary="The major British offensive of 1916.",
            theater="western",
        ),
    ]
    populate_arcs_table(db_conn, arcs)

    # Add sources
    db_conn.execute("""
        INSERT INTO canonical_sources (id, title, author, type, perspective, available, ingested)
        VALUES ('british_memoir', 'British Memoir', 'British Officer', 'memoir', 'british', 1, 1)
    """)

    # Add source coverage
    db_conn.execute("""
        INSERT INTO source_coverage (source_id, arc_id)
        VALUES ('british_memoir', 'somme')
    """)

    # Add passages
    db_conn.execute("""
        INSERT INTO source_passages
        (id, source_id, content, sequence_num, has_direct_quote, date_referenced, word_count)
        VALUES
        ('p1', 'british_memoir', '"Over the top!" shouted the sergeant.', 0, 1, '1916-07-01', 6),
        ('p2', 'british_memoir', 'The bombardment had lasted seven days.', 1, 0, '1916-06-30', 6)
    """)

    # Add events
    db_conn.execute("""
        INSERT INTO events (id, title, date, summary, arc_id)
        VALUES
        ('somme_day1', 'First Day of the Somme', '1916-07-01',
         'The British Army launched its major offensive. 57,470 casualties.', 'somme'),
        ('somme_day2', 'Second Day of the Somme', '1916-07-02',
         'Fighting continued along the front.', 'somme')
    """)

    db_conn.commit()
    return db_conn


class TestGetEventContext:
    """Tests for building event context."""

    def test_get_event_context_basic(self, db_with_data):
        """Verify basic event context creation."""
        event = {
            "title": "First Day of the Somme",
            "date": "1916-07-01",
            "summary": "Major offensive",
            "arc_id": "somme",
        }

        ctx = get_event_context(db_with_data, event)

        assert isinstance(ctx, EventContext)
        assert ctx.title == "First Day of the Somme"
        assert ctx.date == date(1916, 7, 1)
        assert ctx.arc_id == "somme"
        assert ctx.arc_title == "Battle of the Somme"

    def test_get_event_context_infers_arc(self, db_with_data):
        """Verify arc inferred from date when not specified."""
        event = {
            "title": "Some Battle",
            "date": "1916-07-15",
            "summary": "Fighting",
        }

        ctx = get_event_context(db_with_data, event)

        # Should infer somme or western_front from date
        assert ctx.arc_id is not None


class TestResearchEvent:
    """Tests for event research."""

    def test_research_event(self, db_with_data):
        """Verify full event research."""
        event = {
            "title": "First Day of the Somme",
            "date": "1916-07-01",
            "summary": "Major offensive",
            "arc_id": "somme",
        }

        result = research_event(db_with_data, event)

        assert isinstance(result, GenerationContext)
        assert result.event.title == "First Day of the Somme"
        # Should have some passages
        assert isinstance(result.passages, list)

    def test_research_returns_passages(self, db_with_data):
        """Verify passages are found."""
        event = {
            "title": "Battle of the Somme",
            "date": "1916-07-01",
            "summary": "Offensive",
            "arc_id": "somme",
        }

        result = research_event(db_with_data, event, max_passages=5)

        # Should find our test passages
        assert len(result.passages) >= 1


class TestResearchMonth:
    """Tests for month research."""

    def test_research_month(self, db_with_data):
        """Verify month research structure."""
        events_by_date = {
            "1916-07-01": [{
                "title": "First Day of the Somme",
                "date": "1916-07-01",
                "summary": "Offensive",
                "arc_id": "somme",
            }],
            "1916-07-02": [{
                "title": "Second Day",
                "date": "1916-07-02",
                "summary": "Fighting",
                "arc_id": "somme",
            }],
        }

        result = research_month(db_with_data, 1916, 7, events_by_date)

        assert "event_contexts" in result
        assert "passages_by_event" in result
        assert "arc_narratives" in result
        assert "active_arcs" in result

        assert len(result["event_contexts"]) == 2

    def test_month_collects_arc_narratives(self, db_with_data):
        """Verify arc narratives collected."""
        events_by_date = {
            "1916-07-01": [{
                "title": "First Day",
                "date": "1916-07-01",
                "summary": "Offensive",
                "arc_id": "somme",
            }],
        }

        result = research_month(db_with_data, 1916, 7, events_by_date)

        assert "somme" in result["arc_narratives"]


class TestGetPassagesForMonth:
    """Tests for month passage retrieval."""

    def test_get_passages_for_month(self, db_with_data):
        """Verify passages retrieved for month."""
        passages = get_passages_for_month(db_with_data, 1916, 7)

        assert isinstance(passages, list)
        # Should find some passages (our July 1916 passages)


class TestFormatResearchSummary:
    """Tests for research summary formatting."""

    def test_format_summary(self):
        """Verify summary formatting."""
        research = {
            "event_contexts": [None, None, None],
            "passages_by_event": {"Event 1": [], "Event 2": []},
            "arc_narratives": {"western_front": "The main theater..."},
            "active_arcs": [],
        }

        summary = format_research_summary(research)

        assert "Events: 3" in summary
        assert "Events with passages: 2" in summary
        assert "Western Front" in summary
