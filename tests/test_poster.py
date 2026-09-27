from types import SimpleNamespace

from src.poster import generate_caption


def test_caption_uses_evidence():
    story = SimpleNamespace(
        title="From dirt ground to star",
        description="An athlete trained on dirt pitches and overcame family resistance.",
        url="https://example.com/story",
        combined_score=0.505,
        achievement_score=0.75,
        underdog_score=0.512,
        coverage_gap_score=0.0,
        status_gap_score=0.0,
        source_name="Example",
        entities=[],
        matched_signals=[
            r"humble:\bdirt (pitch|ground|field)s?\b",
            r"barrier:\bfamily resistance\b",
        ],
    )
    caption = generate_caption(story)
    assert "dirt pitches" in caption
    assert "resistance" in caption
    assert "A remarkable sporting achievement" not in caption
