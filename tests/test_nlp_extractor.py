from src.nlp_extractor import score_article


def test_genuine_underdog_story_scores_above_plain_story():
    article = {
        "title": "Little-known Indian academy shocks former champions",
        "description": (
            "A grassroots team with limited funding produces a historic upset."
        ),
        "content": "The amateur academy had little media attention.",
        "url": "https://example.com/1",
        "publishedAt": "2026-09-15T00:00:00Z",
        "source": {"name": "Example"},
    }

    score = score_article(article)
    assert score.achievement_score > 0
    assert score.underdog_score > 0
    assert score.combined_score > 0


def test_normal_favourite_win_has_less_underdog_signal():
    article = {
        "title": "National champions win comfortably",
        "description": "The favourites dominated the match.",
        "content": "The professional club won as expected.",
        "url": "https://example.com/2",
        "publishedAt": "2026-09-15T00:00:00Z",
        "source": {"name": "Example"},
    }

    score = score_article(article)
    assert score.underdog_score == 0
