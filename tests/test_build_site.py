"""Tests for static site generator."""

import json
import pytest
from pathlib import Path

from wwi_realtime.build_site import (
    format_date,
    format_month,
    render_tweet,
    render_thread,
    render_thread_tweet,
    render_day,
    render_sources,
)


class TestFormatFunctions:
    """Tests for date formatting."""

    def test_format_date(self):
        """Test date formatting."""
        result = format_date("1916-07-01")
        assert "July" in result
        assert "1916" in result
        assert "1" in result

    def test_format_month(self):
        """Test month formatting."""
        result = format_month("1916-07")
        assert result == "July 1916"


class TestRenderTweet:
    """Tests for single tweet rendering."""

    def test_render_basic_tweet(self):
        """Test rendering a basic tweet."""
        tweet = {"text": "This is a test tweet."}
        html = render_tweet(tweet)

        assert "tweet-content" in html
        assert "This is a test tweet." in html

    def test_render_tweet_with_image(self):
        """Test rendering tweet with image."""
        tweet = {
            "text": "Tweet with image.",
            "image": {
                "url": "https://example.com/image.jpg",
                "caption": "A historical photo",
            },
        }
        html = render_tweet(tweet)

        assert "tweet-image" in html
        assert "https://example.com/image.jpg" in html
        assert "A historical photo" in html

    def test_render_tweet_with_sources(self):
        """Test rendering tweet with sources."""
        tweet = {
            "text": "Tweet with sources.",
            "sources": {
                "event": {
                    "title": "Battle of the Somme",
                    "wikipedia_url": "https://en.wikipedia.org/wiki/Battle_of_the_Somme",
                },
            },
        }
        html = render_tweet(tweet)

        assert "tweet-sources" in html
        assert "Battle of the Somme" in html
        assert "wikipedia.org" in html


class TestRenderSources:
    """Tests for source rendering."""

    def test_render_wikipedia_source(self):
        """Test rendering Wikipedia source."""
        tweet = {
            "sources": {
                "event": {
                    "title": "Test Event",
                    "wikipedia_url": "https://en.wikipedia.org/wiki/Test",
                },
            },
        }
        html = render_sources(tweet)

        assert "Wikipedia" in html
        assert "Test Event" in html

    def test_render_newspaper_sources(self):
        """Test rendering newspaper sources."""
        tweet = {
            "sources": {
                "articles": [
                    {
                        "newspaper": "The Times",
                        "url": "https://example.com/article",
                        "date": "1916-07-02",
                    },
                ],
            },
        }
        html = render_sources(tweet)

        assert "Newspaper" in html
        assert "The Times" in html

    def test_render_no_sources(self):
        """Test rendering with no sources."""
        tweet = {"text": "No sources here"}
        html = render_sources(tweet)

        assert html == ""


class TestRenderThread:
    """Tests for thread rendering."""

    def test_render_basic_thread(self):
        """Test rendering a basic thread."""
        thread = {
            "tweets": [
                {"text": "First tweet in thread."},
                {"text": "Second tweet in thread."},
                {"text": "Third tweet in thread."},
            ],
        }
        html = render_thread(thread)

        assert "tweet-thread" in html
        assert "thread-position" in html
        assert "1/3" in html
        assert "2/3" in html
        assert "3/3" in html
        assert "First tweet" in html
        assert "Third tweet" in html

    def test_render_thread_with_arc(self):
        """Test rendering thread with arc badge."""
        thread = {
            "arc_title": "Battle of Verdun",
            "tweets": [
                {"text": "Tweet about Verdun."},
            ],
        }
        html = render_thread(thread)

        assert "arc-badge" in html
        assert "Battle of Verdun" in html

    def test_render_thread_with_attribution(self):
        """Test rendering thread with source attribution."""
        thread = {
            "tweets": [
                {
                    "text": "A quote from a soldier.",
                    "source_attribution": "Ernst Jünger",
                },
            ],
        }
        html = render_thread(thread)

        assert "tweet-attribution" in html
        assert "Ernst Jünger" in html

    def test_render_thread_with_primary_source(self):
        """Test rendering thread with primary source quote."""
        thread = {
            "tweets": [
                {
                    "text": "Context about the battle.",
                    "primary_source": {
                        "quote": "The shells fell like rain.",
                        "author": "Robert Graves",
                        "title": "Good-bye to All That",
                    },
                },
            ],
        }
        html = render_thread(thread)

        assert "primary-source" in html
        assert "The shells fell like rain." in html
        assert "Robert Graves" in html
        assert "Good-bye to All That" in html

    def test_render_empty_thread(self):
        """Test rendering empty thread returns empty string."""
        thread = {"tweets": []}
        html = render_thread(thread)

        assert html == ""


class TestRenderThreadTweet:
    """Tests for individual thread tweet rendering."""

    def test_render_thread_tweet_position(self):
        """Test thread tweet shows position."""
        tweet = {"text": "Tweet text"}
        html = render_thread_tweet(tweet, position=2, total=5)

        assert "2/5" in html
        assert "thread-position" in html

    def test_render_thread_tweet_with_image(self):
        """Test thread tweet with image."""
        tweet = {
            "text": "Tweet with image",
            "image": {"url": "https://example.com/img.jpg", "caption": "Photo"},
        }
        html = render_thread_tweet(tweet, 1, 1)

        assert "tweet-image" in html
        assert "example.com/img.jpg" in html


class TestRenderDay:
    """Tests for day rendering."""

    def test_render_day_with_tweets(self, tmp_path):
        """Test rendering a day with tweets."""
        day_data = {
            "date": "1916-07-01",
            "summary": "First day of the Somme",
            "tweets": [
                {"text": "The battle begins."},
                {"text": "Heavy casualties reported."},
            ],
        }
        day_file = tmp_path / "1916-07-01.json"
        day_file.write_text(json.dumps(day_data))

        html = render_day(day_file)

        assert "July" in html  # Date formatted
        assert "First day of the Somme" in html
        assert "The battle begins." in html
        assert "Heavy casualties" in html

    def test_render_day_with_threads(self, tmp_path):
        """Test rendering a day with threads."""
        day_data = {
            "date": "1916-07-01",
            "summary": "Major battle",
            "threads": [
                {
                    "arc_title": "Battle of the Somme",
                    "tweets": [
                        {"text": "Thread tweet 1"},
                        {"text": "Thread tweet 2"},
                    ],
                },
            ],
        }
        day_file = tmp_path / "1916-07-01.json"
        day_file.write_text(json.dumps(day_data))

        html = render_day(day_file)

        assert "tweet-thread" in html
        assert "Battle of the Somme" in html
        assert "1/2" in html
        assert "2/2" in html

    def test_render_day_mixed_content(self, tmp_path):
        """Test rendering a day with both threads and single tweets."""
        day_data = {
            "date": "1916-07-01",
            "summary": "Mixed content day",
            "threads": [
                {
                    "tweets": [{"text": "Thread content"}],
                },
            ],
            "tweets": [
                {"text": "Single tweet content"},
            ],
        }
        day_file = tmp_path / "1916-07-01.json"
        day_file.write_text(json.dumps(day_data))

        html = render_day(day_file)

        assert "Thread content" in html
        assert "Single tweet content" in html

    def test_render_empty_day(self, tmp_path):
        """Test rendering a day with no content."""
        day_data = {
            "date": "1916-07-01",
            "summary": "Empty day",
        }
        day_file = tmp_path / "1916-07-01.json"
        day_file.write_text(json.dumps(day_data))

        html = render_day(day_file)

        assert html == ""
