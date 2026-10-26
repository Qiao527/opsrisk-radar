# Labeling guide

This guide defines the labels used to evaluate OpsRisk Radar's ranking. It is
written so two people labeling the same article independently reach the same
answer. When the guide and your intuition disagree, follow the guide and write
the disagreement in `note`; the guide is then revised, not the label.

## The question being answered

> *Should a supply chain operations team at a mid-size manufacturer or shipper
> that imports from Asia and Europe into North America see this article in
> today's risk briefing?*

The label is about the **event the article reports**, judged from the title
and summary only, as of the article's publication date.

## Labels

| Label | Name | Operational definition |
|------:|------|------------------------|
| **2** | **act** | The article reports a **concrete physical, regulatory or commercial event** that is **currently interrupting or has a stated near-term date to interrupt** the flow of goods, transport capacity, production or supply, at a **named place, company, route or product class**. |
| **1** | **watch** | The article is **about supply chain or operations risk** but fails at least one of the three *act* tests: nothing is interrupted yet (proposal, threat, negotiation, forecast of tightening), the effect is a gradual trend (rates, volumes, capacity), or the event has ended (strike settled, port reopened). |
| **0** | **noise** | Not an operational risk signal: company earnings and financial results without an operational disruption, market-size forecasts, product or service launches, funding/M&A/partnerships, hires and appointments, awards, events and webinars, opinion and how-to pieces, technology adoption stories. |

### The three *act* tests

All three must hold for label 2:

1. **Concrete event** — something happened or is scheduled: a closure, strike,
   stoppage, attack, accident, outage, recall, shortage that halts output, a
   tariff/ban/sanction with an effective date, a bankruptcy that stops supply.
   *Not:* "could", "may", "warns of", "risk of", "pressure builds", surveys.
2. **Interruption** — goods, capacity or production are actually stopped,
   diverted, delayed or rationed, or a rule changes what may legally move on a
   stated date. Price changes alone are not interruption.
3. **Specific** — a named port, route, carrier, plant, company, country pair
   or product class. "Global supply chains face headwinds" is not specific.

### Decision procedure

1. Is the article about the physical or regulatory flow of goods, transport,
   production or supply? **No → 0.**
2. Is the article primarily earnings, a forecast of market size, a launch,
   a deal, a hire, an event or an opinion piece? **Yes → 0**, unless the
   summary reports an operational disruption as the news (e.g. "profit falls
   after plant fire halts output" → judge the fire).
3. Do all three *act* tests hold? **Yes → 2.** **No → 1.**

### Edge cases

| Situation | Label | Why |
|-----------|------:|-----|
| Strike or lockout under way | 2 | concrete, interrupting, specific |
| Strike vote, strike threat, contract talks | 1 | not interrupting yet |
| Labor deal reached, strike ends, port reopens | 1 | the risk has ended; still useful context |
| Tariff announced with an effective date ≤ 90 days | 2 | regulatory interruption with a date |
| Tariff proposed, under review, or court challenge | 1 | not in effect |
| Freight rates rise, capacity tightens | 1 | gradual trend, not an interruption |
| Vessel attacks / rerouting on a named route | 2 | goods are being diverted now |
| Weather event closing ports or plants | 2 | |
| Weather forecast, hurricane season outlook | 1 | |
| Cyberattack disrupting a carrier, port or manufacturer | 2 | |
| Supplier bankruptcy that stops deliveries | 2 | |
| Bankruptcy or layoffs with no stated supply effect | 1 | |
| Index or survey showing supply chain pressure | 1 | aggregate trend |
| Company invests in a new DC, automation, AI | 0 | |
| Plant closure announced as a strategic decision months out | 1 | not interrupting now |

When torn between two labels, choose the **lower** one and say why in `note`.

## Procedure and provenance

- Label **blind**: `eval/labels.csv` contains no scores or machine suggestions,
  so the scorer cannot anchor the label. Do not open
  `eval/suggestions.csv` until your pass over a batch is complete.
- Fill `label` (0/1/2), `labeler` (your initials or handle) and `labeled_at`
  (YYYY-MM-DD). Rows without `labeler` are rejected by the evaluator.
- Use the `url` only when the title and summary are genuinely ambiguous; the
  scorers only see title and summary, so labels should too.
- A second labeler should independently label at least 30 rows into a copy
  (`eval/labels_b.csv`); `opsrisk eval agreement` reports Cohen's κ. Rows
  where labelers disagree are discussed and the guide amended.

## Machine suggestions are not labels

`eval/suggestions.csv` holds labels proposed by a model, each with the model
id, date, rationale and quoted evidence. They exist to (a) let the evaluation
pipeline run end to end before human labels exist and (b) be compared with
human labels afterwards. The evaluator refuses to mix the two sources and
prints a warning on every report computed from suggestions. **No number
computed from suggestions is evidence of accuracy.**
