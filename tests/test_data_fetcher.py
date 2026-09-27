from src.data_fetcher import is_indian_sports_article


def article(title, description):
    return {"title": title, "description": description, "content": ""}


def test_indian_hockey_story_is_relevant():
    a = article(
        "From dirt ground to star: Lalremsiami Aims for Asiad Gold",
        "Mizoram's first female Olympian and Asian Games medallist trained on dirt pitches.",
    )
    assert is_indian_sports_article(a)


def test_us_high_school_scoreboard_is_rejected():
    a = article(
        "Ohio high school football scores, Week 4 statewide results",
        "Here are statewide scores from Ohio high school football games played Friday.",
    )
    assert not is_indian_sports_article(a)
