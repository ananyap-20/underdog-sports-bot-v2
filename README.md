# Underdog Sports Bot — Backend Final

This package is the backend milestone for the Underdog Sports Bot. It discovers Indian sports stories, enriches publisher pages for source evidence, classifies genuine resource/underdog signals, verifies Reddit attention, ranks qualified stories, and persists website-ready JSON.

## Backend flow

```text
NewsAPI discovery + Google News fallback
                ↓
Indian sports filtering / deduplication
                ↓
NLP scoring
                ↓
Publisher-page enrichment
                ↓
B/F evidence detection
                ↓
Reddit public-attention verification
                ↓
B / B+F / F classification
                ↓
Rank qualified stories
                ↓
latest_qualified.json + run_history.jsonl
                ↓
Safe social publishing layer
```

## Important Reddit behavior

F is decided by **verified low Reddit discussion + genuine underdog evidence**. Google News volume is diagnostic only and does not block F.

When JSON/OAuth metrics are available, low discussion requires:
- at most 3 matching posts
- at most 15 total comments
- top post score at most 25

High Reddit attention blocks F when any high-attention threshold is met. A 429 or other unavailable response is **unknown**, never low.

The RSS fallback has fewer metrics available, so it uses **<=3 matching public posts** as its low-discussion rule.

Tests that inject a fake HTTP session bypass the Reddit disk cache by default. The production pipeline explicitly enables caching so repeated runs do not unnecessarily repeat successful Reddit checks.

## Reddit OAuth

Reddit's current Data API guidance requires OAuth for API authentication; traffic without OAuth/login credentials can be blocked. Eligible free Data API access is documented at 100 queries/minute per OAuth client id, with rate-limit headers available for monitoring. See Reddit's Data API Wiki before enabling production Reddit access.

Put these values in `.env` when access is configured:

```text
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_REFRESH_TOKEN=
REDDIT_ACCESS_TOKEN=
REDDIT_USER_AGENT=python:underdog-sports-bot:v2.3 (read-only sports attention verifier)
```

The bot does not bypass Reddit rate limits.

## Running the backend

Activate the virtual environment, install dependencies, then run the test suite:

```powershell
python -m pytest -q
```

Run a clean 30-day discovery:

```powershell
python run_pipeline.py --dry-run --fresh
```

The pipeline writes:

```text
data/processed/latest_qualified.json
data/processed/run_history.jsonl
```

`latest_qualified.json` is the contract the future website/API layer can consume. It contains category, title, URL, entities, scores, resource/F evidence, Reddit aggregate metrics, coverage diagnostics, and the generated caption.

## Safe publishing

The default publisher is `mock`, so `--post` does not silently send content to a personal social account unless a real publisher is explicitly configured.

```text
SOCIAL_PUBLISHER=mock
```

## Security

Never commit `.env`, API keys, OAuth tokens, refresh tokens, or social credentials. Rotate any credential that has been exposed.
