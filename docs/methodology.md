# Scoring methodology

Three scorers are implemented and compared under one evaluation protocol
([evaluation.md](evaluation.md)). The pipeline default is **rules-v2.1**.

| Scorer | What it is | Status |
|--------|-----------|--------|
| `rules-v1` | Weighted average of five keyword dimensions | Legacy; kept for comparison and as supporting signals |
| `rules-v2.1` | Event / status / article-type classification | **Default.** Evaluated on provisional labels |
| `llm-v1` | Claude assessment against the labeling guide, validated | Implemented and mock-tested; **not yet run live** |
| `hybrid-v1` | rules-v2.1 triage, LLM review of non-noise articles | Implemented and mock-tested; **not yet run live** |

## Why rules-v1 was replaced

rules-v1 scores five dimensions (disruption 45%, business impact 25%,
actionability 15%, signal strength 10%, strategic relevance 5%), each clamped
to [1, 10], and averages them. An article that is purely about a disruption,
with no dollar figures or regulatory vocabulary, scores at most
0.45 × 10 + 0.55 × 1 = **5.05**, so it can never reach HIGH (≥ 7). On 150 live
articles (2026-10-26) every article was LOW, the maximum was 3.3, "Typhoon
Champi closes Taiwan ports" scored 3.25, and "Australian asset manager
*strikes* deal for UK's largest port operator" outscored most disruptions
because "strike" matched. Lowering thresholds would not fix the ordering; the
model was measuring keyword density, not events.

## rules-v2.1

Implemented in `src/opsrisk/risk_rules.py`, derived from the operational
definitions in [labeling_guide.md](labeling_guide.md):

1. **Event detection.** Pattern groups for closures and stoppages (a stop verb
   near a facility noun: port, plant, terminal, route, production...), labor
   action (excluding "strikes a deal"), attacks on vessels, cyber incidents and
   outages, accidents, severe weather, congestion and diversions, shortages,
   trade measures, insolvency and recalls, conflict, and generic disruption.
   Context-only categories (conflict, trade measure, weather, shortage,
   "disruption") count as an interruption only with support: a trade measure
   needs an effective date, weather needs an impact verb, generic disruption
   needs another category.
2. **Status.** Resolution language (ends, reopens, resumes, tentative deal,
   returns to, eases) and speculative language (could, warns, proposed, talks,
   delays fees, outlook) in the headline demote an event to watch level.
3. **Article type.** Earnings, deals, appointments and events, opinion and
   how-to pieces, technology adoption, expansions and market forecasts are
   noise unless the headline itself reports an interruption.

| Class | Score | Severity |
|-------|-------|----------|
| Ongoing interruption in the headline | 7.0 + up to 1.0 for multiple event types + 0.5 at a chokepoint/major port + 0.25 if the summary adds an event | HIGH (CRITICAL is effectively unreachable by design) |
| Deal or earnings story citing an ongoing interruption | 5.5 | MEDIUM |
| Interruption only in the summary | 5.5 (+0.5 chokepoint) | MEDIUM |
| Resolved or speculative event | 5.0 (+0.5 chokepoint) | MEDIUM |
| Recovery (reopens, resumes) | 4.5 | MEDIUM |
| Risk topic without an event (rates, capacity, regulation) | 4.0 | MEDIUM |
| Supply chain news, no risk event | 2.0 – 3.0 | LOW |
| Noise | 1.0 | LOW |

A tie-breaker of 0.01 per evidence phrase (at most 0.09) orders articles inside
a class without crossing a band. Every score stores its categories, status,
matched evidence and a one-line reason, which the dashboard shows.

The rule-set id is stored with each score (`rules-v2.1`); changing any rule
requires bumping it, which rescores the database on the next run.

### Known failure modes (observed)

- **Strategic closures read as disruptions.** "PepsiCo shutters Tennessee
  bottling plant amid soda slump" is a cost-cutting decision, not a supply
  interruption, but scores HIGH.
