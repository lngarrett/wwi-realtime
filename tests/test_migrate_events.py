"""Tests for event migration."""

import sqlite3
from datetime import date

import pytest

from wwi_realtime.migrate_events import (
    classify_event,
    parse_date,
)


class TestClassifyEvent:
    """Tests for event classification."""

    def test_classify_verdun(self):
        """Test classification of Verdun events."""
        arc = classify_event(
            "Battle of Verdun begins",
            "German forces attack French positions at Verdun",
            date(1916, 2, 21)
        )
        assert arc == "verdun"

    def test_classify_somme(self):
        """Test classification of Somme events."""
        arc = classify_event(
            "First Day of the Somme",
            "British forces suffer heavy casualties",
            date(1916, 7, 1)
        )
        assert arc == "somme"

    def test_classify_gallipoli(self):
        """Test classification of Gallipoli events."""
        arc = classify_event(
            "ANZAC Landing",
            "Australian and New Zealand troops land at Gallipoli",
            date(1915, 4, 25)
        )
        assert arc == "gallipoli"

    def test_classify_naval(self):
        """Test classification of naval events."""
        arc = classify_event(
            "German U-boat sinks merchant ship",
            "Submarine warfare intensifies",
            date(1917, 3, 1)
        )
        assert arc == "uboat_campaign"

    def test_classify_by_keyword_western_front(self):
        """Test classification by Western Front keyword."""
        arc = classify_event(
            "Battle in Flanders",
            "Fighting near Ypres",
            date(1915, 5, 1)
        )
        assert arc == "western_front"

    def test_classify_by_keyword_eastern_front(self):
        """Test classification by Eastern Front keyword."""
        arc = classify_event(
            "Russian advance in Galicia",
            "Fighting in Eastern Europe",
            date(1914, 9, 1)
        )
        assert arc == "eastern_front"

    def test_classify_by_date_1914(self):
        """Test classification by date for early war."""
        arc = classify_event(
            "Generic battle",
            "Fighting somewhere",
            date(1914, 8, 15)
        )
        assert arc == "western_1914"

    def test_classify_by_date_spring_offensive(self):
        """Test classification by date for Spring Offensive."""
        arc = classify_event(
            "German attack",
            "Major offensive operation",
            date(1918, 4, 1)
        )
        assert arc == "spring_offensive"

    def test_classify_by_date_hundred_days(self):
        """Test classification by date for Hundred Days."""
        arc = classify_event(
            "Allied advance",
            "Offensive continues",
            date(1918, 10, 1)
        )
        assert arc == "hundred_days"

    def test_classify_default(self):
        """Test default classification for unmatched events."""
        arc = classify_event(
            "Political developments",
            "Diplomatic negotiations",
            date(1917, 1, 15)
        )
        assert arc == "wwi_overall"

    def test_classify_italy(self):
        """Test classification of Italian Front events."""
        arc = classify_event(
            "Italian offensive",
            "Fighting in the Alps",
            date(1917, 5, 1)
        )
        assert arc == "italian_front"

    def test_classify_middle_east(self):
        """Test classification of Middle East events."""
        arc = classify_event(
            "Capture of Baghdad",
            "British forces take Mesopotamia",
            date(1917, 3, 11)
        )
        assert arc == "mesopotamian_campaign"

    def test_classify_africa(self):
        """Test classification of African Theatre events."""
        arc = classify_event(
            "German forces in East Africa",
            "Lettow-Vorbeck continues resistance",
            date(1917, 6, 1)
        )
        assert arc == "african_theatre"

    def test_classify_assassination(self):
        """Test classification of pre-war events."""
        arc = classify_event(
            "Assassination of Archduke Franz Ferdinand",
            "Shot in Sarajevo",
            date(1914, 6, 28)
        )
        assert arc == "wwi_overall"


class TestParseDate:
    """Tests for date parsing."""

    def test_parse_valid_date(self):
        """Test parsing a valid date string."""
        result = parse_date("1916-07-01")
        assert result == date(1916, 7, 1)

    def test_parse_none(self):
        """Test parsing None."""
        result = parse_date(None)
        assert result is None

    def test_parse_invalid(self):
        """Test parsing invalid date string."""
        result = parse_date("not-a-date")
        assert result is None

    def test_parse_empty(self):
        """Test parsing empty string."""
        result = parse_date("")
        assert result is None
