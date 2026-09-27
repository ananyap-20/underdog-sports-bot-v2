"""Explainable scorer for high-achievement, overlooked Indian sports stories.

The scorer is deliberately evidence-based:
- Achievement: how meaningful the sporting result/achievement is.
- Underdog context: humble beginnings, basic facilities, funding/support
  limitations, obscure/grassroots status, or barriers overcome.
- Coverage gap: explicit evidence of being overlooked/under-reported.
  Publisher count is NOT treated as proof of a coverage gap.
- Status gap: evidence that the opponent/event had substantially higher status.

A story is not accepted just because the article contains the word
"underdog".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import spacy

from config import settings

_nlp = None


def get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError as exc:
            raise RuntimeError(
                "spaCy English model is missing. Run: "
                "python -m spacy download en_core_web_sm"
            ) from exc
    return _nlp


# These are intentionally broader than the old scorer.
# We want evidence of an underdog journey, not only explicit funding language.
ACHIEVEMENT_PATTERNS = [
    r"\bhistoric\b",
    r"\bhistory[- ]making\b",
    r"\bfirst\b",
    r"\brecord\b|\brecord[- ]breaking\b",
    r"\bchampion(ship)?\b",
    r"\bwins?\b|\bwon\b|\bvictory\b",
    r"\bbeat\b|\bbeats\b|\bbeaten\b",
    r"\bdefeat(ed|s)?\b",
    r"\bupset\b",
    r"\bshock(ed|s|ing)?\b",
    r"\bstun(ned|s|ning)?\b",
    r"\bmedal\b|\bgold\b|\bsilver\b|\bbronze\b",
    r"\bfinal\b|\bfinalist\b",
    r"\bqualif(y|ied|ication)\b",
    r"\btitle\b|\btrophy\b",
    r"\bAsian Games\b|\bOlympic(s)?\b|\bWorld Cup\b|\bworld championship\b",
]

# Human-readable signal families. These capture the kinds of evidence visible
# in the Lalremsiami example: dirt pitches, academy beginnings, family/social
# barriers, humble origins, and resource constraints.
HUMBLE_BEGINNINGS_PATTERNS = [
    r"\bdirt (pitch|ground|field)s?\b",
    r"\bbarefoot\b",
    r"\bhumble beginnings?\b",
    r"\bhumble background\b",
    r"\bfrom a (small|remote|rural) (village|town|district)\b",
    r"\bgrew up in\b",
    r"\braised in\b",
    r"\bfrom a small village\b",
    r"\bfrom a remote village\b",
    r"\bsmall[- ]town\b",
    r"\brural\b",
    r"\bremote\b",
    r"\bmodest background\b",
]

RESOURCE_LIMITATION_PATTERNS = [
    r"\bno funding\b",
    r"\bwithout funding\b",
    r"\bunfunded\b",
    r"\blittle funding\b",
    r"\blimited funding\b",
    r"\bunderfunded\b",
    r"\bpoorly funded\b",
    r"\blimited resources?\b",
    r"\black(s|ed)? (of )?(funding|support|resources|facilities|equipment)\b",
    r"\bwithout (proper )?(facilities|equipment|support)\b",
    r"\bbasic facilities\b",
    r"\bpoor facilities\b",
    r"\bprimitive facilities\b",
    r"\btraining on\b.*\b(dirt|basic|rough)\b",
]

GRASSROOTS_OBSCURITY_PATTERNS = [
    r"\bgrassroots\b",
    r"\bunheralded\b",
    r"\blittle[- ]known\b",
    r"\blittle known\b",
    r"\blow[- ]profile\b",
    r"\bunknown\b",
    r"\bsmall club\b",
    r"\bsmall team\b",
    r"\bamateur\b",
    r"\bacademy\b",
    r"\bschool team\b",
    r"\bcollege team\b",
    r"\buniversity team\b",
    r"\bcommunity team\b",
    r"\bvolunteer[- ]run\b",
    r"\bself[- ]funded\b",
]

BARRIER_PATTERNS = [
    r"\bovercam(e|ing|es)\b",
    r"\bovercame\b",
    r"\bdespite\b",
    r"\bagainst all odds\b",
    r"\badversity\b",
    r"\bstruggled\b",
    r"\bstruggle\b",
    r"\bbarrier(s)?\b",
    r"\bresistance\b",
    r"\bfamily resistance\b",
    r"\bfinancial hardship\b",
    r"\bpoverty\b",
    r"\bdiscrimination\b",
    r"\bno opportunity\b",
    r"\black of opportunity\b",
    r"\bhad to leave home\b",
]

COVERAGE_GAP_PATTERNS = [
    r"\blittle coverage\b",
    r"\blittle media attention\b",
    r"\bno media attention\b",
    r"\boverlooked\b",
    r"\bignored\b",
    r"\bforgotten\b",
    r"\bunsung\b",
    r"\bunder[- ]reported\b",
    r"\bnot widely reported\b",
    r"\brarely reported\b",
    r"\bdeserves more attention\b",
    r"\bdeserves more recognition\b",
    r"\bdeserves recognition\b",
]

STATUS_GAP_PATTERNS = [
    r"\bformer champion\b",
    r"\breigning champion\b",
    r"\bnational champion\b",
    r"\bworld champion\b",
    r"\bprofessional\b",
    r"\bpremier league\b",
    r"\btop[- ]ranked\b",
    r"\branked (number )?[0-9]+\b",
    r"\bfavourites?\b|\bfavorites?\b",
    r"\bheavily favou?red\b",
]


@dataclass
class ScoredStory:
    title: str
    url: str
    description: str
    published_at: str
    source_name: str
    achievement_score: float
    underdog_score: float
    coverage_gap_score: float
    status_gap_score: float
    entities: list[str] = field(default_factory=list)
    matched_signals: list[str] = field(default_factory=list)
    combined_score: float = 0.0

    def __post_init__(self):
        # Coverage is no longer automatically 1.0 for a single publisher.
        # The underdog journey is the central signal.
        self.combined_score = round(
            0.40 * self.achievement_score
            + 0.40 * self.underdog_score
            + 0.10 * self.coverage_gap_score
            + 0.10 * self.status_gap_score,
            3,
        )


def pattern_hits(text: str, patterns: list[str]) -> list[str]:
    text_lower = text.lower()
    return [p for p in patterns if re.search(p, text_lower)]


def family_score(
    text: str,
    families: list[tuple[str, list[str]]],
) -> tuple[float, list[str]]:
    """Score independent evidence families.

    A single weak keyword should not dominate. Each family contributes once,
    while multiple hits inside a family provide a small bonus.
    """
    total = 0.0
    labels = []

    for family_name, patterns in families:
        hits = pattern_hits(text, patterns)
        if not hits:
            continue

        # First hit = full family evidence; extra hits add a small amount.
        family_value = min(1.0, 0.65 + 0.10 * (len(hits) - 1))
        total += family_value
        labels.extend(f"{family_name}:{h}" for h in hits)

    if not families:
        return 0.0, labels

    # Four independent families can produce a very strong underdog signal.
    return round(min(total / len(families), 1.0), 3), labels


def extract_entities(text: str) -> list[str]:
    doc = get_nlp()(text)
    return sorted(
        {
            ent.text.strip()
            for ent in doc.ents
            if ent.label_ in ("ORG", "PERSON", "GPE", "EVENT")
        }
    )


def score_article(article: dict, publisher_count: int = 1) -> ScoredStory:
    title = article.get("title") or ""
    description = article.get("description") or ""
    content = article.get("content") or ""
    source_name = ((article.get("source") or {}).get("name")) or "Unknown source"

    text = " ".join([title, description, content])

    a_hits = pattern_hits(text, ACHIEVEMENT_PATTERNS)
    achievement = round(
        min(len(a_hits) / 4.0, 1.0), 3
    )

    underdog, u_hits = family_score(
        text,
        [
            ("humble", HUMBLE_BEGINNINGS_PATTERNS),
            ("resources", RESOURCE_LIMITATION_PATTERNS),
            ("grassroots", GRASSROOTS_OBSCURITY_PATTERNS),
            ("barrier", BARRIER_PATTERNS),
        ],
    )

    gap_hits = pattern_hits(text, COVERAGE_GAP_PATTERNS)
    coverage_gap = round(min(len(gap_hits) / 2.0, 1.0), 3)

    status_hits = pattern_hits(text, STATUS_GAP_PATTERNS)
    status_gap = round(min(len(status_hits) / 2.0, 1.0), 3)

    signals = (
        [f"achievement:{x}" for x in a_hits]
        + u_hits
        + [f"coverage:{x}" for x in gap_hits]
        + [f"status:{x}" for x in status_hits]
    )

    return ScoredStory(
        title=title or "Untitled",
        url=article.get("url") or "",
        description=description,
        published_at=article.get("publishedAt") or "",
        source_name=source_name,
        achievement_score=achievement,
        underdog_score=underdog,
        coverage_gap_score=coverage_gap,
        status_gap_score=status_gap,
        entities=extract_entities(text),
        matched_signals=signals,
    )


def _dedupe_key(article: dict) -> str:
    key = (article.get("url") or article.get("title") or "").lower().strip()
    if article.get("url"):
        return key

    key = re.sub(r"[^a-z0-9 ]+", "", key)
    return re.sub(r"\s+", " ", key)


def filter_and_rank(articles: list[dict]) -> list[ScoredStory]:
    """Score, filter and rank stories.

    We do not use publisher count as proof of low coverage. If multiple
    independent copies are supplied, they are simply deduplicated here.
    """
    unique = {}
    for article in articles:
        unique.setdefault(_dedupe_key(article), article)

    scored = [score_article(article) for article in unique.values()]

    passed = [
        s
        for s in scored
        if s.combined_score >= settings.MIN_FINAL_SCORE
        and s.achievement_score >= settings.MIN_ACHIEVEMENT_SCORE
        and s.underdog_score > 0
    ]

    return sorted(passed, key=lambda s: s.combined_score, reverse=True)


if __name__ == "__main__":
    sample = {
        "title": "From dirt ground to star: Indian athlete aims for gold",
        "description": (
            "After training on dirt pitches and overcoming family resistance, "
            "the academy athlete became an Asian Games medallist."
        ),
        "content": "",
        "url": "https://example.com/story",
        "publishedAt": "2026-09-15T00:00:00Z",
        "source": {"name": "Example Sports"},
    }
    result = score_article(sample)
    print(result)
