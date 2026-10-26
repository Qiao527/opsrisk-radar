"""LLM scorer and hybrid behavior against a fake Messages client (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from opsrisk.hybrid import HybridScorer
from opsrisk.llm_scorer import (
    ASSESSMENT_SCHEMA,
    PROMPT_VERSION,
    LLMCache,
    LLMError,
    LLMScorer,
    LLMUnavailable,
    estimate_cost,
    validate,
)

TITLE = "Strike shuts container terminal in Gdansk"
SUMMARY = "Dockworkers walked out on Monday, halting all vessel operations."


def _answer(**overrides):
    body = {
        "level": "act",
        "severity": 8.0,
        "category": "labor_action",
        "status": "ongoing",
        "evidence": ["Strike shuts container terminal", "halting all vessel operations"],
        "rationale": "Ongoing strike stops a named terminal.",
    }
    body.update(overrides)
    return body


class FakeMessages:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, SimpleNamespace):
            return item
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=item if isinstance(item, str)
                                     else json.dumps(item))],
            usage=SimpleNamespace(input_tokens=900, output_tokens=150,
                                  cache_read_input_tokens=0),
        )


def test_valid_answer_is_parsed_and_costed():
    client = FakeMessages(_answer())
    scorer = LLMScorer(model="claude-opus-5-5", client=client)
    a = scorer.assess(TITLE, SUMMARY)
    assert (a.level, a.severity, a.flags) == ("act", 8.0, [])
    assert a.model == "claude-opus-5-5" and a.prompt_version == PROMPT_VERSION
    assert scorer.usage.calls == 1
    assert scorer.usage.cost_usd == pytest.approx(estimate_cost("claude-opus-5-5", 900, 150))

    req = client.requests[0]
    assert req["output_config"]["format"]["schema"] == ASSESSMENT_SCHEMA
    assert "tool_choice" not in req  # forced tool use is rejected by current models
    assert TITLE in req["messages"][0]["content"]


def test_cost_estimate_uses_list_prices():
    assert estimate_cost("claude-opus-5-5", 1_000_000, 1_000_000) == pytest.approx(24.0)
    assert estimate_cost("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(0.10)
    assert estimate_cost("unknown-model", 1000, 1000) == 0.0


def test_unsupported_evidence_is_dropped_and_act_downgraded():
    a = validate(_answer(evidence=["port authorities confirmed a 2-week closure"]),
                 TITLE, SUMMARY)
    assert a.level == "watch"
    assert a.evidence == []
    assert any("downgraded" in f for f in a.flags)
    assert 4.0 <= a.severity <= 6.9


def test_quotes_match_despite_curly_quotes_and_spacing():
    a = validate(_answer(evidence=["Strike  shuts container terminal"]), TITLE, SUMMARY)
    assert a.level == "act" and a.evidence


def test_severity_is_moved_into_the_level_band():
    a = validate(_answer(level="noise", severity=9.0, evidence=[]), TITLE, SUMMARY)
    assert a.severity == 3.9
    assert any("band" in f for f in a.flags)


@pytest.mark.parametrize(
    "bad",
    [{"level": "act"}, _answer(level="urgent"), _answer(severity="high")],
)
def test_malformed_answers_raise(bad):
    with pytest.raises(LLMError):
        validate(bad, TITLE, SUMMARY)


def test_invalid_json_raises_and_counts_failure():
    scorer = LLMScorer(client=FakeMessages("not json {"))
    with pytest.raises(LLMError, match="JSON"):
        scorer.assess(TITLE, SUMMARY)
    assert scorer.usage.failures == 1


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unusable_stop_reasons_raise(stop_reason):
    resp = SimpleNamespace(stop_reason=stop_reason, content=[],
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    with pytest.raises(LLMError, match=stop_reason):
        LLMScorer(client=FakeMessages(resp)).assess(TITLE, SUMMARY)


def test_api_errors_become_llm_errors():
    scorer = LLMScorer(client=FakeMessages(ConnectionError("reset")))
    with pytest.raises(LLMError, match="ConnectionError"):
        scorer.assess(TITLE, SUMMARY)


def test_missing_credentials_are_reported_as_unavailable():
    with pytest.raises(LLMUnavailable):
        LLMScorer(client=FakeMessages(TypeError("Could not resolve authentication"))).assess(
            TITLE, SUMMARY)


def test_cache_prevents_repeat_calls(tmp_path):
    cache = LLMCache(tmp_path / "c.db")
    first = LLMScorer(client=FakeMessages(_answer()), cache=cache)
    first.assess(TITLE, SUMMARY)
    second = LLMScorer(client=FakeMessages(), cache=cache)  # would fail if called
    a = second.assess(TITLE, SUMMARY)
    assert a.cached and a.level == "act"
    assert (second.usage.calls, second.usage.cache_hits) == (0, 1)


def test_cache_key_depends_on_model_and_text():
    k = LLMCache.key("m1", "t", "s")
    assert k != LLMCache.key("m2", "t", "s")
    assert k != LLMCache.key("m1", "t", "s2")


def test_call_budget_is_enforced():
    scorer = LLMScorer(client=FakeMessages(_answer()), max_calls=1)
    scorer.assess(TITLE, SUMMARY)
    with pytest.raises(LLMError, match="budget"):
        scorer.assess("Another title", "")


def test_hybrid_skips_noise_without_calling_the_llm():
    client = FakeMessages()
    hybrid = HybridScorer(LLMScorer(client=client))
    r = hybrid.score("Forwarder names new chief financial officer", "")
    assert not r.used_llm and client.requests == []
    assert hybrid.skipped == 1


def test_hybrid_uses_llm_judgment_for_candidate_events():
    hybrid = HybridScorer(LLMScorer(client=FakeMessages(_answer(severity=8.5))))
    r = hybrid.score(TITLE, SUMMARY)
    assert r.used_llm and r.score == 8.5
    assert r.detail["rules"]["level"] == "act"
    assert r.detail["llm"]["level"] == "act"


def test_hybrid_falls_back_to_rules_when_llm_fails():
    hybrid = HybridScorer(LLMScorer(client=FakeMessages(ConnectionError("down"))))
    r = hybrid.score(TITLE, SUMMARY)
    assert not r.used_llm
    assert r.score >= 7.0  # the rule score stands
    assert r.detail["llm"].startswith("fallback")
    assert hybrid.fallbacks == 1


def test_pipeline_hybrid_without_credentials_falls_back_and_records_rules(
    project_dir, monkeypatch
):
    from opsrisk import llm_scorer
    from opsrisk.config import load_config
    from opsrisk.database import Database
    from opsrisk.pipeline import score

    monkeypatch.setattr(llm_scorer, "_default_client",
                        lambda: FakeMessages(TypeError("no auth"), TypeError("no auth")))
    cfg = load_config()
    cfg.scoring.scorer = "hybrid-v1"
    cfg.data_dir = project_dir / "data"
    db = Database(project_dir / "data" / "h.db")
    try:
        db.upsert_article("https://e.com/1", TITLE, None, "Wire", "logistics", SUMMARY, "")
        assert score(db, cfg) == 1
        row = db.conn.execute("SELECT scorer, composite_score, detail FROM scores").fetchone()
        assert row["scorer"] == "rules-v2"
        assert row["composite_score"] >= 7.0
        assert "fallback" in json.loads(row["detail"])["llm"]
    finally:
        db.close()
