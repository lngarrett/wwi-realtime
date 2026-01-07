"""Tests for the arc hierarchy management."""

import sqlite3
import tempfile
from datetime import date

import pytest

from wwi_realtime.framework.arcs import (
    Arc,
    WWI_THEATERS,
    WWI_CAMPAIGNS,
    build_arc_hierarchy,
    populate_arcs_table,
    get_arc,
    get_child_arcs,
    get_arcs_for_date,
    get_all_arcs,
)
from wwi_realtime.framework.schema import create_schema


@pytest.fixture
def db_conn():
    """Create a temporary database with schema."""
    conn = sqlite3.connect(":memory:")
    # Create events table first (needed by schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            date DATE,
            wikipedia_url TEXT
        )
    """)
    create_schema(conn)
    yield conn
    conn.close()


class TestArcDataclass:
    """Tests for the Arc dataclass."""

    def test_create_arc(self):
        """Verify arc dataclass works."""
        arc = Arc(
            id="test_arc",
            title="Test Arc",
            parent_arc_id=None,
            start_date=date(1914, 8, 1),
            end_date=date(1914, 9, 30),
            wikipedia_url="https://en.wikipedia.org/wiki/Test",
            narrative_summary="Test summary",
            theater="western",
        )
        assert arc.id == "test_arc"
        assert arc.title == "Test Arc"
        assert arc.start_date == date(1914, 8, 1)
        assert arc.child_arcs == []

    def test_arc_with_children(self):
        """Verify arc can have child arcs."""
        parent = Arc(id="parent", title="Parent Arc")
        child1 = Arc(id="child1", title="Child 1", parent_arc_id="parent")
        child2 = Arc(id="child2", title="Child 2", parent_arc_id="parent")

        parent.child_arcs = [child1, child2]

        assert len(parent.child_arcs) == 2
        assert parent.child_arcs[0].parent_arc_id == "parent"


class TestArcHierarchyDefinitions:
    """Tests for the predefined arc hierarchy."""

    def test_theaters_defined(self):
        """Verify all major theaters are defined."""
        assert "western_front" in WWI_THEATERS
        assert "eastern_front" in WWI_THEATERS
        assert "gallipoli" in WWI_THEATERS
        assert "naval_warfare" in WWI_THEATERS

    def test_theater_has_required_fields(self):
        """Verify each theater has required fields."""
        for theater_id, info in WWI_THEATERS.items():
            assert "title" in info, f"{theater_id} missing title"
            assert "wikipedia_url" in info, f"{theater_id} missing wikipedia_url"

    def test_campaigns_have_parents(self):
        """Verify campaigns reference valid parent arcs."""
        valid_parents = set(WWI_THEATERS.keys()) | set(WWI_CAMPAIGNS.keys())

        for campaign_id, info in WWI_CAMPAIGNS.items():
            if "parent" in info:
                assert info["parent"] in valid_parents, \
                    f"{campaign_id} has invalid parent: {info['parent']}"

    def test_major_campaigns_defined(self):
        """Verify key campaigns are defined."""
        assert "verdun" in WWI_CAMPAIGNS
        assert "somme" in WWI_CAMPAIGNS
        assert "tannenberg" in WWI_CAMPAIGNS
        assert "jutland" in WWI_CAMPAIGNS


class TestBuildArcHierarchy:
    """Tests for building arc hierarchy from Wikipedia."""

    @pytest.mark.slow
    def test_build_hierarchy_returns_arcs(self):
        """Verify build_arc_hierarchy returns arc objects."""
        arcs = build_arc_hierarchy()

        assert len(arcs) > 0
        assert all(isinstance(arc, Arc) for arc in arcs)

    @pytest.mark.slow
    def test_hierarchy_has_top_level_theaters(self):
        """Verify top-level arcs are theaters (no parent)."""
        arcs = build_arc_hierarchy()

        # All top-level should have no parent
        for arc in arcs:
            assert arc.parent_arc_id is None

        # Should include major theaters
        arc_ids = {arc.id for arc in arcs}
        assert "western_front" in arc_ids
        assert "eastern_front" in arc_ids

    @pytest.mark.slow
    def test_hierarchy_has_nested_campaigns(self):
        """Verify campaigns are nested under theaters."""
        arcs = build_arc_hierarchy()

        # Find western front
        western = next((a for a in arcs if a.id == "western_front"), None)
        assert western is not None

        # Should have child arcs
        assert len(western.child_arcs) > 0

        # Children should include major battles
        child_ids = {c.id for c in western.child_arcs}
        # At least some of: verdun, somme, passchendaele, etc.
        assert len(child_ids & {"verdun", "somme", "passchendaele", "hundred_days"}) >= 1


class TestPopulateArcsTable:
    """Tests for populating arcs in database."""

    def test_populate_from_predefined(self, db_conn):
        """Verify we can populate arcs without fetching Wikipedia."""
        # Create minimal arcs manually
        arcs = [
            Arc(
                id="western_front",
                title="Western Front",
                wikipedia_url="https://en.wikipedia.org/wiki/Western_Front_(World_War_I)",
                theater="western",
                child_arcs=[
                    Arc(
                        id="somme",
                        title="Battle of the Somme",
                        parent_arc_id="western_front",
                        start_date=date(1916, 7, 1),
                        end_date=date(1916, 11, 18),
                        theater="western",
                    )
                ],
            )
        ]

        count = populate_arcs_table(db_conn, arcs)

        assert count == 2  # western_front + somme

    def test_arc_foreign_key(self, db_conn):
        """Verify parent_arc_id references work."""
        arcs = [
            Arc(
                id="parent",
                title="Parent Arc",
                child_arcs=[
                    Arc(
                        id="child",
                        title="Child Arc",
                        parent_arc_id="parent",
                    )
                ],
            )
        ]

        populate_arcs_table(db_conn, arcs)

        # Query child and verify parent reference
        child = get_arc(db_conn, "child")
        assert child is not None
        assert child["parent_arc_id"] == "parent"


class TestArcQueries:
    """Tests for querying arcs from database."""

    @pytest.fixture
    def populated_db(self, db_conn):
        """Database with sample arcs."""
        arcs = [
            Arc(
                id="western_front",
                title="Western Front",
                start_date=date(1914, 8, 4),
                end_date=date(1918, 11, 11),
                theater="western",
                child_arcs=[
                    Arc(
                        id="somme",
                        title="Battle of the Somme",
                        parent_arc_id="western_front",
                        start_date=date(1916, 7, 1),
                        end_date=date(1916, 11, 18),
                        theater="western",
                    ),
                    Arc(
                        id="verdun",
                        title="Battle of Verdun",
                        parent_arc_id="western_front",
                        start_date=date(1916, 2, 21),
                        end_date=date(1916, 12, 18),
                        theater="western",
                    ),
                ],
            ),
            Arc(
                id="eastern_front",
                title="Eastern Front",
                start_date=date(1914, 8, 17),
                end_date=date(1917, 12, 15),
                theater="eastern",
            ),
        ]
        populate_arcs_table(db_conn, arcs)
        return db_conn

    def test_get_arc(self, populated_db):
        """Verify single arc retrieval."""
        arc = get_arc(populated_db, "western_front")
        assert arc is not None
        assert arc["title"] == "Western Front"
        assert arc["theater"] == "western"

    def test_get_arc_not_found(self, populated_db):
        """Verify None returned for nonexistent arc."""
        arc = get_arc(populated_db, "nonexistent")
        assert arc is None

    def test_get_child_arcs(self, populated_db):
        """Verify child arc retrieval."""
        children = get_child_arcs(populated_db, "western_front")
        assert len(children) == 2

        child_ids = {c["id"] for c in children}
        assert "somme" in child_ids
        assert "verdun" in child_ids

    def test_get_arcs_for_date(self, populated_db):
        """Verify date-based arc query."""
        # July 1916 - Somme starts
        arcs = get_arcs_for_date(populated_db, date(1916, 7, 15))

        arc_ids = {a["id"] for a in arcs}
        assert "western_front" in arc_ids
        assert "somme" in arc_ids
        assert "verdun" in arc_ids
        # Eastern front also active
        assert "eastern_front" in arc_ids

    def test_get_arcs_for_date_excludes_ended(self, populated_db):
        """Verify arcs that ended are excluded."""
        # 1918 - eastern front ended
        arcs = get_arcs_for_date(populated_db, date(1918, 3, 1))

        arc_ids = {a["id"] for a in arcs}
        assert "western_front" in arc_ids
        assert "eastern_front" not in arc_ids

    def test_get_all_arcs(self, populated_db):
        """Verify all arcs retrieval."""
        arcs = get_all_arcs(populated_db)
        assert len(arcs) == 4  # western, eastern, somme, verdun
