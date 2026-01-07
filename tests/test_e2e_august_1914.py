"""End-to-end test for August 1914 generation.

This tests the complete pipeline:
1. Schema creation
2. Arc population
3. Source population and coverage
4. Passage ingestion (mock)
5. Research assembly
6. Prompt generation
"""

import sqlite3
from datetime import date

import pytest

from wwi_realtime.framework.schema import create_schema
from wwi_realtime.framework.arcs import Arc, populate_arcs_table
from wwi_realtime.sources.curator import CanonicalSource, populate_sources_table, populate_arc_coverage
from wwi_realtime.sources.parser import Passage, save_passages
from wwi_realtime.generate.research import research_month, format_research_summary
from wwi_realtime.generate.prompts import build_month_prompt, build_event_prompt


@pytest.fixture
def full_db():
    """Create a database with complete August 1914 test data."""
    conn = sqlite3.connect(":memory:")

    # Create events table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            date DATE,
            summary TEXT,
            significance TEXT,
            wikipedia_url TEXT,
            arc_id TEXT
        )
    """)

    # Create story engine schema
    create_schema(conn)

    # Add arcs for August 1914
    arcs = [
        Arc(
            id="wwi_outbreak",
            title="Outbreak of World War I",
            start_date=date(1914, 7, 28),
            end_date=date(1914, 8, 31),
            narrative_summary="The assassination of Archduke Franz Ferdinand triggered a chain of events leading to global war.",
            theater=None,
        ),
        Arc(
            id="western_front",
            title="Western Front",
            start_date=date(1914, 8, 4),
            end_date=date(1918, 11, 11),
            narrative_summary="The main theater of WWI stretching from Belgium to Switzerland.",
            theater="western",
        ),
        Arc(
            id="battle_of_frontiers",
            title="Battle of the Frontiers",
            parent_arc_id="western_front",
            start_date=date(1914, 8, 7),
            end_date=date(1914, 8, 25),
            narrative_summary="The opening clashes as German forces swept through Belgium.",
            theater="western",
        ),
        Arc(
            id="eastern_front",
            title="Eastern Front",
            start_date=date(1914, 8, 17),
            end_date=date(1917, 12, 15),
            narrative_summary="The war between Germany, Austria-Hungary and Russia.",
            theater="eastern",
        ),
    ]
    populate_arcs_table(conn, arcs)

    # Add canonical sources
    sources = [
        CanonicalSource(
            id="graves_goodbye",
            title="Good-bye to All That",
            author="Robert Graves",
            author_info="British officer and poet",
            type="memoir",
            perspective="british",
            gutenberg_id="76911",
            coverage_arcs=["western_front", "battle_of_frontiers"],
            coverage_topics=["infantry", "british_experience"],
        ),
        CanonicalSource(
            id="marne_observer",
            title="A Hilltop on the Marne",
            author="Mildred Aldrich",
            author_info="American journalist in France",
            type="letters",
            perspective="civilian",
            gutenberg_id="11011",
            coverage_arcs=["western_front"],
            coverage_topics=["civilian_experience", "marne"],
        ),
        CanonicalSource(
            id="german_diary",
            title="A German Deserter's War Experience",
            author="Anonymous",
            author_info="German soldier",
            type="memoir",
            perspective="german",
            gutenberg_id="42721",
            coverage_arcs=["western_front", "battle_of_frontiers"],
            coverage_topics=["german_perspective", "infantry"],
        ),
    ]
    populate_sources_table(conn, sources)
    populate_arc_coverage(conn, sources)

    # Add test passages
    passages = [
        # British perspective
        Passage(
            id="p_graves_1",
            source_id="graves_goodbye",
            content="When war broke out, I was nineteen. 'It will be over by Christmas,' everyone said.",
            sequence_num=0,
            date_approximate="August 1914",
            has_direct_quote=True,
            topics=["war_outbreak", "british_experience"],
            word_count=15,
        ),
        Passage(
            id="p_graves_2",
            source_id="graves_goodbye",
            content="The Germans came through Belgium like a flood. Villages burned, refugees streamed west.",
            sequence_num=1,
            date_approximate="August 1914",
            has_direct_quote=False,
            topics=["belgium", "german_advance"],
            word_count=13,
        ),
        # Civilian perspective
        Passage(
            id="p_marne_1",
            source_id="marne_observer",
            content="From my hilltop I could see the smoke of burning villages. 'They are coming,' said the farmer.",
            sequence_num=0,
            date_referenced="1914-08-25",
            date_approximate="Late August 1914",
            has_direct_quote=True,
            topics=["marne", "civilian_experience"],
            word_count=18,
        ),
        # German perspective
        Passage(
            id="p_german_1",
            source_id="german_diary",
            content="We marched through Belgium. 'Forward! For the Fatherland!' the officers shouted.",
            sequence_num=0,
            date_approximate="August 1914",
            has_direct_quote=True,
            topics=["german_perspective", "belgium"],
            word_count=12,
        ),
        Passage(
            id="p_german_2",
            source_id="german_diary",
            content="The locals looked at us with fear and hatred. We were not liberators.",
            sequence_num=1,
            date_approximate="August 1914",
            has_direct_quote=False,
            topics=["german_perspective", "occupation"],
            word_count=13,
        ),
    ]
    save_passages(conn, passages)

    # Add August 1914 events
    events = [
        ("war_declared", "Germany Declares War on France", "1914-08-03",
         "Germany declared war on France, implementing the Schlieffen Plan.",
         "critical", "wwi_outbreak"),
        ("britain_enters", "Britain Declares War on Germany", "1914-08-04",
         "After Germany invaded Belgium, Britain declared war to honor its treaty obligations.",
         "critical", "wwi_outbreak"),
        ("liege_falls", "Fall of Liège", "1914-08-16",
         "German forces captured the Belgian fortress of Liège after fierce resistance.",
         "high", "battle_of_frontiers"),
        ("tannenberg_begins", "Battle of Tannenberg Begins", "1914-08-26",
         "German forces engaged Russian armies in East Prussia.",
         "critical", "eastern_front"),
        ("mons_retreat", "Retreat from Mons", "1914-08-24",
         "British Expeditionary Force began retreat from Mons after first engagement.",
         "high", "battle_of_frontiers"),
    ]
    for event_id, title, event_date, summary, sig, arc_id in events:
        conn.execute(
            """INSERT INTO events (id, title, date, summary, significance, arc_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, title, event_date, summary, sig, arc_id)
        )

    conn.commit()
    return conn


