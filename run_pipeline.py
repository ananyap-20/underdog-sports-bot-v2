"""
End-to-end Indian sports underdog discovery pipeline.

Categories:

    B+F = Genuine resource disadvantage + verified low Reddit attention
    B   = Genuine resource disadvantage
    F   = Verified low Reddit attention + genuine underdog narrative

Important rules:

    - Coverage alone never creates F.
    - Achievement alone never creates F.
    - Status gap alone never creates F.
    - Family sacrifice alone never creates B or F.
    - Social platforms are NOT independent media publishers.
    - Reddit public discussion is the deciding attention signal for F.
    - Google News coverage is retained as a diagnostic and never blocks F.
    - Known high follower/subscriber counts can block an F classification only when
      the Reddit attention evaluator explicitly exposes that signal.
    - Unavailable Reddit signals are never treated as low attention.
    - Official sports bodies are tracked separately from news media.
    - Resource evidence can come directly from article text.
    - NewsAPI quota exhaustion is handled locally.
    - Google News is used as discovery fallback.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from xml.etree import ElementTree

import requests

from config import settings
from src.nlp_extractor import score_article
from src.article_enricher import fetch_article_text
from src.poster import process_story, generate_caption
from src.public_attention import (
    evaluate_public_attention,
    verify_reddit_discussions,
)
from src.backend_store import save_run_outputs


# ============================================================
# CONFIGURATION
# ============================================================

NEWSAPI_ENDPOINT = settings.NEWSAPI_ENDPOINT
NEWSAPI_KEY = settings.NEWSAPI_KEY

NEWSAPI_RETRIES = 2
NEWSAPI_REQUEST_SPACING = 1.5

MIN_ACHIEVEMENT_SCORE = 0.50

# Keep a large verification pool so the site can collect at least several stories.
MAX_COVERAGE_CANDIDATES = 200

# Recent discovery cache.
CACHE_MAX_AGE_MINUTES = 15

# Google News fallback cache.
GOOGLE_FALLBACK_CACHE_MAX_AGE_MINUTES = 30

# If local data is smaller than this, supplement it with
# Google News discovery.
MIN_USEFUL_LOCAL_ARTICLES = 50

# ============================================================
# COVERAGE THRESHOLDS
# ============================================================
#
# A media coverage gap requires:
#
#   <= 2 independent NEWS publishers
#   AND
#   <= 12 news results
#
# Institutional sources and social platforms are NOT counted
# as independent news publishers.
#

MAX_COVERAGE_NEWS_DOMAINS = 2
MAX_COVERAGE_NEWS_RESULTS = 12

COVERAGE_REQUEST_TIMEOUT = 15
COVERAGE_REQUEST_SPACING = 0.35

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search"
)

CACHE_PATH = (
    settings.RAW_DATA_DIR
    / "discovery_cache.json"
)

GOOGLE_FALLBACK_CACHE_PATH = (
    settings.RAW_DATA_DIR
    / "google_fallback_cache.json"
)

NEWSAPI_QUOTA_STATE_PATH = (
    settings.RAW_DATA_DIR
    / "newsapi_quota_state.json"
)

# ============================================================
# ARTICLE-PAGE ENRICHMENT
# ============================================================
#
# NewsAPI snippets are truncated. Up to this many candidate
# article pages are fetched per run so that B/resource evidence
# deeper in the article body can be detected.
#
# Search deeply enough to recover resource evidence from more candidates.
ENRICH_MAX_ARTICLES = 150

PAGE_CACHE_DIR = (
    settings.RAW_DATA_DIR
    / "page_cache"
)


# ============================================================
# DISCOVERY QUERIES
# ============================================================

DISCOVERY_QUERIES = [

    (
        '(India OR Indian) AND '
        '(athlete OR team OR club OR academy) AND '
        '("no funding" OR "without funding" OR unfunded OR '
        '"limited funding" OR underfunded OR '
        '"limited resources" OR "basic facilities" OR '
        'makeshift OR improvised OR rudimentary OR '
        'jugaad OR grassroots OR village OR amateur)'
    ),

    (
        '(India OR Indian) AND '
        '(athlete OR team OR player) AND '
        '(adversity OR hardship OR resistance OR '
        '"family resistance" OR barefoot OR dirt OR '
        '"small town" OR village OR "left home" OR '
        '"lack of opportunity" OR injury)'
    ),

    (
        '(India OR Indian) AND '
        '(athlete OR team OR player OR club) AND '
        '(overlooked OR unheralded OR unsung OR '
        'unknown OR grassroots OR amateur)'
    ),

    (
        '(India OR Indian) AND '
        '(sports OR athlete OR team OR player) AND '
        '(historic OR record OR medal OR championship OR '
        'upset OR victory OR won OR title)'
    ),

    (
        '(India OR Indian) AND '
        '(football OR hockey OR badminton OR wrestling OR '
        'boxing OR athletics OR shooting OR archery OR '
        'tennis OR cycling OR swimming OR squash OR '
        'kabaddi OR volleyball OR basketball OR weightlifting) AND '
        '(academy OR grassroots OR amateur OR village OR '
        '"small town" OR hardship OR adversity OR '
        'funding OR makeshift OR improvised)'
    ),
]


GOOGLE_FALLBACK_QUERIES = [

    (
        'Indian grassroots athlete '
        'funding hardship sport'
    ),

    (
        'Indian underdog athlete '
        'village academy sport'
    ),

    (
        'Indian overlooked athlete '
        'unsung sports medal'
    ),

    (
        'Indian athlete adversity '
        'historic achievement'
    ),

    (
        'Indian small town athlete '
        'sports championship'
    ),

    (
        'Indian amateur athlete '
        'national international medal'
    ),

    (
        'Indian women athlete '
        'grassroots hardship sport'
    ),

    (
        'Indian athlete '
        'makeshift facility jugaad sport'
    ),
]


# ============================================================
# TEXT HELPERS
# ============================================================

def _normalize_space(
    value: str,
) -> str:

    return re.sub(
        r"\s+",
        " ",
        value or "",
    ).strip()


def _normalize_title(
    value: str,
) -> str:

    value = _normalize_space(
        value
    ).lower()

    value = re.sub(
        r"[^\w\s]",
        " ",
        value,
    )

    return _normalize_space(
        value
    )


def _normalize_url(
    url: str,
) -> str:

    if not url:
        return ""

    try:
        parsed = urlparse(url)

    except Exception:
        return url.strip().lower()

    hostname = (
        parsed.hostname
        or ""
    ).lower()

    path = (
        parsed.path
        or ""
    ).rstrip("/")

    return (
        f"{hostname}{path}"
    )


def _article_text(
    article: dict,
) -> str:

    parts = [
        article.get(
            "title",
            "",
        ),
        article.get(
            "description",
            "",
        ),
        article.get(
            "content",
            "",
        ),
    ]

    return _normalize_space(
        " ".join(
            part
            for part in parts
            if part
        )
    )


# ============================================================
# RELEVANCE FILTER
# ============================================================

INDIA_PATTERNS = (
    r"\bindia\b",
    r"\bindian\b",
    r"\bmizoram\b",
    r"\bmanipur\b",
    r"\bmeghalaya\b",
    r"\bassam\b",
    r"\barunachal pradesh\b",
    r"\bnagaland\b",
    r"\btripura\b",
    r"\bsikkim\b",
    r"\bgoa\b",
    r"\bkerala\b",
    r"\btamil nadu\b",
    r"\bkarnataka\b",
    r"\bmaharashtra\b",
    r"\bgujarat\b",
    r"\brajasthan\b",
    r"\bpunjab\b",
    r"\bharyana\b",
    r"\buttar pradesh\b",
    r"\bbihar\b",
    r"\bwest bengal\b",
    r"\bodisha\b",
    r"\bjharkhand\b",
    r"\bchhattisgarh\b",
    r"\bmadhya pradesh\b",
    r"\buttarakhand\b",
    r"\bhimachal pradesh\b",
    r"\bjammu and kashmir\b",
    r"\bdelhi\b",
    r"\btelangana\b",
    r"\bandhra pradesh\b",
)

SPORT_PATTERNS = (
    r"\bsport\b",
    r"\bsports\b",
    r"\bathlete\b",
    r"\bathletes\b",
    r"\bplayer\b",
    r"\bplayers\b",
    r"\bteam\b",
    r"\bclub\b",
    r"\bfootball\b",
    r"\bsoccer\b",
    r"\bhockey\b",
    r"\bcricket\b",
    r"\bbadminton\b",
    r"\bwrestling\b",
    r"\bboxing\b",
    r"\bathletics\b",
    r"\bshooting\b",
    r"\barchery\b",
    r"\btennis\b",
    r"\bcycling\b",
    r"\bswimming\b",
    r"\bsquash\b",
    r"\btable tennis\b",
    r"\bvolleyball\b",
    r"\bbasketball\b",
    r"\bkabaddi\b",
    r"\bgolf\b",
    r"\browing\b",
    r"\bfencing\b",
    r"\bjudo\b",
    r"\bweightlifting\b",
    r"\bkarate\b",
    r"\btaekwondo\b",
    r"\bteqball\b",
    r"\bmarathon\b",
    r"\btriathlon\b",
    r"\btournament\b",
    r"\bchampionship\b",
    r"\bmedal\b",
    r"\bmatch\b",
    r"\bcoach\b",
    r"\bfinal\b",
    r"\bsemifinal\b",
    r"\bqualification\b",
)


def _matches_any(
    text: str,
    patterns: tuple[str, ...],
) -> bool:

    return any(
        re.search(
            pattern,
            text or "",
            flags=re.IGNORECASE,
        )
        for pattern in patterns
    )


def is_strict_indian_sports_article(
    article: dict,
) -> bool:
    """
    Indian context can appear anywhere in the article.

    Sports context must appear in title/description to avoid
    unrelated articles which merely mention sports later.
    """

    title = (
        article.get(
            "title",
            "",
        )
        or ""
    )

    description = (
        article.get(
            "description",
            "",
        )
        or ""
    )

    full_text = _article_text(
        article
    )

    title_description = (
        f"{title} {description}"
    )

    return (
        _matches_any(
            full_text,
            INDIA_PATTERNS,
        )
        and
        _matches_any(
            title_description,
            SPORT_PATTERNS,
        )
    )


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate_articles(
    articles: list[dict],
) -> list[dict]:

    seen_urls = set()
    seen_titles = set()

    unique = []

    for article in articles:

        url = _normalize_url(
            article.get(
                "url",
                "",
            )
        )

        title = _normalize_title(
            article.get(
                "title",
                "",
            )
        )

        if not url and not title:
            continue

        if url and url in seen_urls:
            continue

        if title and title in seen_titles:
            continue

        if url:
            seen_urls.add(
                url
            )

        if title:
            seen_titles.add(
                title
            )

        unique.append(
            article
        )

    return unique


# ============================================================
# JSON HELPERS
# ============================================================

def _write_json(
    path: Path,
    payload,
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _read_json(
    path: Path,
):

    if not path.exists():
        return None

    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return None


# ============================================================
# CACHE
# ============================================================

def _write_discovery_cache(
    articles: list[dict],
):

    _write_json(
        CACHE_PATH,
        {
            "saved_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "articles": articles,
        },
    )


def _read_discovery_cache():

    payload = _read_json(
        CACHE_PATH
    )

    if not isinstance(
        payload,
        dict,
    ):

        return (
            None,
            None,
        )

    try:

        saved_at = datetime.fromisoformat(
            payload[
                "saved_at"
            ]
        )

    except Exception:

        return (
            None,
            None,
        )

    articles = payload.get(
        "articles",
        [],
    )

    if not isinstance(
        articles,
        list,
    ):

        return (
            None,
            None,
        )

    age_minutes = (
        datetime.now(
            timezone.utc
        )
        - saved_at
    ).total_seconds() / 60

    return (
        articles,
        age_minutes,
    )


def _parse_raw_file(
    path: Path,
) -> list[dict]:

    payload = _read_json(
        path
    )

    if isinstance(
        payload,
        list,
    ):

        return [
            item
            for item in payload
            if isinstance(
                item,
                dict,
            )
        ]

    if isinstance(
        payload,
        dict,
    ):

        articles = payload.get(
            "articles",
            [],
        )

        if isinstance(
            articles,
            list,
        ):

            return [
                item
                for item in articles
                if isinstance(
                    item,
                    dict,
                )
            ]

    return []


def _load_largest_raw_cache() -> list[dict]:
    """
    Select the raw file containing the largest article set.

    This prevents a tiny later custom-query file from
    replacing a much better historical discovery dataset.
    """

    candidates = []

    for path in settings.RAW_DATA_DIR.glob(
        "*.json"
    ):

        if path.name in {
            CACHE_PATH.name,
            GOOGLE_FALLBACK_CACHE_PATH.name,
            NEWSAPI_QUOTA_STATE_PATH.name,
        }:
            continue

        articles = _parse_raw_file(
            path
        )

        if not articles:
            continue

        candidates.append(
            (
                len(articles),
                path.stat().st_mtime,
                path,
                articles,
            )
        )

    if not candidates:
        return []

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1],
        ),
        reverse=True,
    )

    count, _, selected_path, articles = (
        candidates[0]
    )

    print(
        f"[CACHE] Selected largest previous raw file: "
        f"{selected_path.name} "
        f"({count} articles)"
    )

    return articles


# ============================================================
# NEWSAPI QUOTA STATE
# ============================================================

def _read_quota_state():

    payload = _read_json(
        NEWSAPI_QUOTA_STATE_PATH
    )

    if not isinstance(
        payload,
        dict,
    ):

        return None

    return payload


def _is_newsapi_quota_blocked() -> bool:

    state = _read_quota_state()

    if not state:
        return False

    blocked_until_raw = state.get(
        "blocked_until"
    )

    if not blocked_until_raw:
        return False

    try:

        blocked_until = datetime.fromisoformat(
            blocked_until_raw
        )

    except Exception:

        return False

    now = datetime.now(
        timezone.utc
    )

    if now < blocked_until:

        print(
            "[NEWSAPI] Daily quota is known to be exhausted."
        )

        print(
            "[NEWSAPI] Skipping NewsAPI until "
            f"{blocked_until.isoformat()}."
        )

        return True

    try:

        NEWSAPI_QUOTA_STATE_PATH.unlink()

    except OSError:

        pass

    return False


def _mark_newsapi_quota_exhausted(
    reason: str,
):

    blocked_until = (
        datetime.now(
            timezone.utc
        )
        + timedelta(
            hours=24
        )
    )

    _write_json(
        NEWSAPI_QUOTA_STATE_PATH,
        {
            "blocked_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "blocked_until": blocked_until.isoformat(),
            "reason": reason,
        },
    )

    print(
        "[NEWSAPI] Saved local 24-hour quota cooldown."
    )


def _looks_like_daily_quota_exhaustion(
    message: str,
) -> bool:

    message = (
        message or ""
    ).lower()

    indicators = (
        "100 requests",
        "24 hour",
        "50 requests available",
        "exhausted",
        "daily quota",
    )

    return any(
        indicator in message
        for indicator in indicators
    )


# ============================================================
# NEWSAPI
# ============================================================

def _newsapi_request(
    session: requests.Session,
    query: str,
    days_back: int,
):
    """
    Returns:

        articles,
        success,
        rate_limited,
        error
    """

    if not NEWSAPI_KEY:

        return (
            [],
            False,
            False,
            "NEWSAPI_KEY is missing.",
        )

    if _is_newsapi_quota_blocked():

        return (
            [],
            False,
            True,
            "NewsAPI daily quota is exhausted.",
        )

    from_date = (
        datetime.now(
            timezone.utc
        )
        - timedelta(
            days=days_back
        )
    ).date().isoformat()

    params = {
        "q": query,
        "from": from_date,
        "language": settings.FETCH_LANGUAGE,
        "sortBy": "publishedAt",
        "pageSize": min(
            settings.FETCH_PAGE_SIZE,
            100,
        ),
        "searchIn": (
            "title,description,content"
        ),
    }

    headers = {
        "X-Api-Key": NEWSAPI_KEY,
        "User-Agent": (
            "underdog-sports-bot-v2/1.0"
        ),
    }

    for attempt in range(
        NEWSAPI_RETRIES + 1
    ):

        try:

            response = session.get(
                NEWSAPI_ENDPOINT,
                params=params,
                headers=headers,
                timeout=20,
            )

        except requests.RequestException as exc:

            if attempt < NEWSAPI_RETRIES:

                delay = (
                    3 * (2 ** attempt)
                )

                print(
                    f"[WARN] NewsAPI network error. "
                    f"Retrying in {delay}s..."
                )

                time.sleep(
                    delay
                )

                continue

            return (
                [],
                False,
                False,
                f"Network error: {exc}",
            )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        if response.status_code == 200:

            try:

                payload = response.json()

            except ValueError:

                return (
                    [],
                    False,
                    False,
                    "NewsAPI returned invalid JSON.",
                )

            if payload.get(
                "status"
            ) != "ok":

                return (
                    [],
                    False,
                    False,
                    payload.get(
                        "message",
                        "NewsAPI returned an error.",
                    ),
                )

            return (
                payload.get(
                    "articles",
                    [],
                ),
                True,
                False,
                "",
            )

        # ----------------------------------------------------
        # 429
        # ----------------------------------------------------

        if response.status_code == 429:

            try:

                payload = response.json()

            except ValueError:

                payload = {}

            code = payload.get(
                "code",
                "",
            )

            message = payload.get(
                "message",
                "",
            )

            if (
                code == "apiKeyExhausted"
                or
                _looks_like_daily_quota_exhaustion(
                    message
                )
            ):

                _mark_newsapi_quota_exhausted(
                    message
                )

                return (
                    [],
                    False,
                    True,
                    (
                        "NewsAPI daily quota exhausted. "
                        f"{message}"
                    ),
                )

            if attempt < NEWSAPI_RETRIES:

                retry_after = (
                    response.headers.get(
                        "Retry-After"
                    )
                )

                try:

                    delay = max(
                        5,
                        int(
                            retry_after
                        ),
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    delay = (
                        5 * (2 ** attempt)
                    )

                print(
                    f"[WARN] Temporary NewsAPI "
                    f"rate limit. Retrying in "
                    f"{delay}s..."
                )

                time.sleep(
                    delay
                )

                continue

            return (
                [],
                False,
                True,
                (
                    "NewsAPI returned HTTP 429. "
                    f"{message}"
                ),
            )

        # ----------------------------------------------------
        # 401
        # ----------------------------------------------------

        if response.status_code == 401:

            try:

                payload = response.json()

                message = payload.get(
                    "message",
                    "Unauthorized.",
                )

            except ValueError:

                message = "Unauthorized."

            return (
                [],
                False,
                False,
                (
                    "NewsAPI authentication failed. "
                    f"{message}"
                ),
            )

        # ----------------------------------------------------
        # OTHER ERRORS
        # ----------------------------------------------------

        if attempt < NEWSAPI_RETRIES:

            delay = (
                3 * (2 ** attempt)
            )

            print(
                f"[WARN] NewsAPI HTTP "
                f"{response.status_code}. "
                f"Retrying in {delay}s..."
            )

            time.sleep(
                delay
            )

            continue

        try:

            payload = response.json()

            message = payload.get(
                "message",
                "",
            )

        except ValueError:

            message = ""

        return (
            [],
            False,
            False,
            (
                f"NewsAPI HTTP "
                f"{response.status_code}. "
                f"{message}"
            ),
        )

    return (
        [],
        False,
        False,
        "NewsAPI request failed.",
    )


def fetch_newsapi_discovery(
    days_back: int,
):

    if _is_newsapi_quota_blocked():

        return (
            [],
            0,
        )

    session = requests.Session()

    all_articles = []

    successful_queries = 0

    for index, query in enumerate(
        DISCOVERY_QUERIES,
        start=1,
    ):

        print(
            f"\nNewsAPI discovery "
            f"{index}/{len(DISCOVERY_QUERIES)}..."
        )

        (
            articles,
            success,
            rate_limited,
            error,
        ) = _newsapi_request(
            session,
            query,
            days_back,
        )

        if success:

            successful_queries += 1

            print(
                f"  Received {len(articles)} articles."
            )

            all_articles.extend(
                articles
            )

        else:

            print(
                "[WARN] Query failed:"
            )

            print(
                f"       {error}"
            )

            if rate_limited:

                print(
                    "[WARN] Stopping further "
                    "NewsAPI requests."
                )

                break

        if index < len(
            DISCOVERY_QUERIES
        ):

            time.sleep(
                NEWSAPI_REQUEST_SPACING
            )

    return (
        deduplicate_articles(
            all_articles
        ),
        successful_queries,
    )


# ============================================================
# GOOGLE NEWS DISCOVERY FALLBACK
# ============================================================

def _google_news_url(
    query: str,
) -> str:

    return (
        f"{GOOGLE_NEWS_RSS}"
        f"?q={quote_plus(query)}"
        "&hl=en-IN"
        "&gl=IN"
        "&ceid=IN:en"
    )


def _parse_google_news(
    xml_text: str,
) -> list[dict]:

    articles = []

    root = ElementTree.fromstring(
        xml_text
    )

    for item in root.findall(
        ".//item"
    ):

        title = (
            item.findtext(
                "title"
            )
            or ""
        )

        description = (
            item.findtext(
                "description"
            )
            or ""
        )

        link = (
            item.findtext(
                "link"
            )
            or ""
        )

        source = item.find(
            "source"
        )

        source_name = ""

        if source is not None:

            source_name = (
                source.text
                or ""
            )

        articles.append(
            {
                "source": {
                    "name": html.unescape(
                        source_name
                    ),
                },
                "author": None,
                "title": html.unescape(
                    title
                ),
                "description": html.unescape(
                    re.sub(
                        r"<[^>]+>",
                        " ",
                        description,
                    )
                ),
                "url": link,
                "urlToImage": None,
                "publishedAt": None,
                "content": "",
            }
        )

    return articles


def _write_google_fallback_cache(
    articles: list[dict],
):

    _write_json(
        GOOGLE_FALLBACK_CACHE_PATH,
        {
            "saved_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "articles": articles,
        },
    )


def _read_google_fallback_cache():

    payload = _read_json(
        GOOGLE_FALLBACK_CACHE_PATH
    )

    if not isinstance(
        payload,
        dict,
    ):

        return (
            None,
            None,
        )

    try:

        saved_at = datetime.fromisoformat(
            payload[
                "saved_at"
            ]
        )

    except Exception:

        return (
            None,
            None,
        )

    articles = payload.get(
        "articles",
        [],
    )

    if not isinstance(
        articles,
        list,
    ):

        return (
            None,
            None,
        )

    age_minutes = (
        datetime.now(
            timezone.utc
        )
        - saved_at
    ).total_seconds() / 60

    return (
        articles,
        age_minutes,
    )


def google_news_fallback_discovery():

    cached, age_minutes = (
        _read_google_fallback_cache()
    )

    if (
        cached
        and age_minutes is not None
        and
        age_minutes
        <= GOOGLE_FALLBACK_CACHE_MAX_AGE_MINUTES
    ):

        print(
            f"[GOOGLE] Using fallback cache "
            f"({age_minutes:.1f} minutes old)."
        )

        return cached

    print(
        "\n[GOOGLE] Running fallback discovery..."
    )

    session = requests.Session()

    discovered = []

    for index, query in enumerate(
        GOOGLE_FALLBACK_QUERIES,
        start=1,
    ):

        print(
            f"  Google discovery "
            f"{index}/{len(GOOGLE_FALLBACK_QUERIES)}..."
        )

        try:

            response = session.get(
                _google_news_url(
                    query
                ),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 "
                        "(Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 "
                        "Chrome/153.0 Safari/537.36"
                    )
                },
                timeout=15,
            )

            if response.status_code != 200:

                print(
                    f"    HTTP {response.status_code}; skipped."
                )

                continue

            results = _parse_google_news(
                response.text
            )

            print(
                f"    Received {len(results)} results."
            )

            discovered.extend(
                results
            )

        except (
            requests.RequestException,
            ElementTree.ParseError,
        ) as exc:

            print(
                f"    Fallback query failed: {exc}"
            )

        if index < len(
            GOOGLE_FALLBACK_QUERIES
        ):

            time.sleep(
                COVERAGE_REQUEST_SPACING
            )

    discovered = deduplicate_articles(
        discovered
    )

    if discovered:

        _write_google_fallback_cache(
            discovered
        )

    return discovered


# ============================================================
# SOURCE EVIDENCE
# ============================================================

RESOURCE_EVIDENCE_PATTERNS = (

    # Direct funding/resource problems.
    r"\bno funding\b",
    r"\bwithout funding\b",
    r"\bunfunded\b",
    r"\blittle funding\b",
    r"\blimited funding\b",
    r"\bunderfunded\b",
    r"\black of funding\b",
    r"\blimited resources\b",
    r"\black of resources\b",
    r"\bfinancial hardship\b",
    r"\bfinancial difficulties\b",
    r"\bfinancial constraints\b",
    r"\bfinancial struggle\b",
    r"\bown expense\b",
    r"\bpaid from (?:his|her|their|own) pocket\b",

    # Facilities/equipment.
    r"\bwithout facilities\b",
    r"\bwithout equipment\b",
    r"\blimited facilities\b",
    r"\bpoor facilities\b",
    r"\bbasic facilities\b",
    r"\blimited equipment\b",

    # Dirt/basic/rough training conditions. These are sentence-bounded
    # so a word in one sentence cannot create evidence with a word in
    # an unrelated sentence later in the article.
    r"\btraining on\b[^.!?]{0,120}\b(?:dirt|rough|basic)\b",
    r"\btraining on dirt\b",
    r"\btrained on dirt\b",
    r"\bdirt (?:pitch|pitches|ground|field|track)\b",

    # Improvised facilities/resources. Keep both terms in the SAME
    # sentence to avoid false B matches on long enriched article text.
    r"\bmakeshift\b[^.!?]{0,120}\b(?:pit|pits|facility|facilities|equipment|field|ground|track|court|setup)\b",
    r"\b(?:pit|pits|facility|facilities|equipment|field|ground|track|court|setup)\b[^.!?]{0,120}\bmakeshift\b",

    r"\bimprovised\b[^.!?]{0,120}\b(?:pit|pits|facility|facilities|equipment|field|ground|track|court|setup)\b",
    r"\b(?:pit|pits|facility|facilities|equipment|field|ground|track|court|setup)\b[^.!?]{0,120}\bimprovised\b",

    r"\brudimentary\b[^.!?]{0,120}\b(?:facility|facilities|equipment|setup|pit|pits|field|ground)\b",
    r"\b(?:facility|facilities|equipment|setup|pit|pits|field|ground)\b[^.!?]{0,120}\brudimentary\b",

    # Specific documented improvised material.
    r"\bcorn husk\b[^.!?]{0,120}\b(?:pit|pits|jump|training|athletic)\b",
    r"\b(?:pit|pits|jump|training|athletic)\b[^.!?]{0,120}\bcorn husk\b",

    # Jugaad only when the article connects it to a physical
    # sporting setup/resource in the SAME sentence.
    r"\bjugaad\b[^.!?]{0,120}\b(?:pit|pits|facility|facilities|equipment|setup|training|field|ground)\b",
    r"\b(?:pit|pits|facility|facilities|equipment|setup|training|field|ground)\b[^.!?]{0,120}\bjugaad\b",
)


def attach_source_evidence(
    story,
    article: dict,
):

    setattr(
        story,
        "_source_title",
        article.get(
            "title",
            "",
        )
        or "",
    )

    setattr(
        story,
        "_source_description",
        article.get(
            "description",
            "",
        )
        or "",
    )

    setattr(
        story,
        "_source_content",
        article.get(
            "content",
            "",
        )
        or "",
    )

    setattr(
        story,
        "_source_text",
        _article_text(
            article
        ),
    )

    return story


def find_resource_evidence(
    story,
):

    text = getattr(
        story,
        "_source_text",
        "",
    )

    for pattern in RESOURCE_EVIDENCE_PATTERNS:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:

            return _normalize_space(
                match.group(
                    0
                )
            )

    return None


def has_resource_evidence(
    story,
) -> bool:
    """
    B is accepted only when:

        1. The source text contains concrete resource evidence.

    We intentionally do NOT require the older NLP boolean here.
    This allows newly recognized evidence such as "makeshift pit"
    to work without having to update the extractor every time.
    """

    return (
        find_resource_evidence(
            story
        )
        is not None
    )


# ============================================================
# HIGH-CONFIDENCE UNDERDOG / F NARRATIVE
# ============================================================

F_NARRATIVE_PATTERNS = (

    # Grassroots / humble beginnings.
    r"\bgrassroots\b",
    r"\bhumble beginnings\b",
    r"\bhumble background\b",
    r"\bbarefoot\b",
    r"\bfrom (?:a|an) village\b",
    r"\bfrom (?:a|an) small town\b",
    r"\bsmall-town\b",
    # NOTE: "amateur" is deliberately NOT a standalone F signal.
    # It is too weak on its own: many amateur athletes are not
    # grassroots, overlooked, or under-resourced. Strong narrative
    # evidence must establish the underdog context directly.

    # Improvised / basic beginnings.
    r"\btraining on dirt\b",
    r"\btrained on dirt\b",
    r"\bmakeshift\b.{0,120}\b(?:pit|pits|facility|facilities|equipment|field|ground|track|court|setup)\b",
    r"\b(?:pit|pits|facility|facilities|equipment|field|ground|track|court|setup)\b.{0,120}\bmakeshift\b",
    r"\bimprovised\b.{0,120}\b(?:pit|pits|facility|facilities|equipment|field|ground|track|court|setup)\b",
    r"\b(?:pit|pits|facility|facilities|equipment|field|ground|track|court|setup)\b.{0,120}\bimprovised\b",
    r"\brudimentary\b.{0,120}\b(?:facility|facilities|equipment|setup|pit|pits|field|ground)\b",
    r"\b(?:facility|facilities|equipment|setup|pit|pits|field|ground)\b.{0,120}\brudimentary\b",
    r"\bjugaad\b.{0,120}\b(?:pit|pits|facility|facilities|equipment|setup|training|field|ground)\b",
    r"\b(?:pit|pits|facility|facilities|equipment|setup|training|field|ground)\b.{0,120}\bjugaad\b",

    # Explicitly overlooked.
    r"\boverlooked\b",
    r"\bunheralded\b",
    r"\bunsung\b",
    r"\bunder-recognized\b",
    r"\bunderrecognized\b",

    # Explicitly low media attention.
    r"\bnot widely (?:reported|covered)\b",
    r"\brarely (?:reported|covered)\b",
    r"\blittle media attention\b",
    r"\blittle coverage\b",

    # Concrete adversity.
    r"\badversity\b",
    r"\bfinancial hardship\b",
    r"\bfinancial difficulties\b",
    r"\bfinancial struggle\b",
    r"\bpoverty\b",
    r"\bdiscrimination\b",
    r"\black of opportunity\b",
    r"\black of access\b",
    r"\black of infrastructure\b",
    r"\bpoor infrastructure\b",
    r"\bno proper (?:equipment|facilities|facility|training|coaching)\b",
    r"\bwithout proper (?:equipment|facilities|facility|training|coaching)\b",
    r"\blimited (?:access|opportunity|facilities|equipment|coaching)\b",
    r"\bno coach\b",
    r"\bwithout a coach\b",
    r"\bself-funded\b",
    r"\bself funded\b",
    r"\bself-trained\b",
    r"\bself trained\b",
    r"\bborrowed equipment\b",
    r"\bsecond-hand equipment\b",
    r"\bold equipment\b",
    r"\bpublic ground\b",
    r"\bschool ground\b",
    r"\bbackyard\b",
    r"\bmodest background\b",
    r"\bmodest means\b",
    r"\bhumble family\b",
    r"\bfarm(?:er|ers)[’']?s (?:son|daughter)\b",
    r"\bdaily-wage\b",
    r"\bdaily wage\b",
    r"\brural (?:athlete|star|champion|sport)\b",
    r"\bremote village\b",
    r"\blittle-known\b",
    r"\blesser-known\b",
    r"\bnot (?:a )?household name\b",
    r"\bagainst (?:the )?odds\b",
    r"\bdefied (?:the )?odds\b",
    r"\bdefied expectations\b",
    r"\bfamily resistance\b",
    r"\bresistance to pursuing\b",
    r"\bleft home\b",
    r"\bleave home\b",
    r"\bcareer-threatening injury\b",
    r"\bserious injury\b",
    r"\blong-term injury\b",
    r"\bpsychological struggles\b",
)


def find_f_narrative_evidence(
    story,
):

    title = getattr(
        story,
        "_source_title",
        "",
    )

    description = getattr(
        story,
        "_source_description",
        "",
    )

    content = getattr(
        story,
        "_source_content",
        "",
    )

    # Title + description are given priority.
    # Only the first 3000 content characters are used.
    text = _normalize_space(
        " ".join(
            [
                title,
                description,
                content[:3000],
            ]
        )
    )

    for pattern in F_NARRATIVE_PATTERNS:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:

            return _normalize_space(
                match.group(
                    0
                )
            )

    return None


def has_underdog_signal(
    story,
) -> bool:

    if has_resource_evidence(
        story
    ):

        return True

    return (
        find_f_narrative_evidence(
            story
        )
        is not None
    )


# ============================================================
# CANDIDATE BUILDING
# ============================================================

def apply_page_text(
    story,
    result,
):
    """
    Attach fetched article-page text to a story.

    A failed fetch changes NOTHING about the story's evidence:
    it is recorded only as a status for logging.
    """

    setattr(
        story,
        "_page_status",
        result.status,
    )

    if not result.ok:
        return story

    original_content = getattr(
        story,
        "_source_content",
        "",
    )

    setattr(
        story,
        "_page_text",
        result.text,
    )

    setattr(
        story,
        "_source_content",
        _normalize_space(
            f"{original_content} {result.text}"
        ),
    )

    setattr(
        story,
        "_source_text",
        _normalize_space(
            " ".join(
                [
                    getattr(story, "_source_title", ""),
                    getattr(story, "_source_description", ""),
                    original_content,
                    result.text,
                ]
            )
        ),
    )

    return story


def enrich_stories(
    stories: list,
    max_articles: int,
) -> dict:
    """
    Fetch publisher pages for stories that do not already have
    resource evidence in their snippet.

    Coverage verification is NOT involved here.
    """

    targets = [
        story
        for story in stories
        if not has_resource_evidence(story)
    ]

    targets.sort(
        key=lambda story: (
            story.achievement_score,
            story.underdog_score,
        ),
        reverse=True,
    )

    targets = targets[:max_articles]

    counts: dict[str, int] = {}

    if not targets:
        return counts

    print(
        f"\nEnriching {len(targets)} article page(s) "
        f"for source-text evidence..."
    )

    session = requests.Session()

    for story in targets:

        result = fetch_article_text(
            story.url,
            session=session,
            cache_dir=PAGE_CACHE_DIR,
        )

        counts[result.status] = (
            counts.get(result.status, 0) + 1
        )

        apply_page_text(
            story,
            result,
        )

        if result.ok and has_resource_evidence(story):

            setattr(
                story,
                "_resource_evidence_origin",
                "page",
            )

            print(
                f"  [ENRICH] B evidence in article page: "
                f"{find_resource_evidence(story)!r}\n"
                f"           {story.title}"
            )

    summary = ", ".join(
        f"{status}={count}"
        for status, count in sorted(counts.items())
    )

    print(
        f"  Enrichment results: {summary}"
    )

    return counts


def build_candidates(
    articles: list[dict],
    enrich: bool = False,
    enrich_max: int = ENRICH_MAX_ARTICLES,
):

    stories = []

    for article in articles:

        story = score_article(
            article
        )

        # Attach the original source text BEFORE any score gate so that
        # concrete resource evidence in the article can qualify the story
        # for B even when the headline/description has weak achievement
        # wording.
        attach_source_evidence(
            story,
            article,
        )

        if has_resource_evidence(
            story
        ):

            setattr(
                story,
                "_resource_evidence_origin",
                "snippet",
            )

        stories.append(
            story
        )

    if enrich:

        enrich_stories(
            stories,
            enrich_max,
        )

    scored = []

    for story in stories:

        resource_evidence = has_resource_evidence(
            story
        )

        if resource_evidence:

            story.resource_evidence = True

        # Normal candidates still need sufficient achievement signal.
        # B candidates are allowed through on concrete source evidence
        # alone; this is necessary for the intended B OR F architecture.
        if (
            story.achievement_score
            < MIN_ACHIEVEMENT_SCORE
            and not resource_evidence
        ):

            continue

        scored.append(
            story
        )

    def priority(story):

        return (
            has_resource_evidence(
                story
            ),
            has_underdog_signal(
                story
            ),
            story.achievement_score,
            story.underdog_score,
            story.status_gap_score,
        )

    scored.sort(
        key=priority,
        reverse=True,
    )

    return scored[
        :MAX_COVERAGE_CANDIDATES
    ]


# ============================================================
# PUBLISHER CLASSIFICATION
# ============================================================

CANONICAL_NEWS_PUBLISHERS = {

    "economictimes.com": "economictimes",
    "economictimes.indiatimes.com": "economictimes",

    "timesofindia.indiatimes.com": "timesofindia",
    "timesofindia.com": "timesofindia",

    "hindustantimes.com": "hindustantimes",

    "thehindu.com": "thehindu",

    "indianexpress.com": "indianexpress",

    "business-standard.com": "businessstandard",

    "aninews.in": "aninews",

    "tribuneindia.com": "tribuneindia",

    "outlookindia.com": "outlookindia",

    "thelogicalindian.com": "thelogicalindian",

    "khelnow.com": "khelnow",

    "rediff.com": "rediff",

    "sportstar.thehindu.com": "sportstar",

    "femina.in": "femina",

    "homegrown.co.in": "homegrown",

    "ascendants.in": "ascendants",

    "highlandpost.com": "highlandpost",

    "syllad.com": "syllad",

    "cricketnmore.com": "cricketnmore",

    "shillongtoday.com": "shillongtoday",

    "timesnownews.com": "timesnownews",

    "indiatoday.in": "indiatoday",

    "worldarthletics.org": "worldathletics",
}


INSTITUTIONAL_DOMAINS = {
    "olympics.com": "olympics",
    "worldarchery.sport": "worldarchery",
    "worldathletics.org": "worldathletics",
    "fih.ch": "fih",
    "bwfbadminton.com": "bwf",
    "itftennis.com": "itf",
    "icc-cricket.com": "icc",
    "commonwealthsport.com": "commonwealthsport",
    "asianboxing.org": "asianboxing",
    "immaf.org": "immaf",
}


SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "reddit.com",
}


def _strip_mobile_prefixes(
    hostname: str,
) -> str:

    hostname = (
        hostname
        .lower()
        .strip(".")
    )

    for prefix in (
        "www.",
        "m.",
        "mobile.",
        "amp.",
    ):

        if hostname.startswith(
            prefix
        ):

            hostname = hostname[
                len(prefix):
            ]

    return hostname


def classify_domain(
    url: str,
):
    """
    Return:

        (canonical_name, source_type)

    where source_type is:

        news
        institutional
        social
        unknown
    """

    if not url:
        return (
            None,
            "unknown",
        )

    try:

        hostname = (
            urlparse(
                url
            ).hostname
        )

    except Exception:

        return (
            None,
            "unknown",
        )

    if not hostname:
        return (
            None,
            "unknown",
        )

    hostname = _strip_mobile_prefixes(
        hostname
    )

    if hostname in SOCIAL_DOMAINS:

        return (
            hostname,
            "social",
        )

    if hostname in INSTITUTIONAL_DOMAINS:

        return (
            INSTITUTIONAL_DOMAINS[
                hostname
            ],
            "institutional",
        )

    if hostname in CANONICAL_NEWS_PUBLISHERS:

        return (
            CANONICAL_NEWS_PUBLISHERS[
                hostname
            ],
            "news",
        )

    if (
        hostname == "google.com"
        or hostname.endswith(
            ".google.com"
        )
    ):

        return (
            None,
            "unknown",
        )

    return (
        hostname,
        "news",
    )


# ============================================================
# COVERAGE VERIFICATION
# ============================================================

def clean_coverage_query(
    title: str,
) -> str:

    title = _normalize_space(
        title
    )

    title = re.sub(
        r"[^\w\s'-]",
        "",
        title,
    )

    return " ".join(
        title.split()[:18]
    )


def verify_coverage(
    story,
) -> dict:
    """
    Verify independent MEDIA coverage.

    News publishers count toward F.

    Institutional sources are reported separately.

    Social platforms are reported separately and NEVER count
    as independent publishers.
    """

    query = clean_coverage_query(
        story.title
    )

    try:

        response = requests.get(
            _google_news_url(
                query
            ),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/153.0 Safari/537.36"
                )
            },
            timeout=COVERAGE_REQUEST_TIMEOUT,
        )

    except requests.RequestException as exc:

        return {
            "verification_available": False,
            "coverage_gap": False,
            "query": query,
            "result_count": 0,
            "news_result_count": 0,
            "news_domains": [],
            "institutional_sources": [],
            "social_sources": [],
            "social_result_count": 0,
            "evidence": (
                "Coverage verification unavailable: "
                f"{exc}"
            ),
        }

    if response.status_code != 200:

        return {
            "verification_available": False,
            "coverage_gap": False,
            "query": query,
            "result_count": 0,
            "news_result_count": 0,
            "news_domains": [],
            "institutional_sources": [],
            "social_sources": [],
            "social_result_count": 0,
            "evidence": (
                "Coverage verification unavailable: "
                f"Google News HTTP "
                f"{response.status_code}."
            ),
        }

    try:

        root = ElementTree.fromstring(
            response.text
        )

    except ElementTree.ParseError as exc:

        return {
            "verification_available": False,
            "coverage_gap": False,
            "query": query,
            "result_count": 0,
            "news_result_count": 0,
            "news_domains": [],
            "institutional_sources": [],
            "social_sources": [],
            "social_result_count": 0,
            "evidence": (
                "Coverage verification unavailable: "
                f"RSS parse error: {exc}"
            ),
        }

    news_domains = []
    institutional_sources = []
    social_sources = []

    total_results = 0
    news_result_count = 0
    social_result_count = 0

    for item in root.findall(
        ".//item"
    ):

        total_results += 1

        source = item.find(
            "source"
        )

        if source is None:
            continue

        source_url = source.attrib.get(
            "url",
            "",
        )

        canonical, source_type = (
            classify_domain(
                source_url
            )
        )

        if source_type == "news":

            news_result_count += 1

            if canonical:

                news_domains.append(
                    canonical
                )

        elif source_type == "institutional":

            if canonical:

                institutional_sources.append(
                    canonical
                )

        elif source_type == "social":

            social_result_count += 1

            if canonical:

                social_sources.append(
                    canonical
                )

    unique_news_domains = sorted(
        set(
            news_domains
        )
    )

    unique_institutional = sorted(
        set(
            institutional_sources
        )
    )

    unique_social = sorted(
        set(
            social_sources
        )
    )

    if news_result_count == 0:

        return {
            "verification_available": True,
            "coverage_gap": False,
            "query": query,
            "result_count": total_results,
            "news_result_count": 0,
            "news_domains": [],
            "institutional_sources": unique_institutional,
            "social_sources": unique_social,
            "social_result_count": social_result_count,
            "evidence": (
                f"Google News returned "
                f"{total_results} result(s), but "
                "no independent news publisher results "
                "could be established. Coverage gap was "
                "not automatically assigned."
            ),
        }

    low_news_domain_count = (
        len(unique_news_domains)
        <= MAX_COVERAGE_NEWS_DOMAINS
    )

    low_news_result_count = (
        news_result_count
        <= MAX_COVERAGE_NEWS_RESULTS
    )

    coverage_gap = (
        low_news_domain_count
        and
        low_news_result_count
    )

    evidence = (
        f"Google News returned "
        f"{total_results} total result(s): "
        f"{news_result_count} news result(s) "
        f"across {len(unique_news_domains)} "
        f"independent news publisher(s)"
    )

    if unique_news_domains:

        evidence += (
            f" ({', '.join(unique_news_domains)})"
        )

    if unique_institutional:

        evidence += (
            f"; institutional sources excluded from "
            f"publisher count: "
            f"{', '.join(unique_institutional)}"
        )

    if unique_social:

        evidence += (
            f"; social sources excluded: "
            f"{', '.join(unique_social)}"
        )

    evidence += "."

    if coverage_gap:

        evidence += (
            " This meets the current low-media-coverage threshold."
        )

    else:

        evidence += (
            " The story does not meet the current "
            "low-media-coverage threshold."
        )

    return {
        "verification_available": True,
        "coverage_gap": coverage_gap,
        "query": query,
        "result_count": total_results,
        "news_result_count": news_result_count,
        "news_domains": unique_news_domains,
        "institutional_sources": unique_institutional,
        "social_sources": unique_social,
        "evidence": evidence,
    }


# ============================================================
# FINAL SCORES
# ============================================================

def update_scores(
    story,
    coverage: dict,
    attention: dict,
):

    if (
        coverage[
            "verification_available"
        ]
        and
        coverage[
            "coverage_gap"
        ]
    ):

        story.coverage_gap_score = 1.0

    else:

        story.coverage_gap_score = 0.0

    story.coverage_verification = (
        coverage[
            "evidence"
        ]
    )

    story.coverage_domains = (
        coverage[
            "news_domains"
        ]
    )

    story.coverage_result_count = (
        coverage[
            "result_count"
        ]
    )

    story.coverage_news_result_count = (
        coverage[
            "news_result_count"
        ]
    )

    story.institutional_sources = (
        coverage[
            "institutional_sources"
        ]
    )

    story.social_sources = (
        coverage[
            "social_sources"
        ]
    )

    story.social_result_count = (
        coverage.get(
            "social_result_count",
            0,
        )
    )

    # F is decided by VERIFIED REDDIT attention, not by news coverage.
    # The existing evaluator computes the Reddit-specific gap separately;
    # use that field directly so heavy Google News coverage cannot block F.
    story.reddit_discussion_gap = bool(
        attention.get(
            "reddit_discussion_gap",
            False,
        )
    )

    story.public_attention_gap_score = (
        1.0
        if story.reddit_discussion_gap
        else 0.0
    )

    story.reddit_discussion_count = (
        attention[
            "reddit_discussion_count"
        ]
    )

    story.reddit_discussion_gap = (
        attention[
            "reddit_discussion_gap"
        ]
    )

    story.known_audience_size = (
        attention[
            "known_audience_size"
        ]
    )

    story.public_attention_verification = (
        attention[
            "evidence"
        ]
    )

    # Recalculate after public-attention verification.
    story.combined_score = (
        0.40
        * story.achievement_score
        + 0.25
        * story.underdog_score
        + 0.20
        * story.public_attention_gap_score
        + 0.15
        * story.status_gap_score
    )

    return story


# ============================================================
# CLASSIFICATION
# ============================================================

def classify_story(
    story,
) -> str:

    has_b = has_resource_evidence(
        story
    )

    has_f = (
        getattr(
            story,
            "public_attention_gap_score",
            0.0,
        )
        >= 1.0
    )

    genuine_underdog = (
        has_underdog_signal(
            story
        )
    )

    if has_b and has_f:

        return "B+F"

    if has_b:

        return "B"

    if (
        has_f
        and
        genuine_underdog
    ):

        return "F"

    return "NONE"


# ============================================================
# CAPTION GENERATION
# ============================================================

def generate_caption(
    story,
    category: str,
) -> str:

    title = _normalize_space(
        story.title
    )

    resource = find_resource_evidence(
        story
    )

    narrative = find_f_narrative_evidence(
        story
    )

    headers = {
        "B+F": "🔥 UNDERDOG SPOTLIGHT 🔥",
        "B": "💪 RESOURCE STORY",
        "F": "👀 UNDERCOVERED STORY",
    }

    header = headers.get(
        category,
        "🇮🇳 INDIAN SPORTS STORY",
    )

    body = ""

    if category in (
        "B+F",
        "B",
    ) and resource:

        resource_lower = (
            resource.lower()
        )

        if "dirt" in resource_lower:

            body = (
                "The journey began with training "
                "on dirt."
            )

        elif "makeshift" in resource_lower:

            body = (
                "The journey developed around "
                "makeshift sporting facilities."
            )

        elif "improvised" in resource_lower:

            body = (
                "The journey began with "
                "improvised training facilities."
            )

        elif "jugaad" in resource_lower:

            body = (
                "The athlete's early journey relied "
                "on a makeshift sporting setup."
            )

        elif "funding" in resource_lower:

            body = (
                "The achievement came despite "
                "limited funding."
            )

        elif "financial" in resource_lower:

            body = (
                "The achievement came despite "
                "financial difficulties."
            )

        elif "facility" in resource_lower:

            body = (
                "The journey continued despite "
                "limited facilities."
            )

        else:

            body = (
                "The achievement came despite "
                "significant resource constraints."
            )

    elif category == "F" and narrative:

        narrative_lower = (
            narrative.lower()
        )

        if (
            "overlooked"
            in narrative_lower
            or
            "unheralded"
            in narrative_lower
            or
            "unsung"
            in narrative_lower
        ):

            body = (
                "A sporting achievement that has "
                "received limited attention."
            )

        elif "grassroots" in narrative_lower:

            body = (
                "A grassroots sporting story "
                "deserving wider attention."
            )

        elif "adversity" in narrative_lower:

            body = (
                "A sporting achievement shaped by "
                "significant adversity."
            )

        elif "barefoot" in narrative_lower:

            body = (
                "A remarkable journey rooted in "
                "humble sporting beginnings."
            )

        elif "village" in narrative_lower:

            body = (
                "A story with its roots in "
                "grassroots Indian sport."
            )

        else:

            body = (
                "A remarkable achievement from a "
                "story that received limited coverage."
            )

    else:

        body = (
            "A remarkable achievement from "
            "Indian sport."
        )

    caption = (
        f"{header}\n\n"
        f"{title}\n\n"
        f"{body}\n\n"
        "Help more people discover the story — "
        "read, watch and share.\n\n"
        "🇮🇳 #IndianSports "
        "#GrassrootsSports #Underdogs"
    )

    if story.url:

        caption += (
            f"\n{story.url}"
        )

    return caption[:700]


# ============================================================
# DISCOVERY PREPARATION
# ============================================================

def prepare_articles(
    articles: list[dict],
):

    before = len(
        articles
    )

    relevant = [
        article
        for article in articles
        if is_strict_indian_sports_article(
            article
        )
    ]

    relevant = deduplicate_articles(
        relevant
    )

    print(
        f"Discovery: {before} raw -> "
        f"{len(relevant)} strict Indian sports "
        f"matches/articles"
    )

    return relevant


# ============================================================
# DISCOVERY ORCHESTRATION
# ============================================================

def discover_articles(
    days_back: int,
    force_fresh: bool,
):
    """
    Discovery order:

        recent cache
        ↓
        NewsAPI
        ↓
        large local dataset + Google News
        ↓
        Google News only
    """

    # --------------------------------------------------------
    # RECENT CACHE
    # --------------------------------------------------------

    if not force_fresh:

        cached, age_minutes = (
            _read_discovery_cache()
        )

        if (
            cached
            and
            age_minutes is not None
            and
            age_minutes
            <= CACHE_MAX_AGE_MINUTES
        ):

            print(
                f"[CACHE] Using recent discovery cache "
                f"({age_minutes:.1f} minutes old)."
            )

            return cached

    # --------------------------------------------------------
    # NEWSAPI
    # --------------------------------------------------------

    print(
        "Running targeted NewsAPI discovery..."
    )

    (
        newsapi_articles,
        successful_queries,
    ) = fetch_newsapi_discovery(
        days_back
    )

    if newsapi_articles:

        newsapi_articles = (
            deduplicate_articles(
                newsapi_articles
            )
        )

        _write_discovery_cache(
            newsapi_articles
        )

        print(
            f"[NEWSAPI] "
            f"{successful_queries} query/queries succeeded."
        )

        # Supplement the NewsAPI set with Google News discovery so that
        # niche/grassroots stories missed by NewsAPI can enter the candidate
        # pool without spending more NewsAPI quota.
        google_articles = google_news_fallback_discovery()
        combined = deduplicate_articles(
            newsapi_articles + google_articles
        )

        if len(combined) > len(newsapi_articles):
            print(
                f"[DISCOVERY] NewsAPI + Google News supplement: "
                f"{len(newsapi_articles)} -> {len(combined)} raw articles."
            )

        return combined

    # --------------------------------------------------------
    # LARGEST LOCAL DATASET
    # --------------------------------------------------------

    local_articles = (
        _load_largest_raw_cache()
    )

    local_articles = (
        deduplicate_articles(
            local_articles
        )
    )

    print(
        f"[CACHE] Best local dataset contains "
        f"{len(local_articles)} articles."
    )

    # --------------------------------------------------------
    # SUPPLEMENT SMALL LOCAL DATASET
    # --------------------------------------------------------

    if len(
        local_articles
    ) < MIN_USEFUL_LOCAL_ARTICLES:

        print(
            f"[FALLBACK] Local dataset is below "
            f"{MIN_USEFUL_LOCAL_ARTICLES} articles."
        )

        google_articles = (
            google_news_fallback_discovery()
        )

        combined = deduplicate_articles(
            local_articles
            + google_articles
        )

        if combined:

            print(
                f"[FALLBACK] Combined local + Google News "
                f"dataset: {len(combined)} articles."
            )

            _write_discovery_cache(
                combined
            )

            return combined

    # --------------------------------------------------------
    # LARGE LOCAL DATASET
    # --------------------------------------------------------

    if local_articles:

        print(
            "[CACHE] Using previous local discovery dataset."
        )

        return local_articles

    # --------------------------------------------------------
    # LAST RESORT GOOGLE NEWS
    # --------------------------------------------------------

    google_articles = (
        google_news_fallback_discovery()
    )

    if google_articles:

        _write_discovery_cache(
            google_articles
        )

        return google_articles

    return []


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Discover Indian sports stories "
            "using strict B OR F logic."
        )
    )

    parser.add_argument(
        "--query",
        help=(
            "Run one custom NewsAPI discovery query."
        ),
    )

    parser.add_argument(
        "--days-back",
        type=int,
        default=30,
        help=(
            "Discovery window in days. Default: 30."
        ),
    )

    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help=(
            "Limit output/posting to N stories. Default: all qualified stories."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview qualified stories without posting."
        ),
    )

    parser.add_argument(
        "--post",
        action="store_true",
        help=(
            "Actually publish qualified stories to configured social accounts."
        ),
    )

    parser.add_argument(
        "--save-raw",
        action="store_true",
        help=(
            "Save current discovery results."
        ),
    )

    parser.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "Ignore recent cache and attempt fresh discovery."
        ),
    )

    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help=(
            "Do not fetch article pages for source-text evidence."
        ),
    )

    parser.add_argument(
        "--enrich-max",
        type=int,
        default=ENRICH_MAX_ARTICLES,
        help=(
            "Maximum article pages to fetch per run."
        ),
    )

    args = parser.parse_args()

    if args.post and args.dry_run:
        parser.error("--post and --dry-run are mutually exclusive")

    # Show the exact discovery window used for this run.
    search_end = datetime.now(timezone.utc).date()
    search_start = search_end - timedelta(days=args.days_back)

    print(
        f"Search window (UTC): {search_start.isoformat()} "
        f"through now ({args.days_back} days back)."
    )

    # ========================================================
    # DISCOVERY
    # ========================================================

    if args.query:

        print(
            f"Fetching articles for custom query: "
            f"'{args.query}'..."
        )

        session = requests.Session()

        (
            articles,
            success,
            rate_limited,
            error,
        ) = _newsapi_request(
            session,
            args.query,
            args.days_back,
        )

        if not success:

            print(
                f"[WARN] Custom query failed: "
                f"{error}"
            )

            articles = (
                _load_largest_raw_cache()
            )

            if len(
                articles
            ) < MIN_USEFUL_LOCAL_ARTICLES:

                articles = deduplicate_articles(
                    articles
                    + google_news_fallback_discovery()
                )

        articles = prepare_articles(
            articles
        )

    else:

        raw_articles = discover_articles(
            args.days_back,
            args.fresh,
        )

        articles = prepare_articles(
            raw_articles
        )

    # ========================================================
    # SAVE RAW
    # ========================================================

    if args.save_raw:

        output_path = (
            settings.RAW_DATA_DIR
            / "latest_discovery.json"
        )

        _write_json(
            output_path,
            articles,
        )

        print(
            f"[SAVE] Raw discovery saved to: "
            f"{output_path}"
        )

    # ========================================================
    # SCORING
    # ========================================================

    print(
        f"\nScoring {len(articles)} discovered articles..."
    )

    candidates = build_candidates(
        articles,
        enrich=not args.no_enrich,
        enrich_max=args.enrich_max,
    )

    b_candidates = [
        story
        for story in candidates
        if has_resource_evidence(
            story
        )
    ]

    strong_underdog_candidates = [
        story
        for story in candidates
        if has_underdog_signal(
            story
        )
    ]

    print(
        f"{len(candidates)} promising stories selected "
        f"for B/F coverage verification."
    )

    print(
        f"  B candidates: "
        f"{len(b_candidates)}"
    )

    print(
        f"  Strong underdog candidates: "
        f"{len(strong_underdog_candidates)}"
    )

    print(
        f"  Coverage candidates: "
        f"{len(candidates)}"
    )

    # Only stories with a genuine B/resource or F narrative signal can ever
    # qualify. Do not spend Reddit requests on stories that are structurally
    # incapable of becoming B, B+F, or F.
    verification_candidates = [
        story
        for story in candidates
        if has_underdog_signal(story)
    ]

    print(
        f"  Reddit verification candidates: "
        f"{len(verification_candidates)}"
    )

    # ========================================================
    # COVERAGE / REDDIT VERIFICATION
    # ========================================================

    final_stories = []

    print(
        "\n--- Coverage + Reddit verification ---"
    )

    reddit_session = requests.Session()

    for index, story in enumerate(
        verification_candidates,
        start=1,
    ):

        print(
            f"\n[{index}/{len(verification_candidates)}] "
            f"Verifying coverage: "
            f"{story.title}"
        )

        coverage = verify_coverage(
            story
        )

        print(
            f"  {coverage['evidence']}"
        )

        # Reddit is the deciding F signal. We still run Reddit even when
        # Google News coverage verification is unavailable, because media
        # volume is diagnostic only and must never block an F classification.
        discussion = verify_reddit_discussions(
            story.title,
            args.days_back,
            session=reddit_session,
            use_cache=True,
        )

        attention = evaluate_public_attention(
            coverage,
            discussion,
            story,
        )

        # The shared evaluator also exposes `reddit_discussion_gap`.
        # Promote that verified Reddit-only signal to the actual public-
        # attention decision. False/unknown remains non-qualifying.
        attention = dict(attention)

        reddit_gap = bool(
            attention.get(
                "reddit_discussion_gap",
                False,
            )
        )

        attention["public_attention_gap"] = reddit_gap

        if reddit_gap:
            attention["evidence"] = (
                "Public-attention gap established: Reddit discussion is "
                "verified low; Google News coverage is diagnostic only."
            )
        elif "unavailable" in discussion.evidence.lower():
            attention["evidence"] = (
                "Public-attention gap not established: Reddit verification "
                "was unavailable."
            )
        else:
            attention["evidence"] = (
                "Public-attention gap not established: Reddit discussion "
                "is not verified as low."
            )

        story = update_scores(
            story,
            coverage,
            attention,
        )

        print(
            f"  {discussion.evidence}"
        )

        print(
            f"  {attention['evidence']}"
        )

        category = classify_story(
            story
        )

        # ----------------------------------------------------
        # EVIDENCE DISPLAY
        # ----------------------------------------------------

        if attention[
            "public_attention_gap"
        ]:

            resource_evidence = (
                find_resource_evidence(
                    story
                )
            )

            f_evidence = (
                find_f_narrative_evidence(
                    story
                )
            )

            if resource_evidence:

                print(
                    f"  B resource evidence: "
                    f"{resource_evidence}"
                )

            if f_evidence:

                print(
                    f"  F narrative evidence: "
                    f"{f_evidence}"
                )

        # ----------------------------------------------------
        # CLASSIFICATION
        # ----------------------------------------------------

        if category == "B+F":

            print(
                "  >>> B + F: CORE UNDERDOG SPOTLIGHT"
            )

        elif category == "B":

            print(
                "  >>> B only: RESOURCE STORY"
            )

        elif category == "F":

            print(
                "  >>> F only: UNDERCOVERED STORY"
            )

        elif attention.get(
            "reddit_discussion_gap",
            False,
        ) is False and not coverage.get(
            "coverage_gap",
            False,
        ):

            print(
                "  >>> No F qualification: Reddit attention is "
                "not verified as low or underdog evidence is insufficient."
            )

        elif coverage.get(
            "coverage_gap",
            False,
        ):

            print(
                "  >>> Low news coverage is only a diagnostic; "
                "F still requires verified low Reddit attention "
                "and genuine underdog evidence."
            )

        # ----------------------------------------------------
        # IMPORTANT: NO HARD SCORE GATE
        # ----------------------------------------------------
        # B/F qualification is evidence-based.
        # combined_score is used only to rank already-qualified
        # stories; it must not reject a story that has satisfied
        # the required evidence gates.

        # ----------------------------------------------------
        # STORE
        # ----------------------------------------------------

        if category != "NONE":

            story.story_category = (
                category
            )
            story._resource_evidence = find_resource_evidence(story)
            story._f_narrative_evidence = find_f_narrative_evidence(story)

            final_stories.append(
                (
                    category,
                    story,
                )
            )

    # ========================================================
    # SORT
    # ========================================================

    category_order = {
        "B+F": 0,
        "B": 1,
        "F": 2,
    }

    final_stories.sort(
        key=lambda item: (
            category_order.get(
                item[0],
                99,
            ),
            -item[1].combined_score,
        )
    )

    # Persist backend-ready structured output for the website/API layer.
    output_paths = save_run_outputs(
        final_stories,
        days_back=args.days_back,
        generated_at=datetime.now(timezone.utc),
        generate_caption_fn=generate_caption,
    )
    print(
        f"[SAVE] Qualified output: {output_paths['latest_qualified']}"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    b_f_count = sum(
        category == "B+F"
        for category, _ in final_stories
    )

    b_count = sum(
        category == "B"
        for category, _ in final_stories
    )

    f_count = sum(
        category == "F"
        for category, _ in final_stories
    )

    print(
        f"\n{len(final_stories)} stories qualified "
        f"under B OR F."
    )

    print(
        f"  B + F core: "
        f"{b_f_count}"
    )

    print(
        f"  B only:     "
        f"{b_count}"
    )

    print(
        f"  F only:     "
        f"{f_count}"
    )

    if not final_stories:

        print(
            "\nNo stories qualified."
        )

        return

    # ========================================================
    # FINAL STORIES
    # ========================================================

    print(
        "\n=============================="
    )

    print(
        "QUALIFIED STORIES"
    )

    print(
        "=============================="
    )

    stories_to_output = (
        final_stories
        if args.top_n is None
        else final_stories[:args.top_n]
    )

    print(
        f"  Output stories: {len(stories_to_output)}"
    )

    for category, story in stories_to_output:

        print(
            f"\n[{category}] "
            f"[{story.combined_score:.3f}] "
            f"{story.title}"
        )

        print(
            f"  Achievement: "
            f"{story.achievement_score}"
        )

        print(
            f"  Underdog: "
            f"{story.underdog_score}"
        )

        print(
            f"  Resource B: "
            f"{has_resource_evidence(story)}"
        )

        origin = getattr(
            story,
            "_resource_evidence_origin",
            None,
        )

        if origin:

            print(
                f"  B evidence found in: "
                f"{origin}"
            )

        print(
            f"  Media coverage gap (diagnostic): "
            f"{story.coverage_gap_score}"
        )

        print(
            f"  Reddit attention gap (F signal): "
            f"{story.public_attention_gap_score}"
        )

        print(
            f"  Reddit discussions: "
            f"{getattr(story, 'reddit_discussion_count', 'unknown')}"
        )

        print(
            f"  Status gap: "
            f"{story.status_gap_score}"
        )

        print(
            f"  Ranking score: "
            f"{story.combined_score:.3f}"
        )

        print(
            f"  Total coverage results: "
            f"{getattr(story, 'coverage_result_count', 0)}"
        )

        print(
            f"  News results: "
            f"{getattr(story, 'coverage_news_result_count', 0)}"
        )

        print(
            f"  News publishers: "
            f"{', '.join(getattr(story, 'coverage_domains', []))}"
        )

        institutional = getattr(
            story,
            "institutional_sources",
            [],
        )

        if institutional:

            print(
                f"  Institutional sources: "
                f"{', '.join(institutional)}"
            )

        social = getattr(
            story,
            "social_sources",
            [],
        )

        if social:

            print(
                f"  Social sources excluded: "
                f"{', '.join(social)}"
            )

        image_url = (
            getattr(story, "image_url", None)
            or getattr(story, "urlToImage", None)
        )

        result = process_story(
            story,
            category=category,
            dry_run=not args.post,
            image_url=image_url,
        )

        if args.post:
            print(
                f"  Posting result: Twitter={result['twitter']} "
                f"Instagram={result['instagram']} "
                f"Posted={result['posted']}"
            )


if __name__ == "__main__":
    main()