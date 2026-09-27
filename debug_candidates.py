"""Print every fetched candidate with evidence and scores."""
from src.data_fetcher import fetch_from_newsapi
from src.nlp_extractor import score_article

query = "Indian football academy"
articles = fetch_from_newsapi(query, 7)

for i, article in enumerate(articles, 1):
    s = score_article(article)
    print(f"\n{i}. {s.title}")
    print(f"   Achievement : {s.achievement_score}")
    print(f"   Underdog    : {s.underdog_score}")
    print(f"   Coverage    : {s.coverage_gap_score}")
    print(f"   Status gap  : {s.status_gap_score}")
    print(f"   FINAL       : {s.combined_score}")
    print("   Evidence    :", "; ".join(s.matched_signals[:12]) or "none")
    print("   Description :", s.description)
