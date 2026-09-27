from types import SimpleNamespace

from src.backend_store import serialize_story, save_run_outputs


def test_serialize_story_contains_frontend_fields(tmp_path, monkeypatch):
    story = SimpleNamespace(
        title="Test athlete wins",
        url="https://example.com/story",
        entities=["Test Athlete"],
        achievement_score=0.75,
        underdog_score=0.25,
        combined_score=0.61,
        resource_evidence=True,
        _resource_evidence_origin="page",
        _resource_evidence="makeshift facility",
        _f_narrative_evidence="makeshift facility",
        public_attention_gap_score=1.0,
        reddit_discussion_count=0,
        reddit_discussion_gap=True,
        reddit_total_comments=0,
        reddit_top_score=0,
        reddit_popularity="low",
        known_audience_size=None,
        coverage_result_count=50,
        coverage_news_result_count=49,
        coverage_domains=["example.com"],
        institutional_sources=[],
        social_sources=[],
        public_attention_verification="ok",
    )
    row = serialize_story("B+F", story, lambda s, c: "caption")
    assert row["category"] == "B+F"
    assert row["reddit_discussion_gap"] is True
    assert row["caption"] == "caption"


def test_save_run_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.backend_store._project_root", lambda: tmp_path)
    story = SimpleNamespace(
        title="Test athlete",
        url="https://example.com",
        entities=[],
        achievement_score=1.0,
        underdog_score=0.2,
        combined_score=0.8,
        resource_evidence=True,
        _resource_evidence_origin="page",
        _resource_evidence="dirt ground",
        _f_narrative_evidence="dirt ground",
        public_attention_gap_score=1.0,
        reddit_discussion_count=0,
        reddit_discussion_gap=True,
        reddit_total_comments=0,
        reddit_top_score=0,
        reddit_popularity="low",
        known_audience_size=None,
        coverage_result_count=2,
        coverage_news_result_count=2,
        coverage_domains=["example.com"],
        institutional_sources=[],
        social_sources=[],
        public_attention_verification="ok",
    )
    paths = save_run_outputs([("B+F", story)], days_back=30, generate_caption_fn=lambda s, c: "caption")
    assert (tmp_path / "data" / "processed" / "latest_qualified.json").exists()
    assert (tmp_path / "data" / "processed" / "run_history.jsonl").exists()
    assert paths["latest_qualified"].endswith("latest_qualified.json")
