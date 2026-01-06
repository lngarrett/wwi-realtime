"""Wikipedia API utilities for fetching WWI events."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterator

import httpx
from dateutil import parser as date_parser


WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "WWI-RealTime/0.1 (Historical research project; https://github.com/example/wwi-realtime)"

# WWI date range
WWI_START = date(1914, 6, 28)  # Assassination of Franz Ferdinand
WWI_END = date(1918, 11, 11)    # Armistice


@dataclass
class WikipediaEvent:
    """A single event extracted from Wikipedia."""
    title: str
    summary: str
    wikipedia_url: str
    wikidata_id: str | None
    dates: list[date]
    start_date: date | None
    end_date: date | None
    location: str | None
    categories: list[str]
    citations: list[dict]
    raw_extract: str
    image_url: str | None = None
    image_caption: str | None = None


def get_category_members(category: str, limit: int = 500) -> Iterator[dict]:
    """Get all pages in a Wikipedia category."""
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmlimit": min(limit, 500),
        "cmtype": "page",
        "format": "json",
    }

    headers = {"User-Agent": USER_AGENT}

    with httpx.Client(timeout=30, headers=headers) as client:
        while True:
            resp = client.get(WIKIPEDIA_API, params=params)
            resp.raise_for_status()
            data = resp.json()

            for member in data.get("query", {}).get("categorymembers", []):
                yield member

            # Handle continuation
            if "continue" in data:
                params["cmcontinue"] = data["continue"]["cmcontinue"]
            else:
                break


def get_page_content(title: str) -> dict | None:
    """Get full page content including extract, categories, and wikidata ID."""
    params = {
        "action": "query",
        "titles": title,
        "prop": "extracts|categories|pageprops|info",
        "exintro": False,
        "explaintext": True,
        "exsectionformat": "plain",
        "cllimit": 50,
        "inprop": "url",
        "format": "json",
    }

    headers = {"User-Agent": USER_AGENT}

    with httpx.Client(timeout=30, headers=headers) as client:
        resp = client.get(WIKIPEDIA_API, params=params)
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1":
                return None
            return page

    return None


def get_page_html(title: str) -> str | None:
    """Get parsed HTML content of a page (for extracting citations)."""
    params = {
        "action": "parse",
        "page": title,
        "prop": "text|sections",
        "format": "json",
    }

    headers = {"User-Agent": USER_AGENT}

    with httpx.Client(timeout=30, headers=headers) as client:
        resp = client.get(WIKIPEDIA_API, params=params)
        resp.raise_for_status()
        data = resp.json()

        if "parse" in data:
            return data["parse"].get("text", {}).get("*")

    return None


def extract_dates_from_text(text: str) -> list[date]:
    """Extract dates from text using pattern matching and dateutil."""
    dates = []

    # Common date patterns in WWI articles
    patterns = [
        # "28 June 1914", "June 28, 1914"
        r'\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+191[4-8])\b',
        r'\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+191[4-8])\b',
        # "1914-06-28" ISO format
        r'\b(191[4-8]-\d{2}-\d{2})\b',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                parsed = date_parser.parse(match, fuzzy=True)
                if WWI_START <= parsed.date() <= WWI_END:
                    dates.append(parsed.date())
            except (ValueError, TypeError):
                continue

    return sorted(set(dates))


def extract_infobox_dates(html: str) -> tuple[date | None, date | None]:
    """Extract start/end dates from infobox if present."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    infobox = soup.find("table", class_="infobox")

    if not infobox:
        return None, None

    start_date = None
    end_date = None

    # Look for date rows in infobox
    for row in infobox.find_all("tr"):
        header = row.find("th")
        if header:
            header_text = header.get_text().lower()
            if "date" in header_text:
                td = row.find("td")
                if td:
                    dates = extract_dates_from_text(td.get_text())
                    if len(dates) >= 2:
                        start_date = dates[0]
                        end_date = dates[-1]
                    elif len(dates) == 1:
                        start_date = dates[0]

    return start_date, end_date


def extract_citations(html: str) -> list[dict]:
    """Extract citations/references from Wikipedia HTML."""
    from bs4 import BeautifulSoup

    citations = []
    soup = BeautifulSoup(html, "lxml")

    # Find reference list
    ref_list = soup.find("ol", class_="references")
    if not ref_list:
        return citations

    for i, ref in enumerate(ref_list.find_all("li"), 1):
        citation = {
            "index": i,
            "text": ref.get_text(strip=True)[:500],  # Limit length
        }

        # Extract any URLs
        links = ref.find_all("a", class_="external")
        if links:
            citation["urls"] = [link.get("href") for link in links if link.get("href")]

        citations.append(citation)

    return citations


