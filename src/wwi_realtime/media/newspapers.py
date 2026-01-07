"""Newspaper quote extraction from OCR text.

Extracts quotes from Chronicling America newspaper OCR data.
"""

import re
from dataclasses import dataclass


@dataclass
class ExtractedQuote:
    """A quote extracted from newspaper OCR."""
    text: str
    speaker: str | None = None
    context: str | None = None  # Text around the quote
    confidence: float = 1.0  # Lower for OCR-degraded quotes


# Common OCR errors in quotation marks
QUOTE_CHAR_VARIANTS = [
    '"',  # Standard
    '"', '"',  # Curly
    '``', "''",  # Typewriter style
    '„', '‟',  # Low/high
    '«', '»',  # Guillemets
    '\\"',  # Escaped
]

# Patterns for attributed quotes: "quote" said/says/declared X
ATTRIBUTION_PATTERNS = [
    r'(?:said|says|declared|stated|replied|exclaimed|shouted|wrote|cried)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
    r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:said|says|declared|stated)',
    r'(?:according to|—)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
]


def clean_ocr_text(text: str) -> str:
    """Clean common OCR errors in text.

    Args:
        text: Raw OCR text

    Returns:
        Cleaned text
    """
    # Fix common OCR substitutions
    replacements = [
        ('|', 'I'),  # Pipe often misread as I
        ('0', 'O'),  # Zero/O confusion in context
        ('l', 'l'),  # Various l variants
        ('  ', ' '),  # Double spaces
    ]

    result = text
    for old, new in replacements:
        result = result.replace(old, new)

    # Normalize whitespace
    result = re.sub(r'\s+', ' ', result)

    return result.strip()


def extract_quotes(text: str, min_length: int = 20, max_length: int = 300) -> list[ExtractedQuote]:
    """Extract quoted text from newspaper OCR.

    Looks for text within quotation marks and tries to identify speakers.

    Args:
        text: OCR text to search
        min_length: Minimum quote length to extract
        max_length: Maximum quote length to extract

    Returns:
        List of extracted quotes
    """
    quotes = []

    # Build pattern for various quote styles
    # Pattern: opening quote, content, closing quote
    quote_pattern = r'["""''„‟«»`]+([^"""''„‟«»`]+?)["""''„‟«»`]+'

    matches = re.finditer(quote_pattern, text, re.DOTALL)

    for match in matches:
        quote_text = match.group(1).strip()

        # Skip too short or too long
        if len(quote_text) < min_length or len(quote_text) > max_length:
            continue

        # Clean the quote
        quote_text = clean_ocr_text(quote_text)

        # Skip if still too short after cleaning
        if len(quote_text) < min_length:
            continue

        # Get context around the quote
        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 100)
        context = text[start:end]

        # Try to find attribution
        speaker = extract_speaker(context)

        # Estimate confidence based on OCR quality
        confidence = estimate_quote_confidence(quote_text)

        quotes.append(ExtractedQuote(
            text=quote_text,
            speaker=speaker,
            context=context,
            confidence=confidence,
        ))

    return quotes


def extract_speaker(context: str) -> str | None:
    """Try to extract the speaker from text around a quote.

    Args:
        context: Text around the quote

    Returns:
        Speaker name if found, None otherwise
    """
    for pattern in ATTRIBUTION_PATTERNS:
        match = re.search(pattern, context, re.IGNORECASE)
        if match:
            speaker = match.group(1)
            # Validate it looks like a name
            if len(speaker) > 2 and speaker[0].isupper():
                return speaker

    return None


def estimate_quote_confidence(text: str) -> float:
    """Estimate confidence in quote quality based on OCR indicators.

    Args:
        text: Quote text

    Returns:
        Confidence score 0.0-1.0
    """
    confidence = 1.0

    # Reduce for unusual characters (likely OCR errors)
    unusual = len(re.findall(r'[^\w\s.,!?;:\'"()-]', text))
    if unusual > 0:
        confidence -= min(0.3, unusual * 0.05)

    # Reduce for all caps (often OCR headers)
    if text.isupper():
        confidence -= 0.2

    # Reduce for very short words ratio (fragmented OCR)
    words = text.split()
    if words:
        short_ratio = sum(1 for w in words if len(w) <= 2) / len(words)
        if short_ratio > 0.5:
            confidence -= 0.2

    # Reduce for repeated characters (OCR artifacts)
    if re.search(r'(.)\1{3,}', text):
        confidence -= 0.3

    return max(0.0, confidence)


def extract_headlines(text: str) -> list[str]:
    """Extract likely headlines from newspaper OCR.

    Headlines are typically ALL CAPS or Title Case at start of text blocks.

    Args:
        text: OCR text

    Returns:
        List of extracted headlines
    """
    headlines = []

    # Pattern: All caps words at start of line, 3+ words
    caps_pattern = r'^([A-Z][A-Z\s]{10,50})$'
    for line in text.split('\n'):
        line = line.strip()
        if re.match(caps_pattern, line):
            # Clean up and add
            headline = ' '.join(line.split())
            if len(headline) > 10:
                headlines.append(headline)

    return headlines


def extract_dateline(text: str) -> dict | None:
    """Extract dateline from newspaper article.

    Datelines typically look like: LONDON, July 1 — or PARIS (July 1)

    Args:
        text: OCR text

    Returns:
        Dict with location and date if found
    """
    patterns = [
        r'^([A-Z]{3,}),?\s+([A-Za-z]+\.?\s+\d{1,2})\s*[—–-]',
        r'^([A-Z]{3,})\s+\(([A-Za-z]+\.?\s+\d{1,2})\)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return {
                'location': match.group(1).title(),
                'date': match.group(2),
            }

    return None


def find_war_related_content(text: str) -> list[str]:
    """Find sentences mentioning war-related terms.

    Args:
        text: OCR text

    Returns:
        List of relevant sentences
    """
    war_terms = [
        r'\bwar\b', r'\bbattle\b', r'\btroops?\b', r'\bsoldiers?\b',
        r'\barmy\b', r'\bnavy\b', r'\bGerman\b', r'\bBritish\b',
        r'\bFrench\b', r'\bAmerican\b', r'\bAllied\b', r'\boffensive\b',
        r'\bcasualt(?:y|ies)\b', r'\bfront\b', r'\btrench(?:es)?\b',
        r'\bshell(?:s|ing)?\b', r'\bartillery\b', r'\bmachine gun\b',
        r'\badvance\b', r'\bretreat\b', r'\bvictory\b', r'\bdefeat\b',
    ]

    pattern = '|'.join(war_terms)
    sentences = []

    # Split into sentences
    for sentence in re.split(r'[.!?]+', text):
        sentence = sentence.strip()
        if len(sentence) > 20 and re.search(pattern, sentence, re.IGNORECASE):
            sentences.append(clean_ocr_text(sentence))

    return sentences


def process_newspaper_page(ocr_text: str) -> dict:
    """Process a full newspaper page OCR.

    Args:
        ocr_text: Full page OCR text

    Returns:
        Dict with extracted content
    """
    return {
        'quotes': extract_quotes(ocr_text),
        'headlines': extract_headlines(ocr_text),
        'dateline': extract_dateline(ocr_text),
        'war_content': find_war_related_content(ocr_text),
    }
