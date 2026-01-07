"""Tests for multi-tweet thread generation."""

import pytest
from datetime import date

from wwi_realtime.generate.threads import (
    Tweet,
    TweetThread,
    parse_thread_response,
    validate_thread,
    estimate_thread_length,
    build_thread_context,
    format_thread_for_display,
    merge_short_tweets,
    create_thread_from_passages,
)
from wwi_realtime.generate.prompts import EventContext, PassageResult


class TestTweetDataclass:
    """Tests for Tweet dataclass."""

    def test_tweet_creation(self):
        """Test basic tweet creation."""
        tweet = Tweet(
            text="This is a test tweet about WWI.",
            position=1,
            total=3,
        )
        assert tweet.text == "This is a test tweet about WWI."
        assert tweet.position == 1
        assert tweet.total == 3
        assert tweet.event_id is None
        assert tweet.source_attribution is None
        assert tweet.has_quote is False

    def test_tweet_with_all_fields(self):
        """Test tweet with all optional fields."""
        tweet = Tweet(
            text="Test tweet",
            position=2,
            total=4,
            event_id="battle_of_marne",
            source_attribution="Robert Graves",
            has_quote=True,
        )
        assert tweet.event_id == "battle_of_marne"
        assert tweet.source_attribution == "Robert Graves"
        assert tweet.has_quote is True


class TestTweetThread:
    """Tests for TweetThread dataclass."""

    def test_thread_creation(self):
        """Test basic thread creation."""
        tweets = [
            Tweet(text="Tweet 1", position=1, total=2),
            Tweet(text="Tweet 2", position=2, total=2),
        ]
        thread = TweetThread(
            tweets=tweets,
            event_title="Battle of Marne",
            event_date="1914-09-05",
        )
        assert len(thread.tweets) == 2
        assert thread.event_title == "Battle of Marne"
        assert thread.event_date == "1914-09-05"
        assert thread.arc_id is None


class TestParseThreadResponse:
    """Tests for parsing Claude's thread response."""

    def test_parse_simple_thread(self):
        """Test parsing a simple thread response."""
        response = """
        TWEET 1/3: The Battle of the Marne begins today.
        TWEET 2/3: German forces are halted just 30 miles from Paris.
        TWEET 3/3: "We shall fight on" - French commander rallies troops.
        """
        tweets = parse_thread_response(response)

        assert len(tweets) == 3
        assert tweets[0].position == 1
        assert tweets[0].total == 3
        assert "Marne" in tweets[0].text
        assert tweets[2].has_quote is True

    def test_parse_without_total(self):
        """Test parsing when total not specified."""
        response = """
        TWEET 1: First tweet.
        TWEET 2: Second tweet.
        """
        tweets = parse_thread_response(response)

        assert len(tweets) == 2
        # Total should be inferred from match count
        assert tweets[0].total == 2
        assert tweets[1].total == 2

    def test_parse_with_event_id(self):
        """Test parsing attaches event_id."""
        response = "TWEET 1/1: Single tweet."
        tweets = parse_thread_response(response, event_id="test_event")

        assert len(tweets) == 1
        assert tweets[0].event_id == "test_event"

    def test_parse_empty_response(self):
        """Test parsing empty response."""
        tweets = parse_thread_response("")
        assert tweets == []

    def test_parse_extracts_attribution(self):
        """Test attribution extraction."""
        response = """
        TWEET 1/2: As Robert Graves wrote, the trenches were hell.
        TWEET 2/2: The soldier said goodbye.
        """
        tweets = parse_thread_response(response)

        assert tweets[0].source_attribution == "Robert Graves"

    def test_parse_multiline_text_normalized(self):
        """Test that multiline text is normalized."""
        response = """
        TWEET 1/1: This tweet has
        multiple lines
        that should be joined.
        """
        tweets = parse_thread_response(response)

        assert "\n" not in tweets[0].text
        assert "multiple lines" in tweets[0].text


