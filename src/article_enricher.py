"""
Article-page enrichment.

NewsAPI returns only a title, a short description and ~200 characters of
truncated content. Concrete resource evidence ("makeshift pits of corn husk")
is often deeper in the article body. This module fetches the publisher page
and extracts the body text so the B/F evidence detectors can see it.

Rules this module enforces:

    - A failed or partial fetch is NEVER evidence. It returns ok=False
      and empty text; callers must not treat that as a negative or positive.
    - No text is ever invented, summarised or paraphrased. Output is
      verbatim paragraph text from the page.
    - Only article-body paragraphs are returned. Navigation, sidebars,
      footers, forms, figures and "Also read / Related" lines are dropped,
      so links to OTHER stories cannot leak evidence into this one.
    - Google News links are redirects, not publisher pages, and are skipped.
    - Paywalls / bot blocks (401/403/429) are reported, not bypassed.
    - This module knows nothing about coverage verification.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests


USER_AGENT = (
    "underdog-sports-bot/2.0 "
    "(research project; article text enrichment)"
)

REQUEST_TIMEOUT = 15
MAX_HTML_BYTES = 2_000_000
MAX_TEXT_CHARS = 20_000

# Below this many characters we assume the page is a paywall stub,
# a JS-rendered shell, or otherwise not a usable article body.
MIN_BODY_CHARS = 300

# Minimum length for a paragraph to count (drops breadcrumbs / captions).
MIN_PARAGRAPH_CHARS = 40

PER_HOST_SPACING_SECONDS = 1.0
CACHE_TTL_SECONDS = 7 * 24 * 3600

# Pages that are never article bodies.
UNFETCHABLE_HOSTS = (
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
    "t.co",
)

_SKIP_TAGS = {
    "script", "style", "noscript", "nav", "footer", "aside",
    "form", "header", "iframe", "svg", "template", "figure",
}

_BOILERPLATE_START = re.compile(
    r"^\s*(also read|read more|read also|also see|also watch|related|"
    r"trending|click here|follow us|subscribe|advertisement|"
    r"copyright|©|sign up|download the)\b",
    re.IGNORECASE,
)

_last_request_at: dict[str, float] = {}


# ============================================================
# RESULT TYPE
# ============================================================

@dataclass
class PageResult:
    url: str
    ok: bool
    status: str
    text: str = ""
    detail: str = ""
    from_cache: bool = False


# ============================================================
# HTML -> BODY TEXT
# ============================================================

def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class _PageParser(HTMLParser):
    """Collects <p> text, tracking whether it sits inside <article>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.article_depth = 0
        self.in_p = False
        self._buf: list[str] = []
        self._in_ld = False
        self._ld_buf: list[str] = []
        self.all_paragraphs: list[str] = []
        self.article_paragraphs: list[str] = []
        self.ld_blocks: list[str] = []

    def _flush_paragraph(self):
        text = _normalize_space("".join(self._buf))
        self._buf = []

        if len(text) < MIN_PARAGRAPH_CHARS:
            return

        if _BOILERPLATE_START.match(text):
            return

        self.all_paragraphs.append(text)

        if self.article_depth > 0:
            self.article_paragraphs.append(text)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            script_type = (dict(attrs).get("type") or "").lower()

            if "ld+json" in script_type:
                self._in_ld = True
                self._ld_buf = []

            self.skip_depth += 1
            return

        if tag in _SKIP_TAGS:
            self.skip_depth += 1
            return

        if tag == "article":
            self.article_depth += 1

        elif tag == "p" and self.skip_depth == 0:
            if self.in_p:
                self._flush_paragraph()

            self.in_p = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "script":
            if self._in_ld:
                self.ld_blocks.append("".join(self._ld_buf))
                self._in_ld = False

            if self.skip_depth:
                self.skip_depth -= 1

            return

        if tag in _SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1

            return

        if tag == "article":
            if self.article_depth:
                self.article_depth -= 1

        elif tag == "p" and self.in_p:
            self.in_p = False
            self._flush_paragraph()

    def handle_data(self, data):
        if self._in_ld:
            self._ld_buf.append(data)
            return

        if self.in_p and self.skip_depth == 0:
            self._buf.append(data)


def _find_article_bodies(node) -> list[str]:
    """Recursively collect 'articleBody' strings from JSON-LD."""

    found: list[str] = []

    if isinstance(node, dict):
        body = node.get("articleBody")

        if isinstance(body, str):
            found.append(body)

        for value in node.values():
            found.extend(_find_article_bodies(value))

    elif isinstance(node, list):
        for item in node:
            found.extend(_find_article_bodies(item))

    return found


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    unique = []

    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    return unique


