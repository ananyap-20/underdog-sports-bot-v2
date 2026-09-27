from types import SimpleNamespace
from src import public_attention

RSS_LOW = """<?xml version="1.0"?><rss><channel>
<item><title>one</title><pubDate>Sun, 27 Sep 2026 12:00:00 GMT</pubDate></item>
<item><title>two</title><pubDate>Sun, 27 Sep 2026 11:00:00 GMT</pubDate></item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, body, status=200):
        self.text = body
        self.status_code = status
        self.headers = {}


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.response


def test_rss_two_posts_is_low(monkeypatch, tmp_path):
    monkeypatch.setattr(public_attention, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(public_attention, "REDDIT_MIN_REQUEST_INTERVAL_SECONDS", 0)
    session = FakeSession(FakeResponse(RSS_LOW))
    result = public_attention.verify_reddit_discussions(
        "Small-town athlete wins medal", 30, session=session
    )
    assert result.verification_available is True
    assert result.result_count == 2
    assert result.low_discussion is True
    assert session.calls == 1


def test_explicit_session_bypasses_stale_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(public_attention, "CACHE_PATH", tmp_path / "cache.json")
    public_attention._put_cache(
        public_attention.DiscussionResult(True, 50, False, "stale", "athlete medal"),
        30,
    )
    monkeypatch.setattr(public_attention, "REDDIT_MIN_REQUEST_INTERVAL_SECONDS", 0)
    session = FakeSession(FakeResponse(RSS_LOW))
    result = public_attention.verify_reddit_discussions(
        "athlete medal", 30, session=session
    )
    assert result.result_count == 2
    assert result.low_discussion is True


def test_news_coverage_does_not_block_reddit_gap():
    discussion = public_attention.DiscussionResult(True, 0, True, "ok", "athlete medal")
    result = public_attention.evaluate_public_attention(
        {"social_result_count": 0, "coverage_gap": False},
        discussion,
        SimpleNamespace(),
    )
    assert result["public_attention_gap"] is True
    assert result["social_visibility_gap"] is None