class TestValidateThread:
    """Tests for thread validation."""

    def test_validate_empty_thread(self):
        """Test validation of empty thread."""
        warnings = validate_thread([])
        assert "Empty thread" in warnings

    def test_validate_correct_numbering(self):
        """Test validation passes for correct numbering."""
        tweets = [
            Tweet(text="A" * 100, position=1, total=2, has_quote=True),
            Tweet(text="B" * 100, position=2, total=2),
        ]
        warnings = validate_thread(tweets)
        assert not any("Position mismatch" in w for w in warnings)

    def test_validate_incorrect_numbering(self):
        """Test validation catches incorrect numbering."""
        tweets = [
            Tweet(text="A" * 100, position=1, total=3, has_quote=True),
            Tweet(text="B" * 100, position=3, total=3),  # Missing 2
        ]
        warnings = validate_thread(tweets)
        assert any("Position mismatch" in w for w in warnings)

    def test_validate_character_limit(self):
        """Test validation catches tweets over 280 chars."""
        tweets = [
            Tweet(text="A" * 300, position=1, total=1, has_quote=True),
        ]
        warnings = validate_thread(tweets)
        assert any("exceeds 280" in w for w in warnings)

    def test_validate_no_quotes(self):
        """Test validation warns when no quotes present."""
        tweets = [
            Tweet(text="A" * 100, position=1, total=2, has_quote=False),
            Tweet(text="B" * 100, position=2, total=2, has_quote=False),
        ]
        warnings = validate_thread(tweets)
        assert any("no quoted material" in w for w in warnings)

    def test_validate_with_quotes(self):
        """Test validation passes when quotes present."""
        tweets = [
            Tweet(text="A" * 100, position=1, total=2, has_quote=True),
            Tweet(text="B" * 100, position=2, total=2, has_quote=False),
        ]
        warnings = validate_thread(tweets)
        assert not any("no quoted material" in w for w in warnings)


def make_passage(passage_id: str, has_direct_quote: bool = True, **kwargs) -> PassageResult:
    """Helper to create PassageResult with all required fields."""
    defaults = {
        "source_id": "s1",
        "content": "Test content",
        "source_title": "Test Book",
        "source_author": "Test Author",
        "source_type": "memoir",
        "source_perspective": "british",
        "date_approximate": "1914",
        "word_count": 50,
    }
    defaults.update(kwargs)
    return PassageResult(
        passage_id=passage_id,
        has_direct_quote=has_direct_quote,
        **defaults,
    )


class TestEstimateThreadLength:
    """Tests for thread length estimation."""

    @pytest.fixture
    def sample_event(self):
        """Create sample event context."""
        return EventContext(
            title="Battle of the Somme",
            date=date(1916, 7, 1),
            summary="First day of the Somme offensive.",
            arc_id="western_front",
        )

    def test_estimate_with_many_quotes(self, sample_event):
        """Test estimation with many quote passages."""
        passages = [make_passage(f"p{i}", has_direct_quote=True) for i in range(5)]
        length = estimate_thread_length(sample_event, passages)
        assert length == 5  # Lots of material

    def test_estimate_with_some_quotes(self, sample_event):
        """Test estimation with some quote passages."""
        passages = [
            make_passage("p1", has_direct_quote=True),
            make_passage("p2", has_direct_quote=True),
            make_passage("p3", has_direct_quote=False),
        ]
        length = estimate_thread_length(sample_event, passages)
        assert length == 4  # Good material

    def test_estimate_with_few_quotes(self, sample_event):
        """Test estimation with few quote passages."""
        passages = [make_passage("p1", has_direct_quote=True)]
        length = estimate_thread_length(sample_event, passages)
        assert length == 3  # Some material

    def test_estimate_with_no_quotes(self, sample_event):
        """Test estimation with no quote passages."""
        passages = [make_passage("p1", has_direct_quote=False)]
        length = estimate_thread_length(sample_event, passages)
        assert length == 2  # Limited material


class TestFormatThreadForDisplay:
    """Tests for thread display formatting."""

    def test_format_basic_thread(self):
        """Test formatting a basic thread."""
        tweets = [
            Tweet(text="First tweet.", position=1, total=2),
            Tweet(text="Second tweet.", position=2, total=2, source_attribution="Graves"),
        ]
        thread = TweetThread(
            tweets=tweets,
            event_title="Test Event",
            event_date="1914-08-01",
            arc_id="western_front",
        )

        formatted = format_thread_for_display(thread)

        assert "Test Event" in formatted
        assert "1914-08-01" in formatted
        assert "western_front" in formatted
        assert "[1/2]" in formatted
        assert "[2/2]" in formatted
        assert "Graves" in formatted


