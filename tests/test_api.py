import json
import pytest
from fastapi.testclient import TestClient
from api import service as svc
from api.main import app

client = TestClient(app)


@pytest.fixture
def demo(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "PROCESSED", tmp_path)  # no real data
    monkeypatch.setenv("UNDERDOG_DEMO_DATA", "1")
    monkeypatch.setattr(svc, "SUPPORT_FILE", tmp_path / "support.json")


def test_no_data_gives_readable_404(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "PROCESSED", tmp_path)
    monkeypatch.delenv("UNDERDOG_DEMO_DATA", raising=False)
    r = client.get("/api/stories")
    assert r.status_code == 404 and "run_pipeline.py" in r.json()["detail"]
    assert "Traceback" not in r.text and "C:\\" not in r.text


def test_list_filter_search_sort(demo):
    d = client.get("/api/stories").json()
    assert d["total"] == 4 and d["freshness"]["is_demo"] is True
    assert client.get("/api/stories?category=B").json()["total"] == 2
    assert client.get("/api/stories?q=athlete c").json()["total"] == 1
    assert client.get("/api/stories?q=zzzz").json()["items"] == []
    assert client.get("/api/stories?attention=unknown").json()["total"] == 1
    assert client.get("/api/stories?category=X").status_code == 422
    top = client.get("/api/stories?sort=score").json()["items"][0]
    assert top["scores"]["combined"] == 0.71


def test_missing_fields_stay_null_and_unknown_attention(demo):
    items = client.get("/api/stories?attention=unknown").json()["items"]
    assert items[0]["description"] is None
    assert items[0]["attention"]["reddit_discussion_count"] is None


def test_detail_and_404(demo):
    sid = client.get("/api/stories").json()["items"][0]["id"]
    d = client.get(f"/api/stories/{sid}").json()
    assert d["support_links"] == []
    assert client.get("/api/stories/nope").status_code == 404


def test_malformed_row_does_not_crash():
    out = svc.serialize({"url": "javascript:alert(1)", "category": "ZZ", "entities": [1, "ok"]})
    assert out["url"] is None and out["category"] is None and out["entities"] == ["ok"]


def _link(**kw):
    base = {"recipient": "Demo Athlete A", "relationship": "official page of the athlete",
            "title": "Official fund", "url": "https://example.org/fund", "category": "donate_campaign",
            "verification_status": "verified", "evidence_url": "https://example.org/proof",
            "last_verified": "2026-10-01"}
    base.update(kw)
    return base


def test_support_link_rules(demo):
    a = svc.serialize({"url": "https://x.test/a", "entities": ["Demo Athlete A"]})
    assert svc.validate_support_link(_link(), a)
    assert not svc.validate_support_link(_link(recipient="Someone Else"), a)  # wrong recipient
    assert not svc.validate_support_link(_link(verification_status="unverified"), a)
    assert not svc.validate_support_link(_link(url="javascript:x"), a)
    assert not svc.validate_support_link(_link(evidence_url=None), a)
    assert not svc.validate_support_link(_link(expired=True), a)
    assert svc.validate_support_link(_link(recipient="Other", story_ids=[a["id"]]), a)


def test_verified_link_only_on_matching_story(demo, tmp_path):
    (tmp_path / "support.json").write_text(json.dumps({"links": [_link()]}))
    items = client.get("/api/stories").json()["items"]
    by = {i["entities"][0]: i["id"] for i in items}
    assert len(client.get(f"/api/stories/{by['Demo Athlete A']}").json()["support_links"]) == 1
    assert client.get(f"/api/stories/{by['Demo Team B']}").json()["support_links"] == []


def test_methodology_matches_code_weights():
    m = client.get("/api/methodology").json()
    assert m["score_formulas"][1]["weights"]["public_attention_gap"] == 0.20


def test_save_run_outputs_keeps_stats(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src import backend_store as bs
    monkeypatch.setattr(bs, "_project_root", lambda: tmp_path)
    bs.save_run_outputs([], days_back=7, stats={"articles_scored": 10, "qualified": 0})
    saved = json.loads((tmp_path / "data" / "processed" / "latest_qualified.json").read_text())
    assert saved["pipeline_stats"]["articles_scored"] == 10


def test_unavailable_reddit_check_is_unknown_not_discussion_found():
    row = {"reddit_discussion_count": 0, "reddit_discussion_gap": False,
           "public_attention_verification": "Reddit discussion verification unavailable: HTTP 429."}
    assert svc.attention_status(row) == "unknown"
    assert svc.attention_status({"reddit_discussion_count": 0, "reddit_discussion_gap": True,
                                 "public_attention_verification": "ok"}) == "gap_found"
    assert svc.attention_status({"reddit_discussion_count": 4, "reddit_discussion_gap": False,
                                 "public_attention_verification": "ok"}) == "discussion_found"


def test_image_url_only_http_and_defaults_null():
    assert svc.serialize({"url": "https://x.test/a", "image_url": "javascript:x"})["image_url"] is None
    assert svc.serialize({"url": "https://x.test/a"})["image_url"] is None
    assert svc.serialize({"url": "https://x.test/a", "image_url": "https://img.test/p.jpg"})["image_url"] == "https://img.test/p.jpg"
