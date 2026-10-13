# Underdog Sports Bot: website

React + TypeScript (Vite) frontend and a small read-only FastAPI layer over the existing pipeline output.
The website never runs the pipeline and never sees API keys. It reads `data/processed/latest_qualified.json`.

## Run it (PowerShell, from the project root)
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 1. Create real data (uses your .env keys; unchanged command)
python run_pipeline.py

# 2. Start the API (terminal 1)
python -m uvicorn api.main:app --port 8000

# 3. Start the frontend (terminal 2)
cd frontend
npm install
npm run dev        # http://localhost:5173
```
No data yet? Preview the UI with fictional placeholder stories (a yellow "Demo data" banner is always shown):
```powershell
$env:UNDERDOG_DEMO_DATA="1"; python -m uvicorn api.main:app --port 8000
```

## Tests
```powershell
python -m pytest tests          # backend + API
cd frontend; npm test; npm run build
```

## API (read-only)
| Endpoint | Purpose |
|---|---|
| `GET /api/health` | status, whether data exists |
| `GET /api/dashboard` | counts, freshness, featured stories |
| `GET /api/stories?q=&category=&attention=&source=&sort=&page=&page_size=` | search/filter/sort/paginate |
| `GET /api/stories/{id}` | detail + verified support links |
| `GET /api/runs/latest`, `GET /api/runs` | run history |
| `GET /api/methodology` | rules and weights |
Docs at `/api/docs`. There is deliberately no endpoint that triggers the pipeline.

## Backend change (additive)
`src/backend_store.py::serialize_story` now also saves `description`, `published_at`, `source_name`,
`matched_signals`, `coverage_gap_score`, `status_gap_score` (all via `getattr`, so old tests still pass).
Re-run the pipeline once so `latest_qualified.json` contains them.

## Support links ("Back their journey")
Edit `data/support/support_links.json` by hand (see `support_links.example.json`... copy an entry from the schema below).
A link is shown only if: `verification_status` is `"verified"`, `category` is valid, `url` and `evidence_url` are http(s),
`recipient`, `relationship`, `last_verified` are set, `expired` is not true, AND it is tied to the story via
`story_ids` (the story's id from the API) or `recipient` equals an extracted entity name. Otherwise it is dropped.
```json
{"links":[{"recipient":"Athlete Name","relationship":"official page run by the athlete","title":"Training fund",
"url":"https://...","category":"donate_campaign","verification_status":"verified",
"evidence_url":"https://... (page proving the link belongs to them)","last_verified":"2026-10-13",
"restrictions":null,"story_ids":[]}]}
```
Categories: donate_campaign, team_support, sponsor_athlete, official_initiative, equipment_training, official_profile.

## Known gaps
- Stage counts (raw, filtered, enriched, evaluated) are only printed by `run_pipeline.py`, not saved, so the dashboard shows "not saved" instead of guessing. Saving them in `save_run_outputs` would enable a funnel chart.
- Sport, event and per-discussion URLs are not saved by the pipeline, so there are no sport/event filters or discussion links.
- Support links are a manual registry; no automated discovery.
