"""Reddit-backed public-attention verification.

F is decided by verified low Reddit attention plus a genuine underdog signal.
Google News coverage is diagnostic only.

The verifier is deliberately conservative:
- OAuth is used when a Reddit access token is supplied.
- Anonymous access falls back to Reddit RSS; RSS treats <=3 matching posts as
  low discussion because it does not expose comment/score metrics.
- HTTP 429 / unavailable responses are UNKNOWN, never LOW.
- Results are cached locally as aggregate metrics to avoid repeated requests.
- Requests are throttled and share one Session across the pipeline run.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests


# ============================================================
# ENDPOINTS / CONFIG
# ============================================================

REDDIT_RSS_URL = "https://www.reddit.com/search.rss"
REDDIT_JSON_URL = "https://www.reddit.com/search.json"
REDDIT_OAUTH_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_OAUTH_SEARCH_URL = "https://oauth.reddit.com/search"

REDDIT_REQUEST_TIMEOUT = 15
REDDIT_MIN_REQUEST_INTERVAL_SECONDS = 8.0
REDDIT_MAX_RETRIES_429 = 1
REDDIT_CACHE_TTL_HOURS = 24

# Full low-attention rule when JSON metrics are available:
MAX_REDDIT_DISCUSSIONS_FOR_LOW_ATTENTION = 3
MAX_REDDIT_COMMENTS_FOR_LOW_ATTENTION = 15
MAX_REDDIT_TOP_SCORE_FOR_LOW_ATTENTION = 25

# High attention: clearly popular enough that F must not be assigned.
MIN_REDDIT_DISCUSSIONS_FOR_HIGH_ATTENTION = 10
MIN_REDDIT_COMMENTS_FOR_HIGH_ATTENTION = 100
MIN_REDDIT_TOP_SCORE_FOR_HIGH_ATTENTION = 100

MAX_FOLLOWERS_FOR_LOW_ATTENTION = 25_000

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "reddit_attention_cache.json"

_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT",
    "python:underdog-sports-bot:v2.3 (read-only sports attention verifier)",
)

_last_request_at = 0.0
_cached_access_token: str | None = None
_cached_access_token_expiry = 0.0


# ============================================================
# RESULT TYPE
# ============================================================

@dataclass
class DiscussionResult:
    verification_available: bool
    result_count: int
    low_discussion: bool | None
    evidence: str
    query: str
    total_comments: int | None = None
    top_score: int | None = None
    popularity: str = "unknown"


# ============================================================
# HELPERS
# ============================================================

def _clean_query(title: str) -> str:
    words = " ".join((title or "").split()).split()
    return " ".join(words[:10])


def _cache_key(query: str, days_back: int) -> str:
    return f"{query.lower().strip()}|{days_back}"


def _read_cache() -> dict:
    try:
        if not CACHE_PATH.exists():
            return {}
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_cache(payload: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def _get_cached(query: str, days_back: int) -> DiscussionResult | None:
    payload = _read_cache().get(_cache_key(query, days_back))
    if not isinstance(payload, dict):
        return None

    try:
        saved_at = datetime.fromisoformat(payload["saved_at"])
        if saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - saved_at > timedelta(hours=REDDIT_CACHE_TTL_HOURS):
            return None

        return DiscussionResult(
            verification_available=bool(payload.get("verification_available", False)),
            result_count=int(payload.get("result_count", 0)),
            low_discussion=payload.get("low_discussion"),
            evidence=str(payload.get("evidence", "")),
            query=str(payload.get("query", query)),
            total_comments=(
                int(payload["total_comments"])
                if payload.get("total_comments") is not None
                else None
            ),
            top_score=(
                int(payload["top_score"])
                if payload.get("top_score") is not None
                else None
            ),
            popularity=str(payload.get("popularity", "unknown")),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _put_cache(result: DiscussionResult, days_back: int) -> None:
    payload = _read_cache()
    item = asdict(result)
    item["saved_at"] = datetime.now(timezone.utc).isoformat()
    payload[_cache_key(result.query, days_back)] = item
    _write_cache(payload)


def _throttle() -> None:
    global _last_request_at
    now = time.monotonic()
    wait_for = REDDIT_MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_at)
    if wait_for > 0:
        time.sleep(wait_for)
    _last_request_at = time.monotonic()


def _period(days_back: int) -> str:
    if days_back <= 7:
        return "week"
    if days_back <= 30:
        return "month"
    return "year"


def _headers() -> dict[str, str]:
    return {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    }


def _retry_after_seconds(response: requests.Response) -> float:
    raw = response.headers.get("Retry-After") or response.headers.get("X-Ratelimit-Reset")
    try:
        value = float(raw)
        return max(1.0, min(value, 60.0))
    except (TypeError, ValueError):
        return 10.0


# ============================================================
# OPTIONAL OAUTH
# ============================================================

def _get_oauth_token() -> str | None:
    global _cached_access_token, _cached_access_token_expiry

    direct = os.getenv("REDDIT_ACCESS_TOKEN", "").strip()
    if direct:
        return direct

    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("REDDIT_REFRESH_TOKEN", "").strip()

    if not (client_id and client_secret and refresh_token):
        return None

    if _cached_access_token and time.time() < _cached_access_token_expiry:
        return _cached_access_token

    try:
        _throttle()
        response = requests.post(
            REDDIT_OAUTH_URL,
            auth=(client_id, client_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
            },
            timeout=REDDIT_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 3600))
        if not token:
            return None
        _cached_access_token = str(token)
        _cached_access_token_expiry = time.time() + max(60, expires_in - 60)
        return _cached_access_token
    except (requests.RequestException, ValueError, TypeError):
        return None


# ============================================================
# JSON SEARCH
# ============================================================

def _verify_json(
    title: str,
    days_back: int,
    session: requests.Session,
    token: str,
) -> DiscussionResult:
    query = _clean_query(title)
    params = {
        "q": query,
        "sort": "new",
        "t": _period(days_back),
        "restrict_sr": "off",
        "limit": 100,
        "raw_json": 1,
    }

    headers = _headers()
    headers["Authorization"] = f"Bearer {token}"
    headers["Accept"] = "application/json"

    for attempt in range(REDDIT_MAX_RETRIES_429 + 1):
        try:
            _throttle()
            response = session.get(
                REDDIT_OAUTH_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=REDDIT_REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            return DiscussionResult(False, 0, None, f"Reddit discussion verification unavailable: {exc}", query)

        if response.status_code == 429:
            if attempt < REDDIT_MAX_RETRIES_429:
                time.sleep(_retry_after_seconds(response))
                continue
            return DiscussionResult(False, 0, None, "Reddit discussion verification unavailable: HTTP 429.", query)

        if response.status_code == 401:
            return DiscussionResult(False, 0, None, "Reddit discussion verification unavailable: HTTP 401 (OAuth token rejected).", query)

        if response.status_code != 200:
            return DiscussionResult(False, 0, None, f"Reddit discussion verification unavailable: HTTP {response.status_code}.", query)

        try:
            payload = response.json()
            children = payload.get("data", {}).get("children", [])
            rows = [
                child.get("data", {})
                for child in children
                if isinstance(child, dict) and isinstance(child.get("data"), dict)
            ]
        except (ValueError, TypeError, AttributeError):
            return DiscussionResult(False, 0, None, "Reddit discussion verification unavailable: invalid JSON.", query)

        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days_back))
        filtered = []
        for row in rows:
            created = row.get("created_utc")
            if created is not None:
                try:
                    if datetime.fromtimestamp(float(created), tz=timezone.utc) < cutoff:
                        continue
                except (ValueError, TypeError, OverflowError, OSError):
                    pass
            filtered.append(row)

        count = len(filtered)
        total_comments = sum(max(0, int(row.get("num_comments", 0) or 0)) for row in filtered)
        top_score = max((int(row.get("score", 0) or 0) for row in filtered), default=0)

        high = (
            count >= MIN_REDDIT_DISCUSSIONS_FOR_HIGH_ATTENTION
            or total_comments >= MIN_REDDIT_COMMENTS_FOR_HIGH_ATTENTION
            or top_score >= MIN_REDDIT_TOP_SCORE_FOR_HIGH_ATTENTION
        )
        low = (
            count <= MAX_REDDIT_DISCUSSIONS_FOR_LOW_ATTENTION
            and total_comments <= MAX_REDDIT_COMMENTS_FOR_LOW_ATTENTION
            and top_score <= MAX_REDDIT_TOP_SCORE_FOR_LOW_ATTENTION
        )

        if high:
            popularity = "high"
        elif low:
            popularity = "low"
        else:
            popularity = "medium"

        evidence = (
            f"Reddit returned {count} matching post(s): "
            f"{total_comments} total comments; top post score {top_score}. "
            f"Popularity={popularity}."
        )

        return DiscussionResult(True, count, low, evidence, query, total_comments, top_score, popularity)

    return DiscussionResult(False, 0, None, "Reddit discussion verification unavailable.", query)


# ============================================================
# RSS FALLBACK
# ============================================================

def _verify_rss(
    title: str,
    days_back: int,
    session: requests.Session,
) -> DiscussionResult:
    query = _clean_query(title)
    params = {
        "q": query,
        "sort": "new",
        "t": _period(days_back),
        "restrict_sr": "off",
    }

    for attempt in range(REDDIT_MAX_RETRIES_429 + 1):
        try:
            _throttle()
            response = session.get(
                REDDIT_RSS_URL,
                params=params,
                headers=_headers(),
                timeout=REDDIT_REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            return DiscussionResult(False, 0, None, f"Reddit discussion verification unavailable: {exc}", query)

        if response.status_code == 429:
            if attempt < REDDIT_MAX_RETRIES_429:
                time.sleep(_retry_after_seconds(response))
                continue
            return DiscussionResult(False, 0, None, "Reddit discussion verification unavailable: HTTP 429.", query)

        if response.status_code != 200:
            return DiscussionResult(False, 0, None, f"Reddit discussion verification unavailable: HTTP {response.status_code}.", query)

        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as exc:
            return DiscussionResult(False, 0, None, f"Reddit discussion verification unavailable: RSS parse error: {exc}", query)

        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days_back))
        count = 0
        for entry in root.findall(".//item"):
            pub_date = entry.findtext("pubDate", "")
            if pub_date:
                try:
                    published = parsedate_to_datetime(pub_date)
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    if published < cutoff:
                        continue
                except (TypeError, ValueError, OverflowError):
                    pass
            count += 1

        # RSS does not expose comments or score, so use the original
        # conservative post-count criterion here: <=3 matching posts is
        # low discussion. JSON/OAuth can additionally apply comment/score
        # thresholds.
        low = count <= MAX_REDDIT_DISCUSSIONS_FOR_LOW_ATTENTION
        popularity = "low" if low else "unknown"
        evidence = (
            f"Reddit returned {count} matching public discussion result(s) "
            f"for the selected period; RSS fallback uses <=3 matching posts "
            f"as the low-discussion rule."
        )
        return DiscussionResult(True, count, low, evidence, query, None, None, popularity)

    return DiscussionResult(False, 0, None, "Reddit discussion verification unavailable.", query)


# ============================================================
# PUBLIC API
# ============================================================

def verify_reddit_discussions(
    title: str,
    days_back: int,
    session: requests.Session | None = None,
    use_cache: bool | None = None,
) -> DiscussionResult:
    query = _clean_query(title)
    if not query:
        return DiscussionResult(False, 0, None, "Reddit discussion verification unavailable: empty query.", query)

    # Explicitly injected sessions (used by tests) default to cache-free so
    # their fake responses are authoritative. Production callers can opt into
    # caching explicitly while still reusing a shared requests.Session.
    if use_cache is None:
        use_cache = session is None

    if use_cache:
        cached = _get_cached(query, days_back)
        if cached is not None:
            return cached

    client = session or requests.Session()

    token = _get_oauth_token()
    if token:
        result = _verify_json(title, days_back, client, token)
    else:
        result = _verify_rss(title, days_back, client)

    if use_cache and result.verification_available:
        _put_cache(result, days_back)

    return result


def get_known_audience_size(story) -> int | None:
    for field in (
        "_follower_count",
        "_subscriber_count",
        "follower_count",
        "subscriber_count",
    ):
        value = getattr(story, field, None)
        if value is None:
            continue
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


def evaluate_public_attention(
    coverage: dict,
    discussion: DiscussionResult,
    story,
) -> dict:
    # F is intentionally Reddit-only now. Google News is diagnostic only.
    audience_size = get_known_audience_size(story)
    audience_high = (
        audience_size is not None
        and audience_size > MAX_FOLLOWERS_FOR_LOW_ATTENTION
    )
    audience_gap = (
        audience_size is not None
        and audience_size <= MAX_FOLLOWERS_FOR_LOW_ATTENTION
    )

    discussion_gap = (
        discussion.verification_available
        and discussion.low_discussion is True
    )

    # Reddit is the deciding attention signal. Google News coverage does not
    # block an F classification.
    public_attention_gap = discussion_gap and not audience_high

    if audience_high:
        evidence = (
            "Public-attention gap not established: known follower/subscriber "
            f"count ({audience_size:,}) exceeds the low-audience threshold."
        )
    elif public_attention_gap:
        evidence = (
            "Public-attention gap established: Reddit discussion is verified low; "
            "Google News coverage is diagnostic only."
        )
    elif not discussion.verification_available:
        evidence = "Public-attention gap not established: Reddit verification was unavailable."
    else:
        evidence = "Public-attention gap not established: Reddit discussion is not verified as low."

    return {
        "public_attention_gap": public_attention_gap,
        "discussion_verification_available": discussion.verification_available,
        "reddit_discussion_count": discussion.result_count,
        "reddit_discussion_gap": discussion_gap,
        "reddit_total_comments": discussion.total_comments,
        "reddit_top_score": discussion.top_score,
        "reddit_popularity": discussion.popularity,
        "social_result_count": coverage.get("social_result_count", 0),
        "social_visibility_gap": None,
        "known_audience_size": audience_size,
        "audience_gap": audience_gap,
        "audience_high": audience_high,
        "evidence": evidence,
        "discussion_evidence": discussion.evidence,
    }
