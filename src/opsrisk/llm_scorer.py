"""LLM-based contextual risk assessment with validation, caching and cost tracking.

The model receives the labeling guide's definitions and one article, and must
answer with JSON matching ``ASSESSMENT_SCHEMA`` (enforced by structured
outputs). The answer is then checked semantically:

* the severity is moved into the band that matches the stated level;
* every evidence quote must appear verbatim in the article; unsupported
  quotes are dropped, and an "act" answer with no surviving evidence is
  downgraded to "watch";
* refusals, truncation and malformed JSON raise ``LLMError`` so the caller
  can fall back to the rule-based scorer.

Results are cached by (model, prompt version, article text), so re-running
the pipeline or an evaluation never pays twice for the same judgment.

Requires the optional ``anthropic`` package (``pip install opsrisk-radar[llm]``)
and an API key in ``ANTHROPIC_API_KEY`` (or an ``ant auth login`` profile).
The key is read by the SDK and never logged or stored.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

PROMPT_VERSION = "llm-v1"
DEFAULT_MODEL = "claude-opus-5-5"

# USD per million tokens (input, output), Anthropic first-party list prices as
# published 2026-10-06. Used only for cost estimates; check current pricing.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
CACHE_READ_MULTIPLIER = 0.1

LEVEL_BANDS = {"act": (7.0, 10.0), "watch": (4.0, 6.9), "noise": (0.0, 3.9)}
CATEGORIES = [
    "closure_stoppage", "labor_action", "attack_security", "cyber_outage", "accident",
    "severe_weather", "congestion_delay", "shortage", "trade_measure",
    "insolvency_recall", "conflict", "market_trend", "regulation", "other", "none",
]

SYSTEM_PROMPT = """\
You assess news articles for a supply chain operations team at a mid-size \
manufacturer or shipper importing from Asia and Europe into North America. \
Decide whether the team should see the article in today's risk briefing.

Judge the event the article reports, from the title and summary only, as of \
publication. Labels:

act: a concrete physical, regulatory or commercial event that is currently \
interrupting, or has a stated near-term date to interrupt, the flow of goods, \
transport capacity, production or supply, at a named place, company, route or \
product class. All three must hold: (1) concrete event, not "could/may/warns \
of/risk of"; (2) goods, capacity or production actually stopped, diverted, \
delayed or rationed, or a rule changes what may legally move on a stated \
date (price changes alone are not interruption); (3) specific.

watch: about supply chain or operations risk but fails an act test: nothing \
interrupted yet (proposal, threat, negotiation, forecast), a gradual trend \
(rates, volumes, capacity), or the event has ended (strike settled, port \
reopened).

noise: not an operational risk signal: earnings or results without an \
operational disruption, market-size forecasts, launches, deals, funding, \
hires, awards, events, opinion and how-to pieces, technology adoption.

When torn between two levels, choose the lower one.

Severity (0-10) orders articles within a level: act 7-10, watch 4-6.9, \
noise 0-3.9. Within act, rate higher for chokepoints (Suez, Panama, Hormuz, \
major ports), wider scope, and longer expected duration.

Evidence: quote up to three short phrases copied exactly, character for \
character, from the title or summary that justify the level. Do not \
paraphrase in evidence. Do not state facts that are not in the article.