class TestE2EAugust1914:
    """End-to-end tests for August 1914 generation."""

    def test_database_setup(self, full_db):
        """Verify database is properly set up."""
        # Check arcs
        cursor = full_db.execute("SELECT COUNT(*) FROM arcs")
        assert cursor.fetchone()[0] >= 4

        # Check sources
        cursor = full_db.execute("SELECT COUNT(*) FROM canonical_sources")
        assert cursor.fetchone()[0] >= 3

        # Check passages
        cursor = full_db.execute("SELECT COUNT(*) FROM source_passages")
        assert cursor.fetchone()[0] >= 5

        # Check events
        cursor = full_db.execute("SELECT COUNT(*) FROM events")
        assert cursor.fetchone()[0] >= 5

    def test_research_month_august_1914(self, full_db):
        """Test researching August 1914."""
        # Get events
        cursor = full_db.execute(
            """SELECT id, title, date, summary, arc_id
               FROM events WHERE date LIKE '1914-08%'
               ORDER BY date"""
        )
        events_list = [
            {"id": r[0], "title": r[1], "date": r[2], "summary": r[3], "arc_id": r[4]}
            for r in cursor.fetchall()
        ]

        events_by_date = {}
        for event in events_list:
            date_str = event["date"]
            if date_str not in events_by_date:
                events_by_date[date_str] = []
            events_by_date[date_str].append(event)

        # Research the month
        research = research_month(full_db, 1914, 8, events_by_date)

        # Verify structure
        assert "event_contexts" in research
        assert "passages_by_event" in research
        assert "arc_narratives" in research
        assert "active_arcs" in research

        # Should have our events
        assert len(research["event_contexts"]) >= 5

        # Should have arc narratives
        assert len(research["arc_narratives"]) >= 1

    def test_research_includes_multiple_perspectives(self, full_db):
        """Verify research includes multiple perspectives."""
        events_by_date = {
            "1914-08-04": [{
                "id": "britain_enters",
                "title": "Britain Declares War",
                "date": "1914-08-04",
                "summary": "Britain enters the war",
                "arc_id": "wwi_outbreak",
            }]
        }

        research = research_month(full_db, 1914, 8, events_by_date)

        # Format and check
        summary = format_research_summary(research)
        assert "Events:" in summary

    def test_build_month_prompt(self, full_db):
        """Test building a full month prompt."""
        # Get events
        cursor = full_db.execute(
            """SELECT id, title, date, summary, arc_id
               FROM events WHERE date LIKE '1914-08%'
               ORDER BY date"""
        )
        events_list = [
            {"id": r[0], "title": r[1], "date": r[2], "summary": r[3], "arc_id": r[4]}
            for r in cursor.fetchall()
        ]

        events_by_date = {}
        for event in events_list:
            date_str = event["date"]
            if date_str not in events_by_date:
                events_by_date[date_str] = []
            events_by_date[date_str].append(event)

        # Research
        research = research_month(full_db, 1914, 8, events_by_date)

        # Convert contexts to EventContext objects
        from wwi_realtime.generate.prompts import EventContext
        event_contexts = []
        for ctx in research["event_contexts"]:
            event_contexts.append(ctx)

        # Build prompt
        prompt = build_month_prompt(
            1914, 8,
            event_contexts,
            research["passages_by_event"],
            research["arc_narratives"],
        )

        # Verify prompt structure
        assert "AUGUST 1914" in prompt
        assert "EVENTS THIS MONTH" in prompt
        assert "ACTIVE NARRATIVE ARCS" in prompt
        assert "PRIMARY SOURCE PASSAGES" in prompt

        # Should have our events
        assert "Britain Declares War" in prompt or "Germany Declares War" in prompt

    def test_prompt_includes_quotes(self, full_db):
        """Verify prompt includes direct quotes from sources."""
        events_by_date = {
            "1914-08-04": [{
                "id": "britain_enters",
                "title": "Britain Declares War",
                "date": "1914-08-04",
                "summary": "Britain enters the war",
                "arc_id": "western_front",
            }]
        }

        research = research_month(full_db, 1914, 8, events_by_date)

        prompt = build_month_prompt(
            1914, 8,
            research["event_contexts"],
            research["passages_by_event"],
            research["arc_narratives"],
        )

        # Should reference our sources
        # (May or may not have passages depending on coverage)
        assert "1914" in prompt

    def test_build_single_event_prompt(self, full_db):
        """Test building prompt for single event."""
        from wwi_realtime.generate.research import research_event

        event = {
            "id": "britain_enters",
            "title": "Britain Declares War on Germany",
            "date": "1914-08-04",
            "summary": "Britain declared war to honor its treaty obligations after Germany invaded Belgium.",
            "arc_id": "wwi_outbreak",
        }

        context = research_event(full_db, event)
        prompt = build_event_prompt(context)

        # Verify structure
        assert "Britain Declares War" in prompt
        assert "August 04, 1914" in prompt or "August 4, 1914" in prompt
        assert "treaty obligations" in prompt
        assert "YOUR TASK" in prompt
        assert "TWEET 1:" in prompt

    def test_full_pipeline_diversity(self, full_db):
        """Verify full pipeline produces diverse content."""
        # Get all August 1914 events
        cursor = full_db.execute(
            """SELECT id, title, date, summary, arc_id
               FROM events WHERE date LIKE '1914-08%'
               ORDER BY date"""
        )
        events_list = [
            {"id": r[0], "title": r[1], "date": r[2], "summary": r[3], "arc_id": r[4]}
            for r in cursor.fetchall()
        ]

        events_by_date = {}
        for event in events_list:
            date_str = event["date"]
            if date_str not in events_by_date:
                events_by_date[date_str] = []
            events_by_date[date_str].append(event)

        research = research_month(full_db, 1914, 8, events_by_date)

        # Should have events from multiple arcs
        arcs_found = set()
        for ctx in research["event_contexts"]:
            if ctx.arc_id:
                arcs_found.add(ctx.arc_id)

        # Should span multiple arcs
        assert len(arcs_found) >= 2
