"""Central configuration for Underdog Sports Bot v2."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()

# Reddit read-only public-attention verification
REDDIT_ACCESS_TOKEN = os.getenv("REDDIT_ACCESS_TOKEN", "").strip()
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "").strip()
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
REDDIT_REFRESH_TOKEN = os.getenv("REDDIT_REFRESH_TOKEN", "").strip()
REDDIT_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT",
    "python:underdog-sports-bot:v2.3 (read-only sports attention verifier)",
).strip()

# Safe default: write to local outbox instead of a real social account.
SOCIAL_PUBLISHER = os.getenv("SOCIAL_PUBLISHER", "mock").strip().lower()


NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"

# Broad discovery: do NOT restrict to a tiny list of publishers.
FETCH_LANGUAGE = "en"
FETCH_PAGE_SIZE = 100
DAYS_BACK = 7

# Indian-sports discovery queries. These discover achievements first;
# the scorer decides whether they are genuine underdog stories.
DISCOVERY_QUERIES = [
    # High-recall achievement searches. NewsAPI handles OR/AND better than
    # dozens of ultra-specific phrases, so each query covers a signal family.
    '(India OR Indian) AND (sports OR athlete OR team OR club OR academy) AND (won OR victory OR upset OR historic OR medal OR champion)',
    '(India OR Indian) AND (football OR soccer) AND (academy OR grassroots OR amateur OR club OR school) AND (win OR won OR upset OR victory)',
    '(India OR Indian) AND (football OR soccer) AND (historic OR upset OR shock OR beat OR defeated OR champion)',
    '(India OR Indian) AND (hockey OR cricket OR badminton OR wrestling OR boxing OR athletics) AND (academy OR grassroots OR amateur OR village OR small town)',
    '(India OR Indian) AND (athlete OR team) AND (overcame OR adversity OR resistance OR hardship OR humble OR barefoot OR dirt)',
    '(India OR Indian) AND (team OR club OR athlete) AND (underdog OR unheralded OR overlooked OR unsung OR unknown)',
    '(India OR Indian) AND (sports) AND (first OR record OR gold OR silver OR bronze OR medal OR title)',
    '(India OR Indian) AND (women OR female OR girls) AND (sports) AND (academy OR grassroots OR village OR small town OR first)',
    '(India OR Indian) AND (sports) AND (small club OR small team OR local team OR school team OR college team)',
    '(India OR Indian) AND (sports) AND (defeated OR beat OR upset) AND (favourite OR favorite OR champion OR ranked)',
]

# Scores are intentionally separated:
# achievement = how remarkable the result is
# underdog = evidence of low resources / low status / low support
# coverage_gap = evidence that the story is not widely covered
MIN_FINAL_SCORE = 0.45

# Keep this fairly low while collecting examples; raise after evaluation.
MIN_ACHIEVEMENT_SCORE = 0.25

RAW_DATA_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DATA_DIR = BASE_DIR / "data" / "processed"
POSTED_LOG_PATH = BASE_DIR / "data" / "posted_log.json"

for d in (RAW_DATA_DIR, PROCESSED_DATA_DIR):
    d.mkdir(parents=True, exist_ok=True)
