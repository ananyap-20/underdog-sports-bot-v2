"""Offline tests for article-page enrichment (no network)."""

from types import SimpleNamespace

import requests

import run_pipeline
from src import article_enricher
from src.article_enricher import extract_article_text, fetch_article_text


BODY_1 = (
    "Sarvesh Kushare cleared the bar at the state meet after years of "
    "practising in a village near Kolhapur without proper equipment."
)
BODY_2 = (
    "He started off with jugaad and makeshift pits of corn husk, "
    "landing on piles of husk because the school had no landing mats."
)
BODY_3 = (
    "His coach said the athlete kept training every morning before "
    "school and finally earned selection for the national squad."
)

ARTICLE_PAGE = f"""
<html><body>
  <nav><p>Home | Sports | Cricket | Football | Athletics | More sections</p></nav>
  <article>
    <h1>High jumper's rise</h1>
    <p>{BODY_1}</p>
    <p>{BODY_2}</p>
    <p>Also Read: Makeshift tents and improvised facilities at another event</p>
    <p>{BODY_3}</p>
  </article>
  <aside>
    <p>Trending: A cricketer trained with limited funding and no facilities at all.</p>
  </aside>
  <footer><p>Copyright 2026 Example Media. All rights reserved worldwide.</p></footer>
</body></html>
"""


class FakeResponse:
    def __init__(self, body="", status=200, content_type="text/html; charset=utf-8"):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self._body = body.encode("utf-8")

    def iter_content(self, size):
        yield self._body

    def close(self):
        pass


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


def no_spacing(monkeypatch):
    monkeypatch.setattr(article_enricher, "PER_HOST_SPACING_SECONDS", 0)


# ------------------------------------------------------------
# Extraction
# ------------------------------------------------------------

def test_extracts_body_and_drops_boilerplate():
    text = extract_article_text(ARTICLE_PAGE)

    assert "makeshift pits of corn husk" in text
    assert "Also Read" not in text
    assert "Trending" not in text
    assert "Copyright" not in text
    assert "Sports | Cricket" not in text


def test_evidence_in_sidebar_or_related_links_is_not_used():
    story = SimpleNamespace(
        _source_text=extract_article_text(ARTICLE_PAGE).replace(BODY_2, "")
    )

    # "limited funding" appears only in the <aside>; "makeshift tents ...
    # improvised facilities" only in an "Also Read" line.
    assert run_pipeline.find_resource_evidence(story) is None


def test_json_ld_article_body_fallback():
    body = "Full story text. " * 40 + "They trained on dirt pitches."

    page = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"NewsArticle","articleBody":"' + body + '"}'
        "</script></head><body><div>JS shell</div></body></html>"
    )

    assert "dirt pitches" in extract_article_text(page)


# ------------------------------------------------------------
# Failure handling: failures are never evidence
# ------------------------------------------------------------

def test_google_news_redirect_is_not_fetched():
    session = FakeSession(error=AssertionError("must not fetch"))

    result = fetch_article_text(
        "https://news.google.com/rss/articles/abc", session=session
    )

    assert not result.ok
    assert result.status == "google_news_redirect"
    assert result.text == ""
    assert session.calls == 0


def test_timeout_http_error_and_non_html(monkeypatch):
    no_spacing(monkeypatch)
    url = "https://example.com/a"

    timeout = fetch_article_text(url, FakeSession(error=requests.Timeout()))
    assert (timeout.ok, timeout.status, timeout.text) == (False, "timeout", "")

    forbidden = fetch_article_text(url, FakeSession(FakeResponse(status=403)))
    assert (forbidden.ok, forbidden.status) == (False, "http_403")

    pdf = fetch_article_text(
        url, FakeSession(FakeResponse("x", content_type="application/pdf"))
    )
    assert (pdf.ok, pdf.status) == (False, "not_html")


def test_thin_page_is_empty_body_not_evidence(monkeypatch):
    no_spacing(monkeypatch)

    page = "<html><body><article><p>Subscribe to read the full story now.</p></article></body></html>"

    result = fetch_article_text(
        "https://example.com/paywalled", FakeSession(FakeResponse(page))
    )

    assert not result.ok
    assert result.status == "empty_body"
    assert result.text == ""