def get_page_image(title: str, thumb_size: int = 800) -> tuple[str | None, str | None]:
    """Get the main image for a Wikipedia page.

    Returns (image_url, caption) tuple.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageimages|images",
        "pithumbsize": thumb_size,
        "piprop": "thumbnail|name",
        "format": "json",
    }

    headers = {"User-Agent": USER_AGENT}

    try:
        with httpx.Client(timeout=30, headers=headers) as client:
            resp = client.get(WIKIPEDIA_API, params=params)
            resp.raise_for_status()
            data = resp.json()

            pages = data.get("query", {}).get("pages", {})
            for page_id, page in pages.items():
                if page_id == "-1":
                    return None, None

                thumb = page.get("thumbnail", {})
                if thumb:
                    image_url = thumb.get("source")
                    # Use the page image filename as caption placeholder
                    caption = page.get("pageimage", "").replace("_", " ")
                    return image_url, caption
    except Exception:
        pass

    return None, None


def extract_location(text: str, title: str) -> str | None:
    """Try to extract location from text or title."""
    # Common location patterns
    location_patterns = [
        r'(?:at|in|near)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        r'(?:Battle of|Siege of|Attack on)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
    ]

    # Check title first
    for pattern in location_patterns:
        match = re.search(pattern, title)
        if match:
            return match.group(1)

    # Then check text
    for pattern in location_patterns:
        match = re.search(pattern, text[:1000])  # First 1000 chars
        if match:
            return match.group(1)

    return None


def fetch_wwi_event(title: str) -> WikipediaEvent | None:
    """Fetch and parse a single WWI event from Wikipedia."""
    page = get_page_content(title)
    if not page:
        return None

    extract = page.get("extract", "")
    if not extract:
        return None

    # Get HTML for citations and infobox
    html = get_page_html(title)

    # Extract dates
    dates = extract_dates_from_text(extract)

    # Try to get structured dates from infobox
    start_date, end_date = None, None
    if html:
        start_date, end_date = extract_infobox_dates(html)

    # If no infobox dates, use first/last from text
    if dates and not start_date:
        start_date = dates[0]
        if len(dates) > 1:
            end_date = dates[-1]

    # Extract citations
    citations = []
    if html:
        citations = extract_citations(html)

    # Extract categories
    categories = [
        cat["title"].replace("Category:", "")
        for cat in page.get("categories", [])
    ]

    # Get wikidata ID
    wikidata_id = page.get("pageprops", {}).get("wikibase_item")

    # Build summary (first paragraph)
    summary = extract[:500].split("\n")[0] if extract else ""

    # Get page image
    image_url, image_caption = get_page_image(title)

    return WikipediaEvent(
        title=title,
        summary=summary,
        wikipedia_url=page.get("fullurl", f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"),
        wikidata_id=wikidata_id,
        dates=dates,
        start_date=start_date,
        end_date=end_date,
        location=extract_location(extract, title),
        categories=categories,
        citations=citations[:20],  # Limit to first 20 citations
        raw_extract=extract[:5000],  # Limit raw extract
        image_url=image_url,
        image_caption=image_caption,
    )


def get_wwi_categories() -> list[str]:
    """Get list of Wikipedia categories to scrape for WWI events."""
    return [
        # Battle categories
        "Category:Battles of World War I",
        "Category:Battles of the Western Front (World War I)",
        "Category:Battles of the Eastern Front (World War I)",
        "Category:Battles of the Italian front (World War I)",
        "Category:Battles of the Balkan Front (World War I)",
        "Category:Battles of the African theatre of World War I",
        "Category:Battles of the Middle Eastern theatre of World War I",
        "Category:Naval battles of World War I",
        "Category:Aerial operations and battles of World War I",
        "Category:Sieges of World War I",
        # Other military operations
        "Category:World War I offensives",
        "Category:Meuse–Argonne offensive",
        "Category:Hundred Days Offensive",
        "Category:Battle of Verdun",
        # Political/diplomatic events
        "Category:World War I treaties",
        "Category:Politics of World War I",
        # Key events
        "Category:1914 beginnings",
        "Category:Assassination of Archduke Franz Ferdinand of Austria",
    ]


def get_wwi_categories_recursive() -> Iterator[str]:
    """Recursively get all WWI-related categories including subcategories."""
    seen = set()
    to_visit = list(get_wwi_categories())

    while to_visit:
        category = to_visit.pop(0)
        if category in seen:
            continue
        seen.add(category)
        yield category

        # Get subcategories (limit depth to avoid going too deep)
        if len(seen) < 100:  # Limit total categories
            for subcat in get_subcategories(category):
                if subcat not in seen and "World War I" in subcat:
                    to_visit.append(subcat)


def get_subcategories(category: str) -> list[str]:
    """Get direct subcategories of a category."""
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmlimit": 50,
        "cmtype": "subcat",
        "format": "json",
    }

    headers = {"User-Agent": USER_AGENT}

    try:
        with httpx.Client(timeout=30, headers=headers) as client:
            resp = client.get(WIKIPEDIA_API, params=params)
            resp.raise_for_status()
            data = resp.json()
            return [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
    except Exception:
        return []
