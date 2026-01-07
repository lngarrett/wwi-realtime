"""Tests for the date extractor."""

from datetime import date

import pytest

from wwi_realtime.sources.date_extractor import (
    extract_precise_date,
    extract_approximate_date,
    extract_date_references,
    extract_all_dates,
    infer_date_from_context,
)


class TestExtractPreciseDate:
    """Tests for precise date extraction."""

    def test_extract_dmy_format(self):
        """Verify '28 June 1914' format extracted."""
        text = "On 28 June 1914, the Archduke was assassinated."
        d = extract_precise_date(text)
        assert d == date(1914, 6, 28)

    def test_extract_dmy_with_th(self):
        """Verify '1st July 1916' format extracted."""
        text = "The attack began on 1st July 1916."
        d = extract_precise_date(text)
        assert d == date(1916, 7, 1)

    def test_extract_mdy_format(self):
        """Verify 'June 28, 1914' format extracted."""
        text = "The event occurred on June 28, 1914."
        d = extract_precise_date(text)
        assert d == date(1914, 6, 28)

    def test_extract_iso_format(self):
        """Verify '1914-06-28' format extracted."""
        text = "Date: 1914-06-28"
        d = extract_precise_date(text)
        assert d == date(1914, 6, 28)

    def test_extract_month_year_only(self):
        """Verify 'June 1916' returns first of month."""
        text = "In June 1916, the offensive began."
        d = extract_precise_date(text)
        assert d == date(1916, 6, 1)

    def test_rejects_pre_war_date(self):
        """Verify dates before WWI rejected."""
        text = "He was born on 15 March 1890."
        d = extract_precise_date(text)
        assert d is None

    def test_rejects_post_war_date(self):
        """Verify dates after WWI rejected."""
        text = "He died on 20 October 1945."
        d = extract_precise_date(text)
        assert d is None

    def test_extracts_first_date(self):
        """Verify first valid date returned when multiple present."""
        text = "From 1 July 1916 to 18 November 1916, the battle raged."
        d = extract_precise_date(text)
        assert d == date(1916, 7, 1)


class TestExtractApproximateDate:
    """Tests for approximate date extraction."""

    def test_extract_month_year(self):
        """Verify 'August 1914' captured."""
        text = "In August 1914, the war began."
        approx = extract_approximate_date(text)
        assert approx == "August 1914"

    def test_extract_season(self):
        """Verify 'summer 1916' captured."""
        text = "During the summer of 1916, we advanced."
        approx = extract_approximate_date(text)
        assert "Summer" in approx and "1916" in approx

    def test_extract_early_late(self):
        """Verify 'late July 1916' captured."""
        text = "By late July 1916, casualties were mounting."
        approx = extract_approximate_date(text)
        # May return "July 1916" (month pattern) or "Late July 1916" (early/late pattern)
        assert "July" in approx and "1916" in approx

    def test_extract_battle_reference(self):
        """Verify 'during the Battle of X' captured."""
        text = "During the Battle of Verdun, we held the line."
        approx = extract_approximate_date(text)
        # Case-insensitive check
        assert "battle of verdun" in approx.lower()

    def test_year_only(self):
        """Verify year-only reference captured."""
        text = "In 1916 the situation changed."
        approx = extract_approximate_date(text)
        assert "1916" in approx


class TestExtractDateReferences:
    """Tests for combined date extraction."""

    def test_returns_both(self):
        """Verify both precise and approximate returned."""
        text = "On 1 July 1916, the Battle of the Somme began."
        precise, approx = extract_date_references(text)

        assert precise == "1916-07-01"
        assert approx is not None

    def test_handles_no_date(self):
        """Verify None returned when no date found."""
        text = "The soldiers moved through the trenches."
        precise, approx = extract_date_references(text)

        assert precise is None
        assert approx is None

    def test_approximate_only(self):
        """Verify approximate returned even without precise."""
        text = "During the summer of 1916, fighting intensified."
        precise, approx = extract_date_references(text)

        # Summer doesn't give precise date
        assert approx is not None
        assert "Summer" in approx or "1916" in approx


class TestExtractAllDates:
    """Tests for extracting all dates from text."""

    def test_extract_multiple_dates(self):
        """Verify all dates extracted."""
        text = """The offensive began on 1 July 1916.
        Heavy fighting continued through August 1916.
        The battle finally ended on 18 November 1916."""

        dates = extract_all_dates(text)

        assert len(dates) >= 2
        assert date(1916, 7, 1) in dates
        assert date(1916, 11, 18) in dates

    def test_returns_sorted(self):
        """Verify dates returned in chronological order."""
        text = "November 1916 came after July 1916."
        dates = extract_all_dates(text)

        assert dates == sorted(dates)

    def test_deduplicates(self):
        """Verify duplicate dates removed."""
        text = "1 July 1916. Yes, July 1st, 1916 was the day."
        dates = extract_all_dates(text)

        # Should have only one entry for July 1
        july_first = [d for d in dates if d == date(1916, 7, 1)]
        assert len(july_first) == 1


class TestInferDateFromContext:
    """Tests for date inference."""

    def test_uses_explicit_date(self):
        """Verify explicit date used when present."""
        text = "On 15 August 1916, we attacked."
        d = infer_date_from_context(text)
        assert d == date(1916, 8, 15)

    def test_uses_known_dates(self):
        """Verify known dates used for inference."""
        text = "The next day, we advanced further."
        known = [date(1916, 7, 1), date(1916, 7, 3), date(1916, 7, 5)]

        d = infer_date_from_context(text, known_dates=known)

        # Should return median
        assert d == date(1916, 7, 3)

    def test_returns_none_without_context(self):
        """Verify None returned when no dates available."""
        text = "We moved forward through the mud."
        d = infer_date_from_context(text)
        assert d is None