def test_success_is_cached_and_failure_is_not(monkeypatch, tmp_path):
    no_spacing(monkeypatch)
    url = "https://example.com/story"

    first_session = FakeSession(FakeResponse(ARTICLE_PAGE))
    first = fetch_article_text(url, first_session, cache_dir=tmp_path)

    assert first.ok and not first.from_cache

    second_session = FakeSession(error=AssertionError("cache should be used"))
    second = fetch_article_text(url, second_session, cache_dir=tmp_path)

    assert second.ok and second.from_cache and second_session.calls == 0

    fail_url = "https://example.com/fail"
    fetch_article_text(fail_url, FakeSession(FakeResponse(status=500)), cache_dir=tmp_path)

    assert article_enricher._read_cache(tmp_path, fail_url) is None


# ------------------------------------------------------------
# Pipeline integration
# ------------------------------------------------------------

def _article(url="https://example.com/sarvesh"):
    return {
        "title": "Indian high jumper wins state title",
        "description": "The athlete won the championship final with a record jump.",
        "content": "The Indian athlete won the title ... [+1200 chars]",
        "url": url,
        "publishedAt": "2026-09-15T00:00:00Z",
        "source": {"name": "Example"},
    }


def test_enrichment_finds_b_evidence_missing_from_snippet(monkeypatch, tmp_path):
    monkeypatch.setattr(run_pipeline, "PAGE_CACHE_DIR", tmp_path)
    no_spacing(monkeypatch)

    monkeypatch.setattr(
        run_pipeline,
        "fetch_article_text",
        lambda url, session=None, cache_dir=None: article_enricher.PageResult(
            url, True, "ok", text=extract_article_text(ARTICLE_PAGE)
        ),
    )

    without = run_pipeline.build_candidates([_article()], enrich=False)
    assert not any(run_pipeline.has_resource_evidence(s) for s in without)

    with_enrichment = run_pipeline.build_candidates([_article()], enrich=True)
    story = with_enrichment[0]

    assert run_pipeline.has_resource_evidence(story)
    assert run_pipeline.find_resource_evidence(story) == "makeshift pits"
    assert story._resource_evidence_origin == "page"


def test_failed_fetch_leaves_story_unchanged(monkeypatch):
    monkeypatch.setattr(
        run_pipeline,
        "fetch_article_text",
        lambda url, session=None, cache_dir=None: article_enricher.PageResult(
            url, False, "timeout", detail="Request timed out."
        ),
    )

    before = run_pipeline.build_candidates([_article()], enrich=False)
    after = run_pipeline.build_candidates([_article()], enrich=True)

    assert [s._source_text for s in before] == [s._source_text for s in after]
    assert not any(run_pipeline.has_resource_evidence(s) for s in after)
    assert after[0]._page_status == "timeout"


def test_family_sacrifice_alone_is_still_not_b(monkeypatch):
    page_text = (
        "His parents made significant sacrifices so he could pursue the "
        "sport, and the family stood by him through every difficult season "
        "of his early career as a promising young athlete in the district. "
    ) * 3

    monkeypatch.setattr(
        run_pipeline,
        "fetch_article_text",
        lambda url, session=None, cache_dir=None: article_enricher.PageResult(
            url, True, "ok", text=page_text
        ),
    )

    stories = run_pipeline.build_candidates([_article()], enrich=True)

    assert not any(run_pipeline.has_resource_evidence(s) for s in stories)

def test_jugaad_must_be_connected_to_resource_in_same_sentence():
    story = SimpleNamespace(
        _source_text=(
            "The coach praised his jugaad approach. "
            "The athlete later attended training at the academy."
        )
    )

    assert run_pipeline.find_resource_evidence(story) is None




def test_amateur_alone_is_not_f_narrative():
    story = SimpleNamespace(
        _source_title="Amateur athlete wins a national title",
        _source_description="",
        _source_content="The athlete competes at amateur level.",
    )

    assert run_pipeline.find_f_narrative_evidence(story) is None


def test_amateur_with_strong_underdog_context_is_f_narrative():
    story = SimpleNamespace(
        _source_title="Amateur athlete from a village wins national title",
        _source_description="A grassroots success story from a small town.",
        _source_content="The athlete trained locally before reaching the national stage.",
    )

    evidence = run_pipeline.find_f_narrative_evidence(story)
    assert evidence in {"from a village", "grassroots", "small-town"}


def test_jugaad_and_resource_in_same_sentence_is_valid_b_evidence():
    story = SimpleNamespace(
        _source_text=(
            "The athlete built a makeshift landing pit using jugaad "
            "before the district meet."
        )
    )

    assert run_pipeline.find_resource_evidence(story) == "makeshift landing pit"
