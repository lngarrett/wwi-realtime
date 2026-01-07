"""Date extraction from WWI source texts.

Extracts both precise dates and approximate date references from text.
"""

import re
from datetime import date


# WWI date range for validation
WWI_START = date(1914, 1, 1)
WWI_END = date(1919, 12, 31)

MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
    'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9,
    'oct': 10, 'nov': 11, 'dec': 12,
}

# Patterns for date extraction (ordered by specificity)
DATE_PATTERNS = [
    # Full date: "28 June 1914", "28th June 1914"
    (r'(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]+)\s+(191[4-9])',
     'dmy'),

    # Full date: "June 28, 1914", "June 28th, 1914"
    (r'([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(191[4-9])',
     'mdy'),

    # ISO date: "1914-06-28"
    (r'(191[4-9])-(\d{2})-(\d{2})',
     'iso'),

    # Month and year: "June 1914", "in June of 1914"
    (r'(?:in\s+)?([A-Za-z]+)(?:\s+of)?\s+(191[4-9])',
     'my'),

    # Year only: "in 1914", "during 1916"
    (r'(?:in|during)\s+(191[4-9])',
     'y'),
]

# Patterns for approximate date references
APPROXIMATE_PATTERNS = [
    # Seasons
    (r'(?:the\s+)?(spring|summer|autumn|fall|winter)\s+(?:of\s+)?(191[4-9])',
     '{0} {1}'),

    # Early/mid/late month
    (r'(?:the\s+)?(early|mid|late)\s+([A-Za-z]+)\s+(191[4-9])',
     '{0} {1} {2}'),

    # Beginning/end of year
    (r'(?:the\s+)?(beginning|end)\s+of\s+(191[4-9])',
     '{0} of {1}'),

    # Named battles/events as time references
    (r'during\s+(?:the\s+)?(Battle\s+of\s+[A-Za-z]+)',
     'during {0}'),
    (r'after\s+(?:the\s+)?(Battle\s+of\s+[A-Za-z]+)',
     'after {0}'),
    (r'before\s+(?:the\s+)?(Battle\s+of\s+[A-Za-z]+)',
     'before {0}'),

    # Relative references
    (r'(the\s+following\s+(?:day|week|month|year))',
     '{0}'),
    (r'(a\s+few\s+(?:days|weeks|months)\s+(?:later|earlier))',
     '{0}'),
]


def parse_date(match: re.Match, format_type: str) -> date | None:
    """Parse a date from a regex match."""
    try:
        if format_type == 'dmy':
            day = int(match.group(1))
            month_str = match.group(2).lower()
            year = int(match.group(3))
            month = MONTHS.get(month_str)
            if month:
                return date(year, month, day)

        elif format_type == 'mdy':
            month_str = match.group(1).lower()
            day = int(match.group(2))
            year = int(match.group(3))
            month = MONTHS.get(month_str)
            if month:
                return date(year, month, day)

        elif format_type == 'iso':
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return date(year, month, day)

        elif format_type == 'my':
            month_str = match.group(1).lower()
            year = int(match.group(2))
            month = MONTHS.get(month_str)
            if month:
                # Return first of month for month-only dates
                return date(year, month, 1)

        elif format_type == 'y':
            year = int(match.group(1))
            # Return mid-year for year-only dates
            return date(year, 6, 15)

    except (ValueError, IndexError):
        pass

    return None


def extract_precise_date(text: str) -> date | None:
    """Extract the most specific date from text.

    Returns the first valid WWI-era date found.
    """
    for pattern, format_type in DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            parsed = parse_date(match, format_type)
            if parsed and WWI_START <= parsed <= WWI_END:
                return parsed

    return None


def extract_approximate_date(text: str) -> str | None:
    """Extract approximate date reference from text.

    Returns a human-readable string like "summer 1916" or "during Battle of Somme".
    """
    # First try precise month/year patterns
    for pattern, format_type in DATE_PATTERNS:
        if format_type in ('my', 'y'):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if format_type == 'my':
                    month = match.group(1).capitalize()
                    year = match.group(2)
                    return f"{month} {year}"
                elif format_type == 'y':
                    return match.group(1)

    # Then try approximate patterns
    for pattern, template in APPROXIMATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = [g.capitalize() if g else '' for g in match.groups()]
            return template.format(*groups)

    return None


def extract_date_references(text: str) -> tuple[str | None, str | None]:
    """Extract both precise and approximate date references.

    Args:
        text: Text to extract dates from

    Returns:
        Tuple of (precise_date_iso, approximate_date_string)
    """
    precise = extract_precise_date(text)
    approximate = extract_approximate_date(text)

    precise_str = precise.isoformat() if precise else None

    return precise_str, approximate


def extract_all_dates(text: str) -> list[date]:
    """Extract all dates mentioned in text.

    Returns list of unique dates, sorted chronologically.
    """
    dates = set()

    for pattern, format_type in DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            parsed = parse_date(match, format_type)
            if parsed and WWI_START <= parsed <= WWI_END:
                dates.add(parsed)

    return sorted(dates)


def date_in_range(d: date, start: date | None, end: date | None) -> bool:
    """Check if date falls within a range."""
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


def infer_date_from_context(
    text: str,
    known_dates: list[date] | None = None,
) -> date | None:
    """Try to infer a date from context when no explicit date is given.

    Uses surrounding known dates to estimate.
    """
    # First try direct extraction
    precise = extract_precise_date(text)
    if precise:
        return precise

    # If we have known dates from surrounding passages, use them
    if known_dates:
        # Return median date as estimate
        sorted_dates = sorted(known_dates)
        mid_idx = len(sorted_dates) // 2
        return sorted_dates[mid_idx]

    return None
