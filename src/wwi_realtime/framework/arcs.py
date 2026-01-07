"""Arc hierarchy management from Wikipedia campaign pages.

Scrapes Wikipedia theater/campaign articles to build narrative arcs
with parent-child relationships.
"""

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date

import httpx
from bs4 import BeautifulSoup

from wwi_realtime.utils.wikipedia import (
    WIKIPEDIA_API,
    USER_AGENT,
    extract_dates_from_text,
)


@dataclass
class Arc:
    """A narrative arc representing a campaign, theater, or operation."""
    id: str
    title: str
    parent_arc_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    wikipedia_url: str | None = None
    narrative_summary: str | None = None
    significance: str | None = None
    theater: str | None = None
    child_arcs: list["Arc"] = field(default_factory=list)


# Major WWI theaters and campaigns to scrape
WWI_THEATERS = {
    "wwi_overall": {
        "title": "World War I",
        "wikipedia_url": "https://en.wikipedia.org/wiki/World_War_I",
        "theater": None,
    },
    "western_front": {
        "title": "Western Front",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Western_Front_(World_War_I)",
        "theater": "western",
    },
    "eastern_front": {
        "title": "Eastern Front",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Eastern_Front_(World_War_I)",
        "theater": "eastern",
    },
    "gallipoli": {
        "title": "Gallipoli Campaign",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Gallipoli_campaign",
        "theater": "mediterranean",
    },
    "italian_front": {
        "title": "Italian Front",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Italian_front_(World_War_I)",
        "theater": "italian",
    },
    "mesopotamian_campaign": {
        "title": "Mesopotamian Campaign",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Mesopotamian_campaign",
        "theater": "middle_east",
    },
    "sinai_palestine": {
        "title": "Sinai and Palestine Campaign",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Sinai_and_Palestine_campaign",
        "theater": "middle_east",
    },
    "african_theatre": {
        "title": "African Theatre",
        "wikipedia_url": "https://en.wikipedia.org/wiki/African_theatre_of_World_War_I",
        "theater": "africa",
    },
    "naval_warfare": {
        "title": "Naval Warfare",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Naval_warfare_of_World_War_I",
        "theater": "naval",
    },
}

# Sub-campaigns and major operations
WWI_CAMPAIGNS = {
    # Western Front 1914
    "western_1914": {
        "title": "1914 Western Front",
        "parent": "western_front",
        "theater": "western",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Race_to_the_Sea",
    },
    "battle_of_frontiers": {
        "title": "Battle of the Frontiers",
        "parent": "western_1914",
        "theater": "western",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Battle_of_the_Frontiers",
    },
    "first_marne": {
        "title": "First Battle of the Marne",
        "parent": "western_1914",
        "theater": "western",
        "wikipedia_url": "https://en.wikipedia.org/wiki/First_Battle_of_the_Marne",
    },
    # Western Front major battles
    "verdun": {
        "title": "Battle of Verdun",
        "parent": "western_front",
        "theater": "western",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Battle_of_Verdun",
    },
    "somme": {
        "title": "Battle of the Somme",
        "parent": "western_front",
        "theater": "western",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Battle_of_the_Somme",
    },
    "passchendaele": {
        "title": "Battle of Passchendaele",
        "parent": "western_front",
        "theater": "western",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Battle_of_Passchendaele",
    },
    "spring_offensive": {
        "title": "German Spring Offensive",
        "parent": "western_front",
        "theater": "western",
        "wikipedia_url": "https://en.wikipedia.org/wiki/German_spring_offensive",
    },
    "hundred_days": {
        "title": "Hundred Days Offensive",
        "parent": "western_front",
        "theater": "western",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Hundred_Days_Offensive",
    },
    # Eastern Front
    "tannenberg": {
        "title": "Battle of Tannenberg",
        "parent": "eastern_front",
        "theater": "eastern",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Battle_of_Tannenberg_(1914)",
    },
    "gorlice_tarnow": {
        "title": "Gorlice-Tarnów Offensive",
        "parent": "eastern_front",
        "theater": "eastern",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Gorlice–Tarnów_offensive",
    },
    "brusilov_offensive": {
        "title": "Brusilov Offensive",
        "parent": "eastern_front",
        "theater": "eastern",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Brusilov_offensive",
    },
    # Italian Front
    "isonzo_battles": {
        "title": "Battles of the Isonzo",
        "parent": "italian_front",
        "theater": "italian",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Battles_of_the_Isonzo",
    },
    "caporetto": {
        "title": "Battle of Caporetto",
        "parent": "italian_front",
        "theater": "italian",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Battle_of_Caporetto",
    },
    # Naval
    "jutland": {
        "title": "Battle of Jutland",
        "parent": "naval_warfare",
        "theater": "naval",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Battle_of_Jutland",
    },
    "uboat_campaign": {
        "title": "U-boat Campaign",
        "parent": "naval_warfare",
        "theater": "naval",
        "wikipedia_url": "https://en.wikipedia.org/wiki/U-boat_campaign",
    },
}


