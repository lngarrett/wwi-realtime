"""Chronicling America API integration for fetching historical newspapers."""

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

# Library of Congress Chronicling America API
SEARCH_URL = "https://www.loc.gov/collections/chronicling-america/"
OCR_BASE_URL = "https://chroniclingamerica.loc.gov"

USER_AGENT = "WWI-RealTime/0.1 (Historical research project)"


@dataclass
class NewspaperArticle:
    """A newspaper article/page from Chronicling America."""
    id: str
    date: date
    newspaper: str
    headline: str | None
    content: str  # Full OCR text with relevant section
    page_url: str  # URL to page viewer
    state: str
    city: str | None
    ocr_url: str | None = None  # URL to raw OCR text


def extract_lccn_info(url: str) -> dict | None:
    """Extract LCCN, date, edition, and page from LOC URL.

    URLs look like:
    https://www.loc.gov/resource/sn92066979/1914-06-29/ed-1/?sp=1&q=...
    """
    # Pattern: /resource/{lccn}/{date}/ed-{edition}/?sp={page}
    match = re.search(r'/resource/([^/]+)/(\d{4}-\d{2}-\d{2})/ed-(\d+)/.*[?&]sp=(\d+)', url)
    if match:
        return {
            "lccn": match.group(1),
            "date": match.group(2),
            "edition": match.group(3),
            "page": match.group(4),
        }
    return None


def fetch_full_ocr(lccn: str, date_str: str, edition: str, page: str, client: httpx.Client) -> str | None:
    """Fetch full OCR text for a newspaper page.

    URL format: https://chroniclingamerica.loc.gov/lccn/{lccn}/{date}/ed-{ed}/seq-{page}/ocr.txt
    """
    ocr_url = f"{OCR_BASE_URL}/lccn/{lccn}/{date_str}/ed-{edition}/seq-{page}/ocr.txt"

    try:
        resp = client.get(ocr_url)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"Error fetching OCR from {ocr_url}: {e}")

    return None


