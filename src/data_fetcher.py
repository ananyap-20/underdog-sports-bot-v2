"""Fetch and lightly pre-filter Indian sports discovery candidates.

NewsAPI is a retrieval engine, not a semantic sports classifier.
We therefore use several targeted queries and then apply a conservative
relevance filter before the underdog scorer sees the articles.
"""

from __future__ import annotations

import json
import re

from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from config import settings


# ---------------------------------------------------------------------------
# INDIA / INDIAN LOCATION SIGNALS
# ---------------------------------------------------------------------------

INDIA_PATTERNS = [
    r"\bindia\b",
    r"\bindian\b",
    r"\bindians\b",

    # Indian states
    r"\bandhra pradesh\b",
    r"\barunachal pradesh\b",
    r"\bassam\b",
    r"\bbihar\b",
    r"\bchhattisgarh\b",
    r"\bgoa\b",
    r"\bgujarat\b",
    r"\bharyana\b",
    r"\bhimachal pradesh\b",
    r"\bjharkhand\b",
    r"\bkarnataka\b",
    r"\bkerala\b",
    r"\bmadhya pradesh\b",
    r"\bmaharashtra\b",
    r"\bmanipur\b",
    r"\bmeghalaya\b",
    r"\bmizoram\b",
    r"\bnagaland\b",
    r"\bodisha\b",
    r"\bpunjab\b",
    r"\brajasthan\b",
    r"\bsikkim\b",
    r"\btamil nadu\b",
    r"\btelangana\b",
    r"\btripura\b",
    r"\buttar pradesh\b",
    r"\buttarakhand\b",
    r"\bwest bengal\b",

    # Major territories / locations
    r"\bdelhi\b",
    r"\bjammu and kashmir\b",
    r"\bladakh\b",
    r"\bchandigarh\b",
]


# ---------------------------------------------------------------------------
# SPORTS SIGNALS
# ---------------------------------------------------------------------------

SPORT_PATTERNS = [
    r"\bhockey\b",
    r"\bfootball\b",
    r"\bcricket\b",
    r"\bbadminton\b",
    r"\btennis\b",
    r"\bathletics\b",
    r"\bboxing\b",
    r"\bwrestling\b",
    r"\bswimming\b",
    r"\barchery\b",
    r"\bolympian\b",
    r"\bolympics?\b",
    r"\basian games\b",
    r"\bsports?\b",
]


# ---------------------------------------------------------------------------
# NEWSAPI REQUEST
# ---------------------------------------------------------------------------

def _newsapi_request(
    query: str,
    days_back: int,
) -> list[dict]:

    if not settings.NEWSAPI_KEY:
        raise ValueError(
            "NEWSAPI_KEY is missing. Put a valid key in the project .env file."
        )

    from_date = (
        datetime.now(timezone.utc)
        - timedelta(days=days_back)
    ).strftime("%Y-%m-%d")

    params = {
        "q": query,
        "from": from_date,
        "language": settings.FETCH_LANGUAGE,
        "sortBy": "publishedAt",
        "pageSize": settings.FETCH_PAGE_SIZE,
        "apiKey": settings.NEWSAPI_KEY,
    }

    response = requests.get(
        settings.NEWSAPI_ENDPOINT,
        params=params,
        timeout=20,
    )

    if response.status_code == 401:
        raise RuntimeError(
            "NewsAPI returned 401 Unauthorized. Your API key is invalid, "
            "expired, disabled, or not being accepted by NewsAPI."
        )

    response.raise_for_status()

    data = response.json()

    if data.get("status") != "ok":
        raise RuntimeError(
            f"NewsAPI error: "
            f"{data.get('code', 'unknown')} - "
            f"{data.get('message', 'unknown error')}"
        )

    return data.get("articles", [])


# ---------------------------------------------------------------------------
# ARTICLE TEXT
# ---------------------------------------------------------------------------

def _article_text(article: dict) -> str:
    return " ".join(
        str(article.get(key) or "")
        for key in (
            "title",
            "description",
            "content",
        )
    ).lower()


def _matches_any(
    text: str,
    patterns: list[str],
) -> bool:

    return any(
        re.search(pattern, text)
        for pattern in patterns
    )


# ---------------------------------------------------------------------------
# RELEVANCE FILTER
# ---------------------------------------------------------------------------

def is_indian_sports_article(
    article: dict,
) -> bool:
    """Reject obvious non-Indian/non-sports noise.

    This filter only answers:

        Is this probably an Indian sports article?

    It does NOT decide whether the story is an underdog story.
    """

    text = _article_text(article)

    return (
        _matches_any(text, INDIA_PATTERNS)
        and _matches_any(text, SPORT_PATTERNS)
    )


# ---------------------------------------------------------------------------
# DEDUPLICATION
# ---------------------------------------------------------------------------

def _dedupe_key(article: dict) -> str:
    return (
        article.get("url")
        or article.get("title")
        or ""
    ).strip().lower()


# ---------------------------------------------------------------------------
# SINGLE QUERY
# ---------------------------------------------------------------------------

def fetch_from_newsapi(
    query: str = "India sports team won",
    days_back: int = 7,
) -> list[dict]:

    articles = _newsapi_request(
        query,
        days_back,
    )

    print(
        f"Fetched {len(articles)} articles "
        f"for query: '{query}'"
    )

    return articles


# ---------------------------------------------------------------------------
# BROAD DISCOVERY
# ---------------------------------------------------------------------------

def fetch_discovery_queries(
    queries: list[str] | None = None,
    days_back: int = 7,
) -> list[dict]:
    """Run multiple targeted queries, filter obvious noise, and deduplicate."""

    queries = (
        queries
        or settings.DISCOVERY_QUERIES
    )

    all_articles: list[dict] = []
    seen: set[str] = set()

    raw_count = 0
    relevant_count = 0

    for query in queries:

        try:
            articles = _newsapi_request(
                query,
                days_back,
            )

        except Exception as exc:
            print(
                f"[WARN] Query failed: {query}\n"
                f"       {exc}"
            )
            continue

        raw_count += len(articles)

        for article in articles:

            if not is_indian_sports_article(article):
                continue

            relevant_count += 1

            key = _dedupe_key(article)

            if key and key not in seen:
                seen.add(key)
                all_articles.append(article)

    print(
        f"Discovery: {raw_count} raw -> "
        f"{relevant_count} Indian sports matches -> "
        f"{len(all_articles)} unique articles"
    )

    return all_articles


# ---------------------------------------------------------------------------
# SAVE RAW DATA
# ---------------------------------------------------------------------------

def save_raw(
    articles: list[dict],
    filename: str | None = None,
) -> Path:

    if filename is None:
        filename = (
            f"raw_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            f".json"
        )

    path = settings.RAW_DATA_DIR / filename

    path.write_text(
        json.dumps(
            articles,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        f"Saved {len(articles)} articles -> {path}"
    )

    return path