def extract_article_text(page_html: str) -> str:
    """Return verbatim article-body text, or '' if none can be found."""

    parser = _PageParser()

    try:
        parser.feed(page_html)
        parser.close()
    except Exception:
        # Malformed HTML: use whatever was collected so far.
        pass

    article_paragraphs = _dedupe_keep_order(parser.article_paragraphs)
    all_paragraphs = _dedupe_keep_order(parser.all_paragraphs)

    # Prefer paragraphs inside <article>; fall back to all
    # non-boilerplate paragraphs if <article> is missing/thin.
    if sum(len(p) for p in article_paragraphs) >= MIN_BODY_CHARS:
        body = " ".join(article_paragraphs)
    else:
        body = " ".join(all_paragraphs)

    # JSON-LD articleBody is the publisher's own structured copy of
    # the article, so use it when it is more complete.
    for block in parser.ld_blocks:
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue

        for candidate in _find_article_bodies(data):
            candidate = _normalize_space(
                html_lib.unescape(re.sub(r"<[^>]+>", " ", candidate))
            )

            if len(candidate) > len(body):
                body = candidate

    return body[:MAX_TEXT_CHARS]


# ============================================================
# CACHE
# ============================================================

def _cache_file(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _read_cache(cache_dir: Path | None, url: str) -> str | None:
    if cache_dir is None:
        return None

    path = _cache_file(cache_dir, url)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        if time.time() - float(data["fetched_at"]) > CACHE_TTL_SECONDS:
            return None

        text = data["text"]

        return text if isinstance(text, str) and text else None

    except Exception:
        return None


def _write_cache(cache_dir: Path | None, url: str, text: str) -> None:
    """Only successful extractions are cached; failures never are."""

    if cache_dir is None:
        return

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)

        _cache_file(cache_dir, url).write_text(
            json.dumps(
                {"url": url, "fetched_at": time.time(), "text": text},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


# ============================================================
# FETCH
# ============================================================

def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _respect_spacing(host: str) -> None:
    last = _last_request_at.get(host)

    if last is not None:
        wait = PER_HOST_SPACING_SECONDS - (time.monotonic() - last)

        if wait > 0:
            time.sleep(wait)

    _last_request_at[host] = time.monotonic()


def fetch_article_text(
    url: str,
    session: requests.Session | None = None,
    cache_dir: Path | None = None,
) -> PageResult:
    """
    Fetch a publisher page and return its body text.

    Never raises. Every failure is reported through PageResult.status
    with ok=False and empty text.
    """

    url = (url or "").strip()

    if not url:
        return PageResult(url, False, "no_url", detail="Article has no URL.")

    try:
        parsed = urlparse(url)
    except Exception:
        return PageResult(url, False, "bad_url", detail="Unparseable URL.")

    if parsed.scheme not in ("http", "https"):
        return PageResult(url, False, "bad_url", detail="Not an http(s) URL.")

    host = _host(url)

    if host == "news.google.com" or host.endswith(".google.com"):
        return PageResult(
            url,
            False,
            "google_news_redirect",
            detail=(
                "Google News links are redirects, not publisher pages; "
                "no page was fetched."
            ),
        )

    if any(host == h or host.endswith("." + h) for h in UNFETCHABLE_HOSTS):
        return PageResult(
            url,
            False,
            "unfetchable_host",
            detail=f"{host} is not an article publisher.",
        )

    cached = _read_cache(cache_dir, url)

    if cached:
        return PageResult(url, True, "ok", text=cached, from_cache=True)

    session = session or requests.Session()

    _respect_spacing(host)

    response = None

    try:
        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
            stream=True,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return PageResult(
                url,
                False,
                f"http_{response.status_code}",
                detail=f"Publisher returned HTTP {response.status_code}.",
            )

        content_type = (response.headers.get("Content-Type") or "").lower()

        if content_type and "html" not in content_type:
            return PageResult(
                url,
                False,
                "not_html",
                detail=f"Unexpected content type: {content_type}",
            )

        chunks = []
        size = 0

        for chunk in response.iter_content(65536):
            size += len(chunk)

            if size > MAX_HTML_BYTES:
                return PageResult(
                    url,
                    False,
                    "too_large",
                    detail="Page exceeded the size limit.",
                )

            chunks.append(chunk)

        encoding = (
            response.encoding if "charset" in content_type else None
        ) or "utf-8"

        page_html = b"".join(chunks).decode(encoding, errors="replace")

    except requests.Timeout:
        return PageResult(url, False, "timeout", detail="Request timed out.")

    except requests.RequestException as exc:
        return PageResult(
            url, False, "network_error", detail=f"Network error: {exc}"
        )

    except Exception as exc:
        return PageResult(url, False, "error", detail=f"Unexpected error: {exc}")

    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    text = extract_article_text(page_html)

    if len(text) < MIN_BODY_CHARS:
        return PageResult(
            url,
            False,
            "empty_body",
            detail=(
                f"Only {len(text)} characters of article text found "
                "(paywall, JS-rendered page, or not an article)."
            ),
        )

    _write_cache(cache_dir, url, text)

    return PageResult(url, True, "ok", text=text)