"""Tests for newspaper quote extraction."""

import pytest

from wwi_realtime.media.newspapers import (
    ExtractedQuote,
    clean_ocr_text,
    extract_quotes,
    extract_speaker,
    estimate_quote_confidence,
    extract_headlines,
    extract_dateline,
    find_war_related_content,
    process_newspaper_page,
)


class TestCleanOcrText:
    """Tests for OCR text cleaning."""

    def test_normalize_whitespace(self):
        """Test whitespace normalization."""
        text = "This  has   multiple    spaces"
        result = clean_ocr_text(text)
        assert "  " not in result

    def test_strip_text(self):
        """Test text stripping."""
        text = "  text with spaces  "
        result = clean_ocr_text(text)
        assert result == "text with spaces"


class TestExtractQuotes:
    """Tests for quote extraction."""

    def test_extract_simple_quote(self):
        """Test extracting a simple quoted text."""
        text = 'The general said "We must advance at dawn" to his officers.'
        quotes = extract_quotes(text, min_length=10)

        assert len(quotes) == 1
        assert "advance at dawn" in quotes[0].text

    def test_extract_curly_quotes(self):
        """Test extracting curly quoted text."""
        text = 'The soldier wrote "I miss home terribly" in his letter.'
        quotes = extract_quotes(text, min_length=10)

        assert len(quotes) == 1
        assert "miss home" in quotes[0].text

    def test_skip_short_quotes(self):
        """Test that short quotes are skipped."""
        text = 'He said "yes" and then "no" but also "this is longer text".'
        quotes = extract_quotes(text, min_length=15)

        # Only the longer quote should match
        assert len(quotes) == 1
        assert "longer" in quotes[0].text

    def test_skip_long_quotes(self):
        """Test that very long quotes are skipped."""
        long_text = "a" * 400
        text = f'The document stated "{long_text}".'
        quotes = extract_quotes(text, max_length=300)

        assert len(quotes) == 0

    def test_extract_multiple_quotes(self):
        """Test extracting multiple quotes."""
        text = '''
        General Smith said "We will not retreat" and
        Private Jones wrote "The trenches are flooded".
        '''
        quotes = extract_quotes(text, min_length=10)

        assert len(quotes) == 2

    def test_extract_with_context(self):
        """Test that context is captured."""
        text = 'In the battle report, Colonel Brown declared "The enemy has retreated" after the assault.'
        quotes = extract_quotes(text, min_length=10)

        assert len(quotes) == 1
        assert quotes[0].context is not None
        assert "Colonel Brown" in quotes[0].context


class TestExtractSpeaker:
    """Tests for speaker extraction."""

    def test_extract_speaker_said(self):
        """Test extracting speaker with 'said'."""
        context = 'The important announcement was made. "We shall fight on" said Winston Churchill.'
        speaker = extract_speaker(context)

        assert speaker == "Winston Churchill"

    def test_extract_speaker_declared(self):
        """Test extracting speaker with 'declared'."""
        context = 'General Haig declared "The attack will proceed".'
        speaker = extract_speaker(context)

        assert speaker == "General Haig"

    def test_extract_speaker_according_to(self):
        """Test extracting speaker with 'according to'."""
        context = 'The offensive failed, according to Field Marshal.'
        speaker = extract_speaker(context)

        assert speaker == "Field Marshal"

    def test_no_speaker_found(self):
        """Test when no speaker is found."""
        context = 'The battle continued throughout the day.'
        speaker = extract_speaker(context)

        assert speaker is None


class TestEstimateConfidence:
    """Tests for confidence estimation."""

    def test_high_confidence_clean_text(self):
        """Test high confidence for clean text."""
        text = "The troops advanced through the village at dawn."
        confidence = estimate_quote_confidence(text)

        assert confidence >= 0.9

    def test_lower_confidence_unusual_chars(self):
        """Test lower confidence for unusual characters."""
        text = "The tr@@ps advan#ed through the vi||age"
        confidence = estimate_quote_confidence(text)

        assert confidence < 0.9

    def test_lower_confidence_all_caps(self):
        """Test lower confidence for all caps."""
        text = "THE TROOPS ADVANCED THROUGH THE VILLAGE"
        confidence = estimate_quote_confidence(text)

        assert confidence < 1.0

    def test_lower_confidence_repeated_chars(self):
        """Test lower confidence for repeated characters."""
        text = "The troooooops advanced"
        confidence = estimate_quote_confidence(text)

        assert confidence < 0.8


class TestExtractHeadlines:
    """Tests for headline extraction."""

    def test_extract_caps_headline(self):
        """Test extracting all-caps headline."""
        text = """GERMAN FORCES ADVANCE ON PARIS
        The enemy troops have made significant gains..."""
        headlines = extract_headlines(text)

        assert len(headlines) >= 1
        assert "GERMAN FORCES" in headlines[0]

    def test_skip_short_caps(self):
        """Test skipping short caps text."""
        text = """THE WAR
        More detailed content here..."""
        headlines = extract_headlines(text)

        # "THE WAR" is too short
        assert len(headlines) == 0


class TestExtractDateline:
    """Tests for dateline extraction."""

    def test_extract_london_dateline(self):
        """Test extracting London dateline."""
        text = "LONDON, July 1 — Heavy fighting continues..."
        dateline = extract_dateline(text)

        assert dateline is not None
        assert dateline['location'] == "London"
        assert "July 1" in dateline['date']

    def test_extract_paris_dateline(self):
        """Test extracting Paris dateline."""
        text = "PARIS (Aug. 15) — French forces report..."
        dateline = extract_dateline(text)

        assert dateline is not None
        assert dateline['location'] == "Paris"

    def test_no_dateline(self):
        """Test when no dateline present."""
        text = "The battle continued throughout the day."
        dateline = extract_dateline(text)

        assert dateline is None


class TestFindWarContent:
    """Tests for war-related content finding."""

    def test_find_battle_content(self):
        """Test finding battle-related content."""
        text = """The weather was pleasant yesterday.
        The battle at Verdun continues with heavy casualties.
        Local markets remain open."""
        content = find_war_related_content(text)

        assert len(content) >= 1
        assert any("Verdun" in c for c in content)

    def test_find_troop_content(self):
        """Test finding troop-related content."""
        text = "British troops advanced three miles yesterday."
        content = find_war_related_content(text)

        assert len(content) >= 1

    def test_skip_non_war_content(self):
        """Test skipping non-war content."""
        text = "The local flower show attracted many visitors."
        content = find_war_related_content(text)

        assert len(content) == 0


class TestProcessNewspaperPage:
    """Tests for full page processing."""

    def test_process_page(self):
        """Test processing a full page."""
        text = """HEAVY FIGHTING AT VERDUN
PARIS, July 1 — The battle continues.

General Petain declared "They shall not pass" as
French troops held their positions. The casualties
were reported as heavy on both sides.
"""
        result = process_newspaper_page(text)

        assert 'quotes' in result
        assert 'headlines' in result
        assert 'dateline' in result
        assert 'war_content' in result

        # Should find the dateline
        assert result['dateline'] is not None
        assert result['dateline']['location'] == "Paris"

    def test_process_empty_page(self):
        """Test processing empty page."""
        result = process_newspaper_page("")

        assert result['quotes'] == []
        assert result['headlines'] == []
        assert result['dateline'] is None
        assert result['war_content'] == []