def get_page_intro(title: str, client: httpx.Client | None = None) -> tuple[str, str | None]:
    """Get the intro summary and first paragraph of a Wikipedia page.

    Returns (summary, first_paragraph).
    """
    close_client = client is None
    if client is None:
        client = httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})

    try:
        params = {
            "action": "query",
            "titles": title,
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "format": "json",
        }

        resp = client.get(WIKIPEDIA_API, params=params)
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1":
                return "", None

            extract = page.get("extract", "")
            paragraphs = extract.split("\n\n")

            summary = paragraphs[0] if paragraphs else ""
            first_para = paragraphs[1] if len(paragraphs) > 1 else None

            return summary[:1000], first_para[:1000] if first_para else None

    except Exception as e:
        print(f"Error fetching intro for {title}: {e}")
        return "", None
    finally:
        if close_client:
            client.close()


def get_page_dates(url: str, client: httpx.Client | None = None) -> tuple[date | None, date | None]:
    """Extract start/end dates from a Wikipedia page's infobox.

    Returns (start_date, end_date).
    """
    close_client = client is None
    if client is None:
        client = httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})

    try:
        # Extract page title from URL
        title = url.split("/wiki/")[-1].replace("_", " ")

        params = {
            "action": "parse",
            "page": title,
            "prop": "text",
            "format": "json",
        }

        resp = client.get(WIKIPEDIA_API, params=params)
        resp.raise_for_status()
        data = resp.json()

        html = data.get("parse", {}).get("text", {}).get("*", "")
        if not html:
            return None, None

        soup = BeautifulSoup(html, "lxml")
        infobox = soup.find("table", class_="infobox")

        if not infobox:
            return None, None

        # Look for date row
        for row in infobox.find_all("tr"):
            header = row.find("th")
            if header and "date" in header.get_text().lower():
                td = row.find("td")
                if td:
                    dates = extract_dates_from_text(td.get_text())
                    if len(dates) >= 2:
                        return dates[0], dates[-1]
                    elif len(dates) == 1:
                        return dates[0], dates[0]

        return None, None

    except Exception as e:
        print(f"Error fetching dates for {url}: {e}")
        return None, None
    finally:
        if close_client:
            client.close()


