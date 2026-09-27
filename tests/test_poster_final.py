from types import SimpleNamespace

from src import poster


def story(category="B+F"):
    return SimpleNamespace(
        title="From dirt ground to historic medal",
        description="A major achievement after training on dirt pitches.",
        content="The athlete overcame financial difficulties.",
        _source_text="financial difficulties and dirt pitches",
        _resource_evidence="financial difficulties",
        _f_narrative_evidence="training on dirt pitches",
        story_category=category,
        url="https://example.com/story",
        entities=[],
    )


def test_caption_keeps_url_and_category_language():
    caption = poster.generate_caption(story("B+F"))
    assert "UNDERDOG SPOTLIGHT" in caption
    assert "financial difficulties" in caption
    assert "https://example.com/story" in caption
    assert len(caption) <= poster.TWITTER_MAX_CHARS


def test_b_caption_does_not_claim_low_coverage():
    caption = poster.generate_caption(story("B"), category="B")
    assert "RESOURCE STORY" in caption
    assert "financial difficulties" in caption
    assert "barely any coverage" not in caption


def test_f_caption_uses_narrative_evidence():
    caption = poster.generate_caption(story("F"), category="F")
    assert "UNDERCOVERED STORY" in caption
    assert "dirt pitches" in caption


def test_dry_run_does_not_call_social_apis(monkeypatch):
    called = {"twitter": False, "instagram": False}

    monkeypatch.setattr(
        poster,
        "post_to_twitter",
        lambda caption: called.__setitem__("twitter", True) or True,
    )
    monkeypatch.setattr(
        poster,
        "post_to_instagram",
        lambda caption, image_url: called.__setitem__("instagram", True) or True,
    )

    result = poster.process_story(
        story(),
        dry_run=True,
        image_url="https://example.com/image.jpg",
    )

    assert result["posted"] is False
    assert called == {"twitter": False, "instagram": False}


def test_duplicate_story_is_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(poster.settings, "POSTED_LOG_PATH", tmp_path / "posted.json")
    poster.save_posted_log({"https://example.com/story"})

    result = poster.process_story(story(), dry_run=False)

    assert result["duplicate"] is True
    assert result["posted"] is False


def test_successful_publish_records_url(monkeypatch, tmp_path):
    monkeypatch.setattr(poster.settings, "POSTED_LOG_PATH", tmp_path / "posted.json")
    monkeypatch.setattr(poster, "post_to_twitter", lambda caption: True)
    monkeypatch.setattr(poster, "post_to_instagram", lambda caption, image_url: False)

    result = poster.process_story(story(), dry_run=False)

    assert result["twitter"] is True
    assert result["posted"] is True
    assert "https://example.com/story" in poster.load_posted_log()
