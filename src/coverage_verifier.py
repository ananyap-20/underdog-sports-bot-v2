"""
Web-based coverage verification.

Coverage F is only established when:
1. The search itself succeeds.
2. The story has genuinely limited independent publisher coverage.

Search failure is NEVER treated as a coverage gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse
from xml.etree import ElementTree

import requests


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

REQUEST_TIMEOUT = 15

# Two or fewer independent publishers = low-coverage signal.
MAX_DOMAINS_FOR_COVERAGE_GAP = 2


@dataclass
class CoverageResult:
    query: str
    distinct_domains: int
    result_count: int
    domains: list[str]
    coverage_gap: bool
    evidence: str
    verification_available: bool


def _clean_query(title: str) -> str:
    """Turn a title into a reasonable Google News query."""

    title = re.sub(
        r"\s+",
        " ",
        title,
    ).strip()

    title = re.sub(
        r"[^\w\s'-]",
        "",
        title,
    )

    return " ".join(
        title.split()[:18]
    )


def _google_news_url(query: str) -> str:
    return (
        f"{GOOGLE_NEWS_RSS}"
        f"?q={quote_plus(query)}"
        f"&hl=en-IN"
        f"&gl=IN"
        f"&ceid=IN:en"
    )


def _normalize_domain(url: str) -> str | None:
    """
    Convert a URL into an independent publisher domain.

    Examples:

        www.example.com
            -> example.com

        m.example.com
            -> example.com

        amp.example.com
            -> example.com

        economictimes.indiatimes.com
        m.economictimes.indiatimes.com
            -> economictimes.indiatimes.com
    """

    if not url:
        return None

    try:
        hostname = urlparse(url).hostname
    except Exception:
        return None

    if not hostname:
        return None

    hostname = hostname.lower().strip(".")

    # Remove common presentation subdomains.
    prefixes = (
        "www.",
        "m.",
        "mobile.",
        "amp.",
        "amp-",
    )

    changed = True

    while changed:
        changed = False

        for prefix in prefixes:
            if hostname.startswith(prefix):
                hostname = hostname[
                    len(prefix):
                ]
                changed = True
                break

    if not hostname:
        return None

    # Never count Google itself as a publisher.
    if (
        hostname == "google.com"
        or hostname.endswith(".google.com")
    ):
        return None

    return hostname


def _parse_google_news(
    xml_text: str,
) -> list[str]:
    """Extract publisher domains from Google News RSS."""

    root = ElementTree.fromstring(
        xml_text
    )

    domains = []

    for item in root.findall(
        ".//item"
    ):
        source = item.find(
            "source"
        )

        if source is None:
            continue

        source_url = source.attrib.get(
            "url",
            "",
        )

        domain = _normalize_domain(
            source_url
        )

        if domain:
            domains.append(domain)

    return domains


def _run_search(
    query: str,
) -> tuple[bool, list[str], str]:

    url = _google_news_url(
        query
    )

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/153.0 Safari/537.36"
                )
            },
        )

    except requests.RequestException as exc:
        return (
            False,
            [],
            f"Network error: {exc}",
        )

    if response.status_code != 200:
        return (
            False,
            [],
            (
                "Google News returned "
                f"HTTP {response.status_code}."
            ),
        )

    try:
        domains = _parse_google_news(
            response.text
        )

    except ElementTree.ParseError as exc:
        return (
            False,
            [],
            (
                "Could not parse Google News RSS: "
                f"{exc}"
            ),
        )

    return (
        True,
        domains,
        "",
    )


def verify_coverage(
    story,
) -> CoverageResult:
    """
    Verify coverage breadth for a promising story.

    Important:
        A failed search does NOT establish F.

        A successful search with <=2 independent
        publishers provides a low-coverage signal.
    """

    title = (
        getattr(
            story,
            "title",
            "",
        )
        or ""
    )

    query = _clean_query(
        title
    )

    success, domains, error = _run_search(
        query
    )

    if not success:
        return CoverageResult(
            query=query,
            distinct_domains=0,
            result_count=0,
            domains=[],
            coverage_gap=False,
            verification_available=False,
            evidence=(
                "Coverage verification unavailable. "
                f"{error}"
            ),
        )

    unique_domains = sorted(
        set(domains)
    )

    # Retry with a shorter query if the title
    # produced no usable publisher results.
    if not unique_domains:

        fallback_words = [
            word
            for word in query.split()
            if len(word) >= 4
        ]

        fallback_query = " ".join(
            fallback_words[:8]
        )

        if (
            fallback_query
            and fallback_query != query
        ):

            (
                success2,
                domains2,
                error2,
            ) = _run_search(
                fallback_query
            )

            if success2:
                unique_domains = sorted(
                    set(domains2)
                )
                query = fallback_query

            else:
                return CoverageResult(
                    query=query,
                    distinct_domains=0,
                    result_count=0,
                    domains=[],
                    coverage_gap=False,
                    verification_available=False,
                    evidence=(
                        "Coverage verification unavailable "
                        "after both searches. "
                        f"{error2}"
                    ),
                )

    result_count = len(
        domains
    )

    if result_count == 0:
        return CoverageResult(
            query=query,
            distinct_domains=0,
            result_count=0,
            domains=[],
            coverage_gap=False,
            verification_available=True,
            evidence=(
                "Search completed, but no publisher "
                "domains could be extracted. "
                "Coverage gap was not established."
            ),
        )

    coverage_gap = (
        len(unique_domains)
        <= MAX_DOMAINS_FOR_COVERAGE_GAP
    )

    if coverage_gap:
        evidence = (
            f"Google News returned "
            f"{result_count} result(s) across "
            f"{len(unique_domains)} independent "
            f"publisher domain(s): "
            f"{', '.join(unique_domains)}."
        )

    else:
        evidence = (
            f"Google News returned "
            f"{result_count} result(s) across "
            f"{len(unique_domains)} independent "
            f"publisher domain(s). "
            "The story does not meet the "
            "current low-coverage threshold."
        )

    return CoverageResult(
        query=query,
        distinct_domains=len(
            unique_domains
        ),
        result_count=result_count,
        domains=unique_domains,
        coverage_gap=coverage_gap,
        verification_available=True,
        evidence=evidence,
    )