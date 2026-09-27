import pytest
from types import SimpleNamespace

import src.public_attention as pa


def make_json_response(rows, status=200):
    class R:
        status_code = status
        headers = {}

        def json(self):
            return {"data": {"children": [{"data": row} for row in rows]}}
    return R()


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.response


def setup_module(module):
    pa.REDDIT_MIN_REQUEST_INTERVAL_SECONDS = 0
    pa.REDDIT_MAX_RETRIES_429 = 0


def test_zero_reddit_posts_is_low():
    result = pa._verify_json(
        "Test Athlete wins medal",
        30,
        FakeSession(make_json_response([])),
        "token",
    )
    assert result.verification_available is True
    assert result.result_count == 0
    assert result.low_discussion is True
    assert result.popularity == "low"


def test_medium_reddit_activity_is_not_low():
    rows = [{"num_comments": 6, "score": 20} for _ in range(2)]
    result = pa._verify_json(
        "Test Athlete wins medal",
        30,
        FakeSession(make_json_response(rows)),
        "token",
    )
    assert result.result_count == 2
    assert result.total_comments == 12
    assert result.top_score == 20
    assert result.low_discussion is True


def test_high_reddit_activity_is_not_low():
    rows = [{"num_comments": 20, "score": 150}]
    result = pa._verify_json(
        "Test Athlete wins medal",
        30,
        FakeSession(make_json_response(rows)),
        "token",
    )
    assert result.popularity == "high"
    assert result.low_discussion is False


def test_unavailable_is_unknown():
    class R:
        status_code = 429
        headers = {}
    result = pa._verify_json(
        "Test Athlete wins medal",
        30,
        FakeSession(R()),
        "token",
    )
    assert result.verification_available is False
    assert result.low_discussion is None


def test_evaluator_uses_reddit_only_for_f():
    story = SimpleNamespace()
    coverage = {"coverage_gap": False, "social_result_count": 0}
    discussion = pa.DiscussionResult(True, 0, True, "ok", "x", 0, 0, "low")
    out = pa.evaluate_public_attention(coverage, discussion, story)
    assert out["public_attention_gap"] is True
