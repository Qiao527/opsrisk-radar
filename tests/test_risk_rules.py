"""Behavioral specification for rules-v2, one case per labeling-guide rule.

Headlines are synthetic so these tests do not overlap the evaluation set.
"""

from __future__ import annotations

import pytest

from opsrisk.risk_rules import assess
from opsrisk.signals import severity_label


@pytest.mark.parametrize(
    ("title", "summary"),
    [
        ("Dockworkers strike halts operations at Port of Gdansk", ""),
        ("Cyclone shuts Chittagong port and garment plants", ""),
        ("Ransomware attack knocks out carrier booking systems", ""),
        ("Fire at semiconductor plant halts output for weeks", ""),
        ("Rail line closed after derailment near Chicago", ""),
        ("Missile strikes on tankers force diversions from Red Sea", ""),
        ("Ban on rare earth exports takes effect Dec. 1", "Licenses required effective Dec. 1"),
    ],
)
def test_ongoing_interruptions_are_high(title, summary):
    a = assess(title, summary)
    assert a.level == "act", a
    assert severity_label(a.score) in {"HIGH", "CRITICAL"}
    assert a.evidence


@pytest.mark.parametrize(
    "title",
    [
        "Union and terminal operators reach tentative labor deal",
        "Strike ends at Antwerp container terminals",
        "Port reopens after storm passes",
        "Shippers warn of possible rail strike next month",
        "Regulators propose new tariffs on steel imports",
        "Hurricane season outlook points to above-average storms",
    ],
)
def test_resolved_or_speculative_events_are_medium_not_high(title):
    a = assess(title, "")
    assert severity_label(a.score) == "MEDIUM", a
    assert a.level == "watch"


@pytest.mark.parametrize(
    "title",
    [
        "Logistics firm strikes deal to acquire regional carrier",
        "Carrier reports record Q3 earnings on higher volumes",
        "Warehouse automation market projected to reach $40 billion by 2030",
        "Shipping line names new chief operating officer",
        "How to build a resilient supplier network",
        "Forwarder opens new office in Rotterdam",
    ],
)
def test_noise_is_low(title):
    a = assess(title, "")
    assert severity_label(a.score) == "LOW", a


def test_closing_a_gap_is_not_a_closure():
    assert assess("Closing the skills gap in transportation", "").level != "act"


def test_deal_citing_a_disruption_ranks_below_the_disruption_itself():
    deal = assess("Utility agrees to buy coal as war disrupts supply", "")
    event = assess("Strike shuts coal terminal", "")
    assert deal.score < event.score
    assert severity_label(deal.score) == "MEDIUM"


def test_chokepoint_raises_severity_within_the_band():
    plain = assess("Strike halts operations at regional port", "")
    choke = assess("Strike halts operations at port near Suez", "")
    assert choke.score > plain.score


def test_tariff_without_date_is_watch_with_date_is_act():
    assert assess("Government announces tariffs on furniture", "").level == "watch"
    dated = assess("Government sets tariffs on furniture", "Duties apply effective Nov. 3.")
    assert dated.level == "act"


def test_interruption_only_in_summary_is_medium():
    a = assess("Middle East tensions reshape operations", "An outage hit regional data centers.")
    assert a.level == "watch"
    assert severity_label(a.score) == "MEDIUM"


def test_every_score_is_explained():
    a = assess("Typhoon closes ports in southern China", "")
    detail = a.as_detail()
    assert detail["scorer"] == "rules-v2"
    assert detail["reason"]
    assert "severe_weather" in detail["categories"]