- **Analysis pieces driven by an event.** A capacity analysis whose headline
  mentions congestion scores HIGH.
- **Interruptions described only in the summary** stay at MEDIUM (for example
  an AWS outage in the UAE inside a geopolitics explainer).
- **Category confusion.** "containership damaged after cruise ship collision"
  also triggers the attack/security pattern ("vessel ... damaged").
- English-only patterns; no understanding of scale beyond a short chokepoint
  list.

These are exactly the cases where contextual judgment helps, which motivates
the hybrid.

## llm-v1

`src/opsrisk/llm_scorer.py`. Uses the official `anthropic` SDK (optional
`llm` extra).

- **Prompt.** The labeling guide's three *act* tests, watch and noise
  definitions, "choose the lower level when torn", severity bands, and an
  instruction to quote evidence verbatim. Prompt version `llm-v1` is part of
  the cache key and stored with every result.
- **Structured output.** `output_config.format` with a JSON schema (level,
  severity, category, status, evidence, rationale). Forced `tool_choice` is
  rejected by current Claude models, so it is not used.
- **Validation.** Evidence quotes must appear verbatim in the title or summary
  (after quote and whitespace normalization); unsupported quotes are dropped,
  and an "act" answer with no surviving evidence is downgraded to watch.
  Severity is moved into the band of the stated level. Refusals, truncation
  (`max_tokens`) and invalid JSON raise, and the caller falls back to rules.
- **Model.** Default `claude-opus-5-5` at `effort: low`, configurable in
  `config/sources.toml` (`[llm] model`). The cheaper `claude-haiku-5-5` is
  supported by the cost table and is the obvious candidate to evaluate.
- **Caching and budget.** Results are cached in SQLite by (model, prompt
  version, title, summary). A per-run call budget (default 200) caps spend.
- **Credentials.** Read by the SDK from `ANTHROPIC_API_KEY` (or an
  `ant auth login` profile). The code never logs or stores the key.

## hybrid-v1

`src/opsrisk/hybrid.py`. rules-v2.1 scores every article. Articles the rules
place at watch or act level, or that match any event pattern, go to the LLM;
the LLM's validated severity replaces the rule score. Clear noise is never
sent. Any LLM failure keeps the rule score and records the fallback.

On the 157 live articles of 2026-10-26, the hybrid would send **46 (29%)** to
the LLM (measured by running the routing rule; no API calls).

## Cost and latency

| | rules-v2.1 | llm-v1 (all articles) | hybrid-v1 |
|---|---|---|---|
| Scoring time, 58 test articles | 0.02 s (measured) | not measured | not measured |
| Articles sent to the API per day (157/day) | 0 | 157 | 46 (measured routing) |
| Estimated cost per day, `claude-opus-5-5` | $0 | ≈ $0.75 – 2.30 | ≈ $0.22 – 0.67 |
| Estimated cost per day, `claude-haiku-5-5` | $0 | ≈ $0.02 – 0.06 | ≈ $0.006 – 0.017 |

**The cost rows are estimates, not measurements.** Assumptions: ~600 input
tokens per call (the system prompt is ~1,800 characters, an article ~430
characters, at ~4 characters per token) and 120 – 600 output tokens (the JSON
answer plus an unknown amount of thinking at low effort), at list prices of
2026-10-06 (Opus 5.5: $4 / $20 per million input/output tokens; Haiku 5.5:
$0.10 / $0.50). Prompt caching of the system prompt would reduce input cost
further if the prefix is long enough to be cached. The scorer records real
token counts and cost once it runs with a key; `opsrisk evaluate` prints them.

## Choosing the default

rules-v2.1 is the default because it is free, instant, deterministic,
explainable, and on the evidence available so far (provisional labels) far
better than v1. The hybrid should become the default only if, on **human**
labels, it beats rules-v2.1 on the test split by more than the bootstrap
interval width, at an acceptable measured cost. Until then it remains an
opt-in (`[scoring] scorer = "hybrid-v1"`).