class TestMergeShortTweets:
    """Tests for merging short tweets."""

    def test_merge_short_tweets(self):
        """Test merging short tweets together."""
        tweets = [
            Tweet(text="Short.", position=1, total=3),
            Tweet(text="Also short.", position=2, total=3),
            Tweet(text="A" * 270, position=3, total=3),  # Too long to merge with combined first two
        ]
        merged = merge_short_tweets(tweets, min_length=100)

        # First two should be merged (18 chars), but third (270) can't fit with it (18+270+1>280)
        assert len(merged) == 2
        assert "Short." in merged[0].text
        assert "Also short." in merged[0].text

    def test_no_merge_if_would_exceed_limit(self):
        """Test no merge if it would exceed 280 chars."""
        tweets = [
            Tweet(text="A" * 200, position=1, total=2),
            Tweet(text="B" * 200, position=2, total=2),
        ]
        merged = merge_short_tweets(tweets, min_length=100)

        # Should not merge (would be 401 chars)
        assert len(merged) == 2

    def test_merge_renumbers(self):
        """Test that merged tweets are renumbered."""
        tweets = [
            Tweet(text="A", position=1, total=4),
            Tweet(text="B", position=2, total=4),
            Tweet(text="C" * 150, position=3, total=4),
            Tweet(text="D" * 150, position=4, total=4),
        ]
        merged = merge_short_tweets(tweets, min_length=100)

        # Should be renumbered sequentially
        for i, tweet in enumerate(merged):
            assert tweet.position == i + 1
            assert tweet.total == len(merged)

    def test_single_tweet_unchanged(self):
        """Test single tweet is returned unchanged."""
        tweets = [Tweet(text="Single", position=1, total=1)]
        merged = merge_short_tweets(tweets)
        assert merged == tweets


class TestCreateThreadFromPassages:
    """Tests for creating sample threads from passages."""

    @pytest.fixture
    def sample_event(self):
        """Create sample event context."""
        return EventContext(
            title="Battle of the Marne",
            date=date(1914, 9, 5),
            summary="The German advance is halted at the Marne River, saving Paris.",
            arc_id="western_front",
            arc_title="Western Front",
            arc_narrative="The main theater of WWI.",
        )

    @pytest.fixture
    def sample_passages(self):
        """Create sample passages."""
        return [
            make_passage(
                "p1",
                has_direct_quote=True,
                content='The battle was fierce. "We must hold!" shouted the commander.',
                source_title="Good-bye to All That",
                source_author="Robert Graves",
                source_perspective="british",
            ),
            make_passage(
                "p2",
                has_direct_quote=True,
                source_id="s2",
                content='German forces pushed forward. "For the Fatherland!" they cried.',
                source_title="Storm of Steel",
                source_author="Ernst Jünger",
                source_perspective="german",
            ),
        ]

    def test_creates_thread(self, sample_event, sample_passages):
        """Test creating a thread from passages."""
        thread = create_thread_from_passages(sample_event, sample_passages, thread_length=3)

        assert isinstance(thread, TweetThread)
        assert len(thread.tweets) == 3
        assert thread.event_title == "Battle of the Marne"
        assert thread.event_date == "1914-09-05"
        assert thread.arc_id == "western_front"

    def test_first_tweet_is_hook(self, sample_event, sample_passages):
        """Test first tweet is the event hook."""
        thread = create_thread_from_passages(sample_event, sample_passages)

        first_tweet = thread.tweets[0]
        assert "September" in first_tweet.text or "1914" in first_tweet.text
        assert "Marne" in first_tweet.text

    def test_includes_quotes_from_passages(self, sample_event, sample_passages):
        """Test thread includes quotes from passages."""
        thread = create_thread_from_passages(sample_event, sample_passages, thread_length=3)

        # At least one tweet should have a quote
        has_quoted_tweet = any(t.has_quote for t in thread.tweets)
        assert has_quoted_tweet

    def test_respects_character_limit(self, sample_event, sample_passages):
        """Test all tweets respect 280 character limit."""
        thread = create_thread_from_passages(sample_event, sample_passages)

        for tweet in thread.tweets:
            assert len(tweet.text) <= 280

    def test_fills_remaining_with_context(self, sample_event):
        """Test fills remaining tweets with arc context when few passages."""
        passages = []  # No passages
        thread = create_thread_from_passages(sample_event, passages, thread_length=3)

        assert len(thread.tweets) == 3
        # Should mention arc since we have no passages
        assert any("Western Front" in t.text or "war" in t.text.lower() for t in thread.tweets)