def build_arc_hierarchy() -> list[Arc]:
    """Build the complete arc hierarchy from predefined theaters and campaigns.

    Returns list of top-level arcs with nested child_arcs.
    """
    arcs_by_id: dict[str, Arc] = {}

    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        # Create theater arcs
        for arc_id, info in WWI_THEATERS.items():
            title = info["title"]
            url = info["wikipedia_url"]

            # Get summary from Wikipedia
            wiki_title = url.split("/wiki/")[-1].replace("_", " ")
            summary, significance = get_page_intro(wiki_title, client)

            # Get dates
            start_date, end_date = get_page_dates(url, client)

            arc = Arc(
                id=arc_id,
                title=title,
                parent_arc_id=None,
                start_date=start_date,
                end_date=end_date,
                wikipedia_url=url,
                narrative_summary=summary,
                significance=significance,
                theater=info.get("theater"),
            )
            arcs_by_id[arc_id] = arc

        # Create campaign arcs
        for arc_id, info in WWI_CAMPAIGNS.items():
            title = info["title"]
            url = info.get("wikipedia_url")
            parent_id = info.get("parent")

            # Get summary from Wikipedia if URL provided
            summary, significance = "", None
            start_date, end_date = None, None

            if url:
                wiki_title = url.split("/wiki/")[-1].replace("_", " ")
                summary, significance = get_page_intro(wiki_title, client)
                start_date, end_date = get_page_dates(url, client)

            arc = Arc(
                id=arc_id,
                title=title,
                parent_arc_id=parent_id,
                start_date=start_date,
                end_date=end_date,
                wikipedia_url=url,
                narrative_summary=summary,
                significance=significance,
                theater=info.get("theater"),
            )
            arcs_by_id[arc_id] = arc

            # Add to parent's children
            if parent_id and parent_id in arcs_by_id:
                arcs_by_id[parent_id].child_arcs.append(arc)

    # Return top-level arcs (those without parents)
    return [arc for arc in arcs_by_id.values() if arc.parent_arc_id is None]


def populate_arcs_table(conn: sqlite3.Connection, arcs: list[Arc] | None = None) -> int:
    """Populate the arcs table from arc hierarchy.

    If arcs is None, builds hierarchy from Wikipedia first.

    Returns number of arcs inserted.
    """
    if arcs is None:
        arcs = build_arc_hierarchy()

    count = 0

    def insert_arc(arc: Arc) -> None:
        nonlocal count

        conn.execute(
            """INSERT OR REPLACE INTO arcs
            (id, title, parent_arc_id, start_date, end_date, wikipedia_url,
             narrative_summary, significance, theater)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                arc.id,
                arc.title,
                arc.parent_arc_id,
                arc.start_date.isoformat() if arc.start_date else None,
                arc.end_date.isoformat() if arc.end_date else None,
                arc.wikipedia_url,
                arc.narrative_summary,
                arc.significance,
                arc.theater,
            )
        )
        count += 1

        # Insert children
        for child in arc.child_arcs:
            insert_arc(child)

    for arc in arcs:
        insert_arc(arc)

    conn.commit()
    return count


def get_arc(conn: sqlite3.Connection, arc_id: str) -> dict | None:
    """Get a single arc by ID."""
    cursor = conn.execute(
        """SELECT id, title, parent_arc_id, start_date, end_date,
                  wikipedia_url, narrative_summary, significance, theater
           FROM arcs WHERE id = ?""",
        (arc_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None

    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


def get_child_arcs(conn: sqlite3.Connection, parent_arc_id: str) -> list[dict]:
    """Get all child arcs of a parent arc."""
    cursor = conn.execute(
        """SELECT id, title, parent_arc_id, start_date, end_date,
                  wikipedia_url, narrative_summary, significance, theater
           FROM arcs WHERE parent_arc_id = ?
           ORDER BY start_date""",
        (parent_arc_id,)
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_arcs_for_date(conn: sqlite3.Connection, target_date: date) -> list[dict]:
    """Get all arcs active on a given date."""
    cursor = conn.execute(
        """SELECT id, title, parent_arc_id, start_date, end_date,
                  wikipedia_url, narrative_summary, significance, theater
           FROM arcs
           WHERE (start_date IS NULL OR start_date <= ?)
             AND (end_date IS NULL OR end_date >= ?)
           ORDER BY start_date""",
        (target_date.isoformat(), target_date.isoformat())
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_all_arcs(conn: sqlite3.Connection) -> list[dict]:
    """Get all arcs."""
    cursor = conn.execute(
        """SELECT id, title, parent_arc_id, start_date, end_date,
                  wikipedia_url, narrative_summary, significance, theater
           FROM arcs ORDER BY start_date"""
    )

    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
