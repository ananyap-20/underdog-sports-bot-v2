"""FastAPI layer. Read-only: it serves what the pipeline already saved."""
from __future__ import annotations

import math
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import service as svc

app = FastAPI(title="Underdog Sports Bot API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
origins = [o.strip() for o in os.getenv("UNDERDOG_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])

NO_DATA = "No pipeline results found yet. Run `python run_pipeline.py` to create data/processed/latest_qualified.json."


@app.get("/api/health")
def health():
    stories, payload = svc.get_stories()
    return {"status": "ok", "has_data": payload is not None, "demo_mode": svc.demo_mode()}


@app.get("/api/dashboard")
def dashboard():
    stories, payload = svc.get_stories()
    if payload is None:
        raise HTTPException(404, NO_DATA)
    cats = {"B+F": 0, "B": 0, "F": 0}
    for s in stories:
        if s["category"] in cats:
            cats[s["category"]] += 1
    history = svc.load_history()
    return {
        "freshness": svc.freshness(payload),
        "search_days_back": payload.get("search_days_back"),
        "qualified_count": len(stories),
        "categories": cats,
        "run_count": len(history),
        # Saved by run_pipeline.py since this version; None for older runs.
        "pipeline_funnel": payload.get("pipeline_stats"),
        "featured": stories[:3],
    }


@app.get("/api/stories")
def list_stories(
    q: str = Query("", max_length=100),
    category: Literal["", "B+F", "B", "F"] = "",
    attention: Literal["", "gap_found", "discussion_found", "unknown"] = "",
    source: str = Query("", max_length=100),
    sort: Literal["category", "score", "published", "title"] = "category",
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(12, ge=1, le=50),
):
    stories, payload = svc.get_stories()
    if payload is None:
        raise HTTPException(404, NO_DATA)
    sources = sorted({s["source_name"] for s in stories if s["source_name"]})
    qn = svc._norm(q)
    if qn:
        def hay(s):
            return svc._norm(" ".join([s["title"], s["description"] or "", s["source_name"] or "", *s["entities"]]))
        stories = [s for s in stories if qn in hay(s)]
    if category:
        stories = [s for s in stories if s["category"] == category]
    if attention:
        stories = [s for s in stories if s["attention"]["status"] == attention]
    if source:
        stories = [s for s in stories if s["source_name"] == source]
    order = {"B+F": 0, "B": 1, "F": 2}
    if sort == "score":
        stories.sort(key=lambda s: -s["scores"]["combined"])
    elif sort == "published":
        stories.sort(key=lambda s: s["published_at"] or "", reverse=True)
    elif sort == "title":
        stories.sort(key=lambda s: s["title"].lower())
    else:  # pipeline's own order: category, then combined score
        stories.sort(key=lambda s: (order.get(s["category"], 9), -s["scores"]["combined"]))
    total = len(stories)
    start = (page - 1) * page_size
    return {
        "items": stories[start:start + page_size],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
        "available_sources": sources,
        "freshness": svc.freshness(payload),
    }


@app.get("/api/stories/{sid}")
def story_detail(sid: str):
    stories, payload = svc.get_stories()
    if payload is None:
        raise HTTPException(404, NO_DATA)
    for s in stories:
        if s["id"] == sid:
            return {**s, "support_links": svc.support_links_for(s), "freshness": svc.freshness(payload)}
    raise HTTPException(404, "Story not found. It may have been replaced by a newer pipeline run.")


@app.get("/api/runs/latest")
def latest_run():
    history = svc.load_history()
    if not history:
        raise HTTPException(404, "No run history recorded yet.")
    return history[-1]


@app.get("/api/runs")
def runs():
    return {"items": svc.load_history()[-30:]}


@app.get("/api/methodology")
def methodology():
    return svc.METHODOLOGY
