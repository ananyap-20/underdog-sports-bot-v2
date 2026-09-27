from types import SimpleNamespace

import requests

from src import public_attention


class FakeResponse:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


RSS_LOW = """<?xml version="1.0"?>
<rss><channel>
  <item><title>Discussion 1</title><pubDate>Wed, 23 Sep 2026 10:00:00 GMT</pubDate></item>
  <item><title>Discussion 2</title><pubDate>Wed, 22 Sep 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

RSS_HIGH = """<?xml version="1.0"?>
<rss><channel>
  <item><title>1</title></item>
  <item><title>2</title></item>
  <item><title>3</title></item>
  <item><title>4</title></item>
</channel></rss>"""


def coverage(news_gap=True, social_count=0):
    return {
        "verification_available": True,
        "coverage_gap": news_gap,
        "social_result_count": social_count,
    }


def test_reddit_low_discussion_is_available_and_low():
    result = public_attention.verify_reddit_discussions(
        "Small-town athlete wins medal",
        30,
        FakeSession(FakeResponse(RSS_LOW)),
    )

    assert result.verification_available
    assert result.result_count == 2
    assert result.low_discussion is True


def test_reddit_high_discussion_is_not_low():
    result = public_attention.verify_reddit_discussions(
        "Popular athlete wins medal",
        30,
        FakeSession(FakeResponse(RSS_HIGH)),
    )

    assert result.verification_available
    assert result.result_count == 4
    assert result.low_discussion is False


def test_reddit_failure_is_unknown_not_low():
    result = public_attention.verify_reddit_discussions(
        "Athlete wins medal",
        30,
        FakeSession(error=requests.Timeout()),
    )

    assert not result.verification_available
    assert result.low_discussion is None


def test_low_news_plus_low_discussion_establishes_public_attention_gap():
    story = SimpleNamespace()
    discussion = public_attention.DiscussionResult(
        True,
        1,
        True,
        "ok",
        "athlete medal",
    )

    result = public_attention.evaluate_public_attention(
        coverage(news_gap=True, social_count=4),
        discussion,
        story,
    )

    assert result["public_attention_gap"] is True
    assert result["reddit_discussion_gap"] is True
    assert result["public_attention_gap"] is True


def test_social_result_count_alone_does_not_establish_gap():
    story = SimpleNamespace()
    discussion = public_attention.DiscussionResult(
        False,
        0,
        None,
        "unavailable",
        "athlete medal",
    )

    result = public_attention.evaluate_public_attention(
        coverage(news_gap=True, social_count=1),
        discussion,
        story,
    )

    assert result["public_attention_gap"] is False
    assert result["social_visibility_gap"] is None


def test_high_known_followers_block_public_attention_gap():
    story = SimpleNamespace(_follower_count=500_000)
    discussion = public_attention.DiscussionResult(
        True,
        0,
        True,
        "ok",
        "athlete medal",
    )

    result = public_attention.evaluate_public_attention(
        coverage(news_gap=True, social_count=0),
        discussion,
        story,
    )

    assert result["audience_high"] is True
    assert result["public_attention_gap"] is False


def test_high_news_coverage_blocks_public_attention_gap():
    story = SimpleNamespace()
    discussion = public_attention.DiscussionResult(
        True,
        0,
        True,
        "ok",
        "athlete medal",
    )

    result = public_attention.evaluate_public_attention(
        coverage(news_gap=False, social_count=0),
        discussion,
        story,
    )

    assert result["public_attention_gap"] is True