def extract_relevant_section(ocr_text: str, query_terms: list[str], context_chars: int = 1500) -> str:
    """Extract the section of OCR text most relevant to the search terms."""
    if not ocr_text or not query_terms:
        return ocr_text[:context_chars] if ocr_text else ""

    text_lower = ocr_text.lower()

    # Find the best position (most query terms nearby)
    best_pos = 0
    best_score = 0

    for term in query_terms:
        term_lower = term.lower()
        pos = 0
        while True:
            idx = text_lower.find(term_lower, pos)
            if idx == -1:
                break

            # Score this position by counting nearby terms
            window_start = max(0, idx - 500)
            window_end = min(len(text_lower), idx + 500)
            window = text_lower[window_start:window_end]

            score = sum(1 for t in query_terms if t.lower() in window)
            if score > best_score:
                best_score = score
                best_pos = idx

            pos = idx + 1

    # Extract context around best position
    start = max(0, best_pos - context_chars // 3)
    end = min(len(ocr_text), best_pos + context_chars * 2 // 3)

    # Try to start/end at word boundaries
    if start > 0:
        space = ocr_text.rfind(' ', start - 50, start + 50)
        if space > 0:
            start = space + 1

    return ocr_text[start:end].strip()


def extract_headline_from_section(text: str, query_terms: list[str]) -> str | None:
    """Extract a headline from OCR text near query terms."""
    # Look for ALL CAPS sequences that contain query terms
    lines = text.split('\n')

    for i, line in enumerate(lines[:50]):  # Check first 50 lines
        line = line.strip()
        if not line:
            continue

        # Check if line is mostly uppercase (headline style)
        alpha_chars = [c for c in line if c.isalpha()]
        if not alpha_chars:
            continue

        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)

        if upper_ratio > 0.7 and len(line) > 10:
            # Check if it contains any query terms
            line_lower = line.lower()
            if any(term.lower() in line_lower for term in query_terms):
                # Clean up the headline
                headline = re.sub(r'\s+', ' ', line).strip()
                if len(headline) > 10 and len(headline) < 200:
                    return headline

    return None


def search_articles(
    query: str,
    date_start: date,
    date_end: date | None = None,
    max_results: int = 10,
    fetch_full_text: bool = True,
) -> list[NewspaperArticle]:
    """Search Chronicling America for newspaper pages matching query and date range.

    Args:
        query: Search terms (e.g., "assassination archduke ferdinand")
        date_start: Start of date range
        date_end: End of date range (defaults to date_start + 3 days)
        max_results: Maximum number of results to return
        fetch_full_text: Whether to fetch full OCR text (slower but better content)

    Returns:
        List of NewspaperArticle objects
    """
    if date_end is None:
        date_end = date_start + timedelta(days=3)

    # Format dates for API
    date_range = f"{date_start.isoformat()}/{date_end.isoformat()}"
    query_terms = [t for t in query.split() if len(t) > 2]

    params = {
        "q": query,
        "dates": date_range,
        "fo": "json",
        "c": max_results,
        "sp": 1,
    }

    headers = {"User-Agent": USER_AGENT}
    articles = []

    try:
        with httpx.Client(timeout=60, headers=headers, follow_redirects=True) as client:
            resp = client.get(SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("content", {}).get("results", [])
            if not results:
                results = data.get("results", [])

            for item in results:
                # Parse date from item
                item_date_str = item.get("date", "")
                if not item_date_str:
                    continue
                try:
                    if "-" in item_date_str:
                        parts = item_date_str.split("-")
                        item_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                    else:
                        item_date = date(
                            int(item_date_str[:4]),
                            int(item_date_str[4:6]),
                            int(item_date_str[6:8]),
                        )
                except (ValueError, IndexError):
                    continue

                # Get URL and generate ID
                url = item.get("url", item.get("id", ""))
                article_id = hashlib.sha256(url.encode()).hexdigest()[:12]

                # Get newspaper title
                partof_title = item.get("partof_title", ["Unknown"])
                if isinstance(partof_title, list):
                    newspaper = partof_title[0] if partof_title else "Unknown"
                else:
                    newspaper = str(partof_title)

                # Get location
                state_list = item.get("location_state", ["Unknown"])
                state = state_list[0] if state_list else "Unknown"
                city_list = item.get("location_city", [])
                city = city_list[0] if city_list else None

                # Default to description snippet
                description = item.get("description", [""])
                if isinstance(description, list):
                    ocr_text = description[0] if description else ""
                else:
                    ocr_text = str(description)

                ocr_url = None

                # Fetch full OCR text if requested
                if fetch_full_text:
                    lccn_info = extract_lccn_info(url)
                    if lccn_info:
                        full_ocr = fetch_full_ocr(
                            lccn_info["lccn"],
                            lccn_info["date"],
                            lccn_info["edition"],
                            lccn_info["page"],
                            client,
                        )
                        if full_ocr:
                            # Extract the relevant section
                            ocr_text = extract_relevant_section(full_ocr, query_terms)
                            ocr_url = f"{OCR_BASE_URL}/lccn/{lccn_info['lccn']}/{lccn_info['date']}/ed-{lccn_info['edition']}/seq-{lccn_info['page']}/ocr.txt"

                if not ocr_text or len(ocr_text) < 50:
                    continue

                # Extract headline from relevant section
                headline = extract_headline_from_section(ocr_text, query_terms)

                articles.append(NewspaperArticle(
                    id=article_id,
                    date=item_date,
                    newspaper=newspaper,
                    headline=headline,
                    content=ocr_text[:5000],
                    page_url=url,
                    state=state,
                    city=city,
                    ocr_url=ocr_url,
                ))

    except Exception as e:
        print(f"Error searching Chronicling America: {e}")

    return articles


def search_for_event(
    event_title: str,
    event_date: date,
    event_summary: str | None = None,
    max_results: int = 5,
) -> list[NewspaperArticle]:
    """Search for newspaper articles related to a specific event.

    Searches a date range after the event (news takes time to print).

    Args:
        event_title: Title of the event
        event_date: Date the event occurred
        event_summary: Optional summary for additional keywords
        max_results: Maximum results to return

    Returns:
        List of relevant NewspaperArticle objects
    """
    # Extract key terms from title
    stop_words = {"the", "of", "at", "in", "on", "a", "an", "and", "or", "to", "for"}
    words = event_title.lower().replace("(", "").replace(")", "").split()
    key_words = [w for w in words if w not in stop_words and len(w) > 2]

    # Build search query
    query = " ".join(key_words[:5])

    # Search from event date to +3 days (news delay)
    return search_articles(
        query=query,
        date_start=event_date,
        date_end=event_date + timedelta(days=3),
        max_results=max_results,
        fetch_full_text=True,
    )


def get_article_snippet(article: NewspaperArticle, max_length: int = 500) -> str:
    """Extract a readable snippet from article OCR text."""
    text = article.content
    text = re.sub(r'\s+', ' ', text)

    snippet = text[:max_length]
    last_period = snippet.rfind('.')
    if last_period > max_length // 2:
        snippet = snippet[:last_period + 1]

    return snippet.strip()


def format_article_for_prompt(article: NewspaperArticle) -> str:
    """Format an article for inclusion in an LLM prompt."""
    snippet = get_article_snippet(article, max_length=600)

    header = f"[{article.newspaper}, {article.date.strftime('%B %d, %Y')}]"
    if article.headline:
        header += f"\nHeadline: {article.headline}"

    return f"{header}\n{snippet}"
