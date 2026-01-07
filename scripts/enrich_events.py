"""Enrich key events with data from their Wikipedia pages.

Scrapes casualty figures and key facts from battle infoboxes.
"""

import re
import sqlite3
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def get_wikipedia_page(url: str) -> str | None:
    """Fetch Wikipedia page HTML."""
    headers = {
        "User-Agent": "WWI-Realtime-Bot/1.0 (https://github.com/lngarrett/wwi-realtime; educational project)"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def extract_infobox_data(html: str) -> dict:
    """Extract casualty and other key data from Wikipedia infobox."""
    soup = BeautifulSoup(html, "html.parser")

    data = {
        "casualties": None,
        "commanders": [],
        "strength": None,
        "result": None,
    }

    # Find infobox
    infobox = soup.find("table", class_="infobox")
    if not infobox:
        return data

    rows = infobox.find_all("tr")
    for i, row in enumerate(rows):
        header = row.find("th")
        if not header:
            continue

        header_text = header.get_text(strip=True).lower()
        td = row.find("td")

        # Some Wikipedia infoboxes have the data in the next row
        if not td and i + 1 < len(rows):
            next_row = rows[i + 1]
            tds = next_row.find_all("td")
            if tds:
                td = tds[0]  # Get first td
                cell_text = " / ".join(t.get_text(" ", strip=True) for t in tds)
            else:
                continue
        elif td:
            cell_text = td.get_text(" ", strip=True)
        else:
            continue

        # Extract casualties
        if "casualties" in header_text:
            # Found casualties row
            data["casualties"] = cell_text[:300]

        # Extract result
        if "result" in header_text:
            data["result"] = cell_text[:200]

        # Extract strength
        if "strength" in header_text:
            data["strength"] = cell_text[:200]

    # If no casualties found in infobox, search the full text
    if not data["casualties"]:
        full_text = soup.get_text()
        # Look for common casualty patterns
        casualty_patterns = [
            r'(\d{1,3}(?:,\d{3})+)\s*(?:casualties|dead|killed)',
            r'casualties.*?(\d{1,3}(?:,\d{3})+)',
        ]
        for pattern in casualty_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                # Get surrounding context
                idx = match.start()
                context = full_text[max(0, idx):idx+200]
                # Clean up whitespace
                context = ' '.join(context.split())
                data["casualties"] = context
                break

    return data


def enrich_event(conn: sqlite3.Connection, event_id: str, url: str) -> dict | None:
    """Enrich a single event with Wikipedia data."""
    html = get_wikipedia_page(url)
    if not html:
        return None

    data = extract_infobox_data(html)

    # Update event if we found casualties
    if data["casualties"]:
        # Create an enhanced summary with casualties
        cursor = conn.execute(
            "SELECT summary FROM events WHERE id = ?", (event_id,)
        )
        current_summary = cursor.fetchone()[0] or ""

        # Append casualty info if not already present
        if "casualties" not in current_summary.lower():
            enhanced_summary = f"{current_summary} [Casualties: {data['casualties']}]"
            conn.execute(
                "UPDATE events SET summary = ? WHERE id = ?",
                (enhanced_summary[:1000], event_id)
            )
            conn.commit()

    return data


def main():
    """Enrich key high-significance events."""
    db_path = Path("data/story_engine.db")
    if not db_path.exists():
        print("Database not found")
        return

    conn = sqlite3.connect(db_path)

    # Get high-significance events, prioritizing major battles
    cursor = conn.execute("""
        SELECT id, title, wikipedia_url FROM events
        WHERE significance = 'high'
        AND (title LIKE '%First day on the Somme%'
             OR title LIKE '%Battle of the Somme%'
             OR title LIKE '%Battle of Verdun%'
             OR title LIKE '%Battle of the Marne%'
             OR title LIKE '%Battle of Mons%'
             OR title LIKE '%Battle of Ypres%'
             OR title LIKE '%Gallipoli%'
             OR title LIKE '%Battle of Passchendaele%'
             OR title LIKE '%Battle of Tannenberg%'
             OR title LIKE '%Battle of Jutland%'
             OR title LIKE '%Battle of Arras%')
        UNION
        SELECT id, title, wikipedia_url FROM events
        WHERE significance = 'high'
        AND (title LIKE '%Battle%' OR title LIKE '%Siege%')
        LIMIT 60
    """)

    events = cursor.fetchall()
    print(f"Found {len(events)} high-significance battle events to enrich")

    for event_id, title, url in events:
        print(f"\nEnriching: {title}")
        print(f"  URL: {url}")

        data = enrich_event(conn, event_id, url)
        if data:
            if data["casualties"]:
                print(f"  Casualties: {data['casualties'][:100]}...")
            if data["result"]:
                print(f"  Result: {data['result'][:100]}...")

        # Rate limit
        time.sleep(1)

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
