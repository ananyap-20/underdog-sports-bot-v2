"""Read-only data service for the website API.

Reads the files the existing pipeline already writes (src/backend_store.py):
  data/processed/latest_qualified.json
  data/processed/run_history.jsonl
It never runs the pipeline and never touches API keys.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
SAMPLE = ROOT / "data" / "sample" / "latest_qualified.sample.json"
SUPPORT_FILE = ROOT / "data" / "support" / "support_links.json"
STALE_AFTER_HOURS = 24 * 7

CATEGORY_LABELS = {
    "B+F": "Resource story + attention gap",
    "B": "Resource story",
    "F": "Attention-gap story",
}
SUPPORT_CATEGORIES = {
    "donate_campaign", "team_support", "sponsor_athlete",
    "official_initiative", "equipment_training", "official_profile",
}


def demo_mode() -> bool:
    return os.getenv("UNDERDOG_DEMO_DATA", "").strip() == "1"


def story_id(url: str) -> str:
    return hashlib.sha1((url or "").strip().encode("utf-8")).hexdigest()[:12]


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_latest() -> dict | None:
    """Return the latest payload (+ is_demo flag) or None if nothing exists."""
    data = _read_json(PROCESSED / "latest_qualified.json")
    if isinstance(data, dict) and isinstance(data.get("stories"), list):
        data["is_demo"] = False
        return data
    if demo_mode():
        data = _read_json(SAMPLE)
        if isinstance(data, dict):
            data["is_demo"] = True
            return data
    return None


def load_history() -> list[dict]:
    path = PROCESSED / "run_history.jsonl"
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except ValueError:
                continue
    except OSError:
        pass
    return rows


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def safe_url(url) -> str | None:
    """Only http(s) URLs with a host are ever passed to the browser."""
    if not isinstance(url, str):
        return None
    p = urlparse(url.strip())
    return url.strip() if p.scheme in ("http", "https") and p.netloc else None


def attention_status(row: dict) -> str:
    """Honest three-way view of the Reddit check.
    The pipeline stores count=0 and gap=False when Reddit could not be reached
    (evidence text says "unavailable"), so that case must be reported as unknown."""
    note = str(row.get("public_attention_verification") or "").lower()
    if row.get("reddit_discussion_count") is None or "unavailable" in note:
        return "unknown"
    if row.get("reddit_discussion_gap"):
        return "gap_found"
    if (row.get("reddit_discussion_count") or 0) > 0:
        return "discussion_found"
    return "unknown"


def serialize(row: dict) -> dict:
    """Normalise one stored record for the frontend. Missing fields stay null."""
    url = safe_url(row.get("url"))
    cat = row.get("category") if row.get("category") in CATEGORY_LABELS else None
    out = {
        "id": story_id(row.get("url", "")),
        "category": cat,
        "category_label": CATEGORY_LABELS.get(cat),
        "title": row.get("title") or "Untitled story",
        "url": url,
        "entities": [e for e in (row.get("entities") or []) if isinstance(e, str)],
        "description": row.get("description"),
        "published_at": row.get("published_at"),
        "source_name": row.get("source_name"),
        "image_url": safe_url(row.get("image_url")),
        "matched_signals": row.get("matched_signals") or [],
        "scores": {
            "achievement": _num(row.get("achievement_score")),
            "underdog": _num(row.get("underdog_score")),
            "combined": _num(row.get("combined_score")),
            "coverage_gap": row.get("coverage_gap_score"),
            "status_gap": row.get("status_gap_score"),
        },
        "evidence": {
            "resource": row.get("resource_evidence"),
            "resource_origin": row.get("resource_evidence_origin"),
            "narrative": row.get("f_narrative_evidence"),
        },
        "attention": {
            "status": attention_status(row),
            "gap_flag": bool(row.get("public_attention_gap")),
            "reddit_discussion_count": row.get("reddit_discussion_count"),
            "reddit_total_comments": row.get("reddit_total_comments"),
            "reddit_top_score": row.get("reddit_top_score"),
            "reddit_popularity": row.get("reddit_popularity") or "unknown",
            "known_audience_size": row.get("known_audience_size"),
            "note": row.get("public_attention_verification") or None,
        },
        "coverage": {
            "result_count": row.get("coverage_result_count"),
            "news_result_count": row.get("coverage_news_result_count"),
            "domains": row.get("coverage_domains") or [],
            "institutional_sources": row.get("institutional_sources") or [],
            "social_sources": row.get("social_sources") or [],
        },
        "caption": row.get("caption") or None,
    }
    return out


def get_stories() -> tuple[list[dict], dict | None]:
    payload = load_latest()
    if not payload:
        return [], None
    return [serialize(r) for r in payload["stories"] if isinstance(r, dict)], payload


def freshness(payload: dict | None) -> dict:
    gen = payload.get("generated_at") if payload else None
    age = None
    try:
        dt = datetime.fromisoformat(gen)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except (TypeError, ValueError):
        pass
    return {
        "generated_at": gen,
        "age_hours": round(age, 1) if age is not None else None,
        "is_stale": age is None or age > STALE_AFTER_HOURS,
        "is_demo": bool(payload and payload.get("is_demo")),
    }


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def validate_support_link(link: dict, story: dict) -> bool:
    """A link is shown only if EVERY rule holds. Anything else is dropped."""
    if link.get("verification_status") != "verified":
        return False
    if link.get("category") not in SUPPORT_CATEGORIES:
        return False
    if not safe_url(link.get("url")) or not safe_url(link.get("evidence_url")):
        return False
    if not (link.get("recipient") and link.get("relationship") and link.get("last_verified")):
        return False
    if link.get("expired"):
        return False
    # Recipient binding: explicit story id, or recipient is an extracted entity.
    ids = link.get("story_ids") or []
    ents = {_norm(e) for e in story["entities"]}
    return story["id"] in ids or _norm(link["recipient"]) in ents


def support_links_for(story: dict) -> list[dict]:
    data = _read_json(SUPPORT_FILE)
    links = data.get("links") if isinstance(data, dict) else None
    if not isinstance(links, list):
        return []
    keep = []
    for l in links:
        if isinstance(l, dict) and validate_support_link(l, story):
            keep.append({k: l.get(k) for k in (
                "recipient", "relationship", "title", "url", "category",
                "verification_status", "evidence_url", "last_verified", "restrictions")})
    return keep


METHODOLOGY = {
    "category_rules": [
        {"code": "B+F", "label": CATEGORY_LABELS["B+F"],
         "rule": "Resource-constraint evidence (B) AND a verified Reddit attention gap (F)."},
        {"code": "B", "label": CATEGORY_LABELS["B"],
         "rule": "Resource-constraint evidence (B) found in the article text or page."},
        {"code": "F", "label": CATEGORY_LABELS["F"],
         "rule": "Verified low Reddit attention (F) AND a genuine underdog signal (resource evidence or narrative evidence)."},
        {"code": "NONE", "label": "Not qualified",
         "rule": "Neither rule is met; the story is not published."},
    ],
    "score_formulas": [
        {"stage": "After NLP scoring (src/nlp_extractor.py)",
         "weights": {"achievement": 0.40, "underdog": 0.40, "coverage_gap": 0.10, "status_gap": 0.10}},
        {"stage": "After public-attention verification (run_pipeline.py)",
         "weights": {"achievement": 0.40, "underdog": 0.25, "public_attention_gap": 0.20, "status_gap": 0.15}},
    ],
    "no_score_gate": "combined_score only ranks stories that already satisfy the B/F evidence rules. It never rejects a story.",
    "config": {"min_final_score_setting": 0.45, "min_achievement_score_setting": 0.25,
               "note": "Defined in config/settings.py; the pipeline's final B/F decision does not apply a score threshold."},
}
