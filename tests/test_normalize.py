from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from opsrisk.normalize import (
    canonical_url,
    clean_text,
    content_hash,
    jaccard,
    title_tokens,
    to_utc_naive,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Example.com/news/a/?utm_source=x&id=2#top", "https://example.com/news/a?id=2"),
        ("http://example.com:80/a/", "https://example.com/a"),
        ("https://example.com/a?b=2&a=1&fbclid=z", "https://example.com/a?a=1&b=2"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
    ],
)
def test_canonical_url(raw, expected):
    assert canonical_url(raw) == expected


def test_tracking_variants_share_one_identity():
    a = canonical_url("https://joc.com/article/x?utm_medium=rss")
    b = canonical_url("https://www.joc.com/article/x/")
    assert a == b


def test_clean_text_decodes_entities_and_strips_wordpress_footer():
    raw = (
        "Tianjin Port Holdings will acquire [&#8230;] The post Tianjin Port Holdings sets "
        "terms for two terminal acquisitions appeared first on Container News ."
    )
    assert clean_text(raw) == "Tianjin Port Holdings will acquire"


def test_clean_text_strips_footer_when_site_name_has_dots():
    raw = "Pressures rose in August The post NY Fed Reports X appeared first on PYMNTS.com ."
    assert clean_text(raw) == "Pressures rose in August"


def test_clean_text_handles_double_encoding_and_markup():
    assert clean_text("<p>R&amp;amp;D &amp; <b>ops</b></p>") == "R&D & ops"


def test_clean_text_strips_read_more_and_truncates():
    text = clean_text("Europe may compensate shipowners. In... Read More", max_chars=20)
    assert "Read More" not in text
    assert len(text) <= 20
    assert text.endswith("…")


def test_near_duplicate_titles_are_similar_and_distinct_ones_are_not():
    a = title_tokens("Typhoon Champi closes Taiwan ports, brings fresh disruption to East Asia")
    b = title_tokens("Typhoon Champi closes Taiwan ports and brings fresh disruption to East Asia")
    c = title_tokens("Typhoon Champi weakens after landfall in the Philippines")
    assert jaccard(a, b) >= 0.8
    assert jaccard(a, c) < 0.5


def test_content_hash_changes_with_text():
    assert content_hash("a", "b") == content_hash("a ", "b")
    assert content_hash("a", "b") != content_hash("a", "c")


def test_to_utc_naive_converts_offsets():
    shanghai = timezone(timedelta(hours=8))
    dt = datetime(2026, 10, 27, 7, 30, 15, 999, tzinfo=shanghai)
    assert to_utc_naive(dt) == datetime(2026, 10, 26, 23, 30, 15)
    assert to_utc_naive(None) is None
    assert to_utc_naive(datetime(2026, 1, 1, tzinfo=timezone.utc)).tzinfo is None