Rationale: at most 30 words."""

ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": list(LEVEL_BANDS)},
        "severity": {"type": "number"},
        "category": {"type": "string", "enum": CATEGORIES},
        "status": {"type": "string",
                   "enum": ["ongoing", "imminent", "resolved", "speculative", "not_applicable"]},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["level", "severity", "category", "status", "evidence", "rationale"],
    "additionalProperties": False,
}


class LLMError(RuntimeError):
    """The model call or its answer could not be used; fall back to rules."""


class LLMUnavailable(LLMError):
    """No SDK or credentials; nothing was sent."""


class MessagesClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


@dataclass
class Assessment:
    level: str
    severity: float
    category: str
    status: str
    evidence: list[str]
    rationale: str
    flags: list[str] = field(default_factory=list)
    model: str = ""
    prompt_version: str = PROMPT_VERSION
    cached: bool = False

    def as_detail(self) -> dict[str, Any]:
        d = asdict(self)
        d["scorer"] = f"{PROMPT_VERSION}:{self.model}"
        return d


@dataclass
class Usage:
    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0

    def summary(self) -> str:
        return (f"{self.calls} call(s), {self.cache_hits} cache hit(s), "
                f"{self.failures} failure(s), {self.input_tokens} in / "
                f"{self.output_tokens} out tokens, ~${self.cost_usd:.4f}, "
                f"{self.latency_s:.1f}s API time")


def estimate_cost(model: str, input_tokens: int, output_tokens: int,
                  cache_read_tokens: int = 0) -> float:
    price_in, price_out = PRICING.get(model, (0.0, 0.0))
    return (input_tokens * price_in + cache_read_tokens * price_in * CACHE_READ_MULTIPLIER
            + output_tokens * price_out) / 1_000_000


def _norm(s: str) -> str:
    return " ".join(s.replace("’", "'").replace("‘", "'")
                    .replace("“", '"').replace("”", '"').split()).lower()


def validate(raw: dict[str, Any], title: str, summary: str) -> Assessment:
    """Check a parsed answer against the article and the label definitions."""
    try:
        level = str(raw["level"])
        severity = float(raw["severity"])
        category = str(raw["category"])
        status = str(raw["status"])
        evidence = [str(e) for e in raw["evidence"]]
        rationale = str(raw["rationale"])[:400]
    except (KeyError, TypeError, ValueError) as exc:
        raise LLMError(f"malformed assessment: {exc}") from exc
    if level not in LEVEL_BANDS:
        raise LLMError(f"unknown level {level!r}")

    flags: list[str] = []
    text = _norm(f"{title} {summary}")
    supported = [e for e in evidence if e.strip() and _norm(e) in text]
    if len(supported) < len(evidence):
        flags.append(f"dropped {len(evidence) - len(supported)} unsupported quote(s)")
    if level == "act" and not supported:
        level = "watch"
        flags.append("act without verbatim evidence downgraded to watch")

    lo, hi = LEVEL_BANDS[level]
    if not lo <= severity <= hi:
        flags.append(f"severity {severity} moved into {level} band")
        severity = min(max(severity, lo), hi)
    if category not in CATEGORIES:
        category = "other"
    return Assessment(level, round(severity, 2), category, status, supported[:3], rationale,
                      flags)


class LLMCache:
    """Judgments keyed by model, prompt version and article text."""

    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, model TEXT, "
            "prompt_version TEXT, result TEXT, input_tokens INTEGER, output_tokens INTEGER, "
            "cost_usd REAL, latency_s REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.conn.commit()

    @staticmethod
    def key(model: str, title: str, summary: str) -> str:
        return hashlib.sha256(f"{model}\x1f{PROMPT_VERSION}\x1f{title}\x1f{summary}".encode()
                              ).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT result FROM llm_cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, model: str, result: dict[str, Any], input_tokens: int,
            output_tokens: int, cost: float, latency: float) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO llm_cache (key, model, prompt_version, result, "
            "input_tokens, output_tokens, cost_usd, latency_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (key, model, PROMPT_VERSION, json.dumps(result), input_tokens, output_tokens, cost,
             latency),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def credentials_configured() -> bool:
    """Whether the SDK can find credentials (env vars or an ``ant auth login`` profile)."""
    if any(os.environ.get(v) for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                                       "ANTHROPIC_PROFILE")):
        return True
    return (Path.home() / ".config" / "anthropic").is_dir()


def _default_client() -> MessagesClient:
    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailable("install the 'llm' extra: pip install 'opsrisk-radar[llm]'") from exc
    try:
        return anthropic.Anthropic(max_retries=3, timeout=60.0).messages
    except anthropic.AnthropicError as exc:  # no credentials configured
        raise LLMUnavailable(f"Anthropic client unavailable: {type(exc).__name__}") from exc


class LLMScorer:
    def __init__(self, model: str = DEFAULT_MODEL, cache: LLMCache | None = None,
                 client: MessagesClient | None = None, max_calls: int | None = None,
                 effort: str = "low") -> None:
        self.model = model
        self.cache = cache
        self._client = client
        self.max_calls = max_calls
        self.effort = effort
        self.usage = Usage()

    @property
    def client(self) -> MessagesClient:
        if self._client is None:
            self._client = _default_client()
        return self._client

    def assess(self, title: str, summary: str) -> Assessment:
        key = LLMCache.key(self.model, title, summary)
        if self.cache and (hit := self.cache.get(key)):
            self.usage.cache_hits += 1
            result = validate(hit, title, summary)
            result.model, result.cached = self.model, True
            return result
        if self.max_calls is not None and self.usage.calls >= self.max_calls:
            raise LLMError(f"call budget of {self.max_calls} exhausted")

        raw, in_tok, out_tok, cache_tok, latency = self._call(title, summary)
        cost = estimate_cost(self.model, in_tok, out_tok, cache_tok)
        self.usage.input_tokens += in_tok
        self.usage.output_tokens += out_tok
        self.usage.cache_read_tokens += cache_tok
        self.usage.cost_usd += cost
        self.usage.latency_s += latency
        try:
            result = validate(raw, title, summary)
        except LLMError:
            self.usage.failures += 1
            raise
        if self.cache:
            self.cache.put(key, self.model, raw, in_tok, out_tok, cost, latency)
        result.model = self.model
        return result

    def _call(self, title: str, summary: str) -> tuple[dict[str, Any], int, int, int, float]:
        self.usage.calls += 1
        start = time.monotonic()
        try:
            response = self.client.create(
                model=self.model,
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                cache_control={"type": "ephemeral"},
                output_config={"effort": self.effort,
                               "format": {"type": "json_schema", "schema": ASSESSMENT_SCHEMA}},
                messages=[{"role": "user",
                           "content": f"Title: {title}\nSummary: {summary or '(none)'}"}],
            )
        except LLMError:
            raise
        except TypeError as exc:  # raised by the SDK when no credentials resolve
            raise LLMUnavailable("no Anthropic credentials configured") from exc
        except Exception as exc:  # SDK errors after its own retries, network, auth
            self.usage.failures += 1
            log.warning("llm call failed", extra={"error_type": type(exc).__name__})
            raise LLMError(f"API call failed: {type(exc).__name__}") from exc
        latency = time.monotonic() - start

        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        cache_tok = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        if response.stop_reason in ("refusal", "max_tokens"):
            self.usage.failures += 1
            raise LLMError(f"unusable response: stop_reason={response.stop_reason}")
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            self.usage.failures += 1
            raise LLMError("response was not valid JSON") from exc
        return raw, in_tok, out_tok, cache_tok, latency
