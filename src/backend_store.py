"""Persistent backend output for the Underdog Sports Bot.

Keeps the pipeline and future website/API layer loosely coupled:
- latest_qualified.json is the current frontend-ready dataset.
- run_history.jsonl stores one compact summary record per run.
No Reddit user content is persisted; only aggregate attention metrics are stored.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _processed_dir() -> Path:
    path = _project_root() / "data" / "processed"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _safe_value(v) for k, v in value.items()}
    return str(value)


def serialize_story(category: str, story, generate_caption_fn: Callable | None = None) -> dict:
    caption = ""
    if generate_caption_fn is not None:
        try:
            caption = generate_caption_fn(story, category)
        except TypeError:
            caption = generate_caption_fn(story)
        except Exception:
            caption = ""

    return {
        "category": category,
        "title": getattr(story, "title", ""),
        "url": getattr(story, "url", ""),
        "entities": _safe_value(getattr(story, "entities", [])),
        "achievement_score": float(getattr(story, "achievement_score", 0.0)),
        "underdog_score": float(getattr(story, "underdog_score", 0.0)),
        "combined_score": float(getattr(story, "combined_score", 0.0)),
        "resource_b": bool(getattr(story, "resource_evidence", False) or getattr(story, "_resource_evidence_origin", None)),
        "resource_evidence": getattr(story, "_resource_evidence", None) or None,
        "resource_evidence_origin": getattr(story, "_resource_evidence_origin", None),
        "f_narrative_evidence": getattr(story, "_f_narrative_evidence", None) or None,
        "public_attention_gap": bool(getattr(story, "public_attention_gap_score", 0.0) >= 1.0),
        "reddit_discussion_count": getattr(story, "reddit_discussion_count", None),
        "reddit_discussion_gap": bool(getattr(story, "reddit_discussion_gap", False)),
        "reddit_total_comments": getattr(story, "reddit_total_comments", None),
        "reddit_top_score": getattr(story, "reddit_top_score", None),
        "reddit_popularity": getattr(story, "reddit_popularity", "unknown"),
        "known_audience_size": getattr(story, "known_audience_size", None),
        "coverage_result_count": getattr(story, "coverage_result_count", 0),
        "coverage_news_result_count": getattr(story, "coverage_news_result_count", 0),
        "coverage_domains": _safe_value(getattr(story, "coverage_domains", [])),
        "institutional_sources": _safe_value(getattr(story, "institutional_sources", [])),
        "social_sources": _safe_value(getattr(story, "social_sources", [])),
        "public_attention_verification": getattr(story, "public_attention_verification", ""),
        "caption": caption,
    }


def save_run_outputs(
    final_stories: list[tuple[str, object]],
    *,
    days_back: int,
    generated_at: datetime | None = None,
    generate_caption_fn: Callable | None = None,
) -> dict[str, str]:
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    stories = [
        serialize_story(category, story, generate_caption_fn)
        for category, story in final_stories
    ]

    latest_payload = {
        "generated_at": generated_at.isoformat(),
        "search_days_back": int(days_back),
        "count": len(stories),
        "categories": {
            "B+F": sum(item["category"] == "B+F" for item in stories),
            "B": sum(item["category"] == "B" for item in stories),
            "F": sum(item["category"] == "F" for item in stories),
        },
        "stories": stories,
    }

    directory = _processed_dir()
    latest_path = directory / "latest_qualified.json"
    history_path = directory / "run_history.jsonl"

    latest_path.write_text(
        json.dumps(latest_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    history_record = {
        "generated_at": latest_payload["generated_at"],
        "search_days_back": int(days_back),
        "qualified_count": len(stories),
        "b_f_count": latest_payload["categories"]["B+F"],
        "b_count": latest_payload["categories"]["B"],
        "f_count": latest_payload["categories"]["F"],
    }
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(history_record, ensure_ascii=False) + "\n")

    return {
        "latest_qualified": str(latest_path),
        "run_history": str(history_path),
    }
