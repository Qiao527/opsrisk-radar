from __future__ import annotations

from opsrisk.scorer import (
    SUMMARY_WEIGHT,
    TITLE_WEIGHT,
    compute_composite,
    make_article_score,
    score_article,
)

WEIGHTS = {
    "disruption_risk": 0.45,
    "business_impact": 0.25,
    "strategic_relevance": 0.05,
    "actionability": 0.15,
    "signal_strength": 0.10,
}
DIMENSIONS = list(WEIGHTS)


def test_article_with_no_keywords_gets_floor_score_everywhere():
    scores = score_article("Company opens new office", "A short tour of the building.")
    assert scores == dict.fromkeys(DIMENSIONS, 1.0)


def test_title_match_counts_more_than_summary_match():
    in_title = score_article("Port congestion worsens", "")
    in_summary = score_article("Weekly update", "Port congestion worsens")
    assert in_title["disruption_risk"] == TITLE_WEIGHT
    assert in_summary["disruption_risk"] == max(1.0, SUMMARY_WEIGHT)
    assert in_title["disruption_risk"] > in_summary["disruption_risk"]


def test_pronoun_us_is_not_treated_as_united_states():
    pronoun = score_article("Let us help you plan your week", "")
    country = score_article("US and China agree on shipping rules", "")
    assert pronoun["signal_strength"] == 1.0
    assert country["signal_strength"] > 1.0


def test_lowercase_ai_word_fragments_do_not_count_as_ai():
    assert score_article("Said the ai ai captain", "")["strategic_relevance"] == 1.0
    assert score_article("AI planning tools for warehouses", "")["strategic_relevance"] > 1.0


def test_distinct_disruption_signals_add_up():
    one = score_article("Port backlog", "")["disruption_risk"]
    two = score_article("Port backlog causes shortage", "")["disruption_risk"]
    assert two == one + TITLE_WEIGHT


def test_documented_calibration_example_still_ranks_medium():
    """README and docs/methodology.md show this headline at D10 / MEDIUM."""
    s = make_article_score(
        1,
        "Toyota Suppliers Warn of Parts Shortages Tied to Iran War",
        "Japanese suppliers say a shortage of components could disrupt output.",
        WEIGHTS,
    )
    assert s.disruption_risk == 10.0
    assert s.composite_score >= 4.0


def test_scores_are_capped_at_ten():
    title = "Strike, hurricane, cyberattack, shortage, recall and bankruptcy hit suppliers"
    assert score_article(title, "")["disruption_risk"] == 10.0


def test_market_forecast_has_business_impact_penalized():
    forecast = make_article_score(
        1, "Robotics market projected to grow to $9 billion by 2030", "", WEIGHTS
    )
    actual = make_article_score(1, "Carrier reports $9 billion loss", "", WEIGHTS)
    assert forecast.business_impact < actual.business_impact


def test_composite_is_weighted_sum_rounded():
    scores = dict.fromkeys(DIMENSIONS, 1.0) | {"disruption_risk": 10.0}
    # 10*0.45 + 1*(0.25 + 0.05 + 0.15 + 0.10)
    assert compute_composite(scores, WEIGHTS) == 5.05


def test_every_dimension_stays_in_range():
    s = make_article_score(
        7,
        "War and sanctions trigger $2 billion tariff shock, 40% freight rate spike",
        "Customs compliance deadline effective March 1 under new regulation in the EU.",
        WEIGHTS,
    )
    for value in (
        s.disruption_risk,
        s.business_impact,
        s.strategic_relevance,
        s.actionability,
        s.signal_strength,
        s.composite_score,
    ):
        assert 1.0 <= value <= 10.0
