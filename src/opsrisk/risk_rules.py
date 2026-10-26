"""Rule-based scorer v2: classify the reported event, then assign severity.

v1 averaged keyword counts over five dimensions, so an article that was pure
disruption (no dollar figures, no regulation words) could not exceed
0.45 × 10 + 0.55 = 5.05 and never reached HIGH. v2 follows the labeling guide
(``docs/labeling_guide.md``) instead:

1. **Event** — does the text report an interrupting event (closure, strike,
   attack, accident, outage, severe weather, dated trade measure, ...)?
2. **Status** — is it ongoing, or resolved / speculative / postponed?
3. **Article type** — is it earnings, a deal, a launch, an appointment or an
   opinion piece (noise), whatever words it contains?

The class sets the severity band and small, explained boosts order articles
within it:

    act-level event, ongoing ............ 7.0 - 9.5  HIGH / CRITICAL
    event resolved / speculative, trend . 4.0 - 6.9  MEDIUM
    supply chain topic, no event ........ 2.0 - 3.9  LOW
    noise ............................... 1.0 - 1.9  LOW

Every score comes with the matched evidence and a one-line reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from opsrisk.signals import CATEGORY_LABELS, is_market_report

# Version of the rule set stored with every score; bump it on any rule change
# so stored scores are recomputed. "rules-v2" in config selects this module.
SCORER_ID = "rules-v2.1"

_FACILITY = (
    r"(ports?|harbou?rs?|terminals?|plants?|factor(?:y|ies)|mills?|airports?|borders?|"
    r"canals?|straits?|routes?|rail\s*lines?|railways?|warehouses?|highways?|bridges?|"
    r"facilit(?:y|ies)|mines?|refiner(?:y|ies)|operations|production|output|lines?|"
    r"services?|sailings?|shipments?|exports?|imports?|traffic)"
)
_STOP_VERB = r"(clos\w*|shut\w*|halt\w*|suspend\w*|idl(?:e|es|ed|ing)|stop(?:s|ped|ping)?|block\w*)"
_NEAR = r"(?:\W+\w+){0,4}?\W+"

# Interrupting events, by category. Matched against title and summary.
EVENT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    name: [re.compile(p, re.IGNORECASE) for p in pats]
    for name, pats in {
        "closure_stoppage": [
            rf"\b{_STOP_VERB}{_NEAR}{_FACILITY}\b",
            rf"\b{_FACILITY}{_NEAR}{_STOP_VERB}\b",
            r"\b(shutdown|work\s+stoppage|production\s+halt|force\s+majeure)\b",
            r"\bprohibit\w*\b.{0,40}\b(depart|sail|enter|call)\w*",
        ],
        "labor_action": [
            r"\bstrik(e|es|ing)\b(?!\s+(a\s+)?(new\s+)?(deal|agreement|balance|pact|partnership|tone))",
            r"\b(walkout|walk-out|lockout|picket\w*)\b",
        ],
        "attack_security": [
            r"\b(vessel|ship|tanker|cargo)\s+attacks?\b",
            r"\battacks?\s+(on|in|against)\b",
            r"\b(hijack\w*|seized|seizure|piracy|missile|drone\s+strikes?)\b",
            r"\b(damaged|struck)\b.{0,30}\b(tankers?|vessels?|ships?)\b",
            r"\b(tankers?|vessels?|ships?)\b.{0,30}\b(damaged|struck|attacked)\b",
        ],
        "cyber_outage": [
            r"\b(cyber-?attacks?|ransomware|hack(ed|ers)?|data\s+breach)\b",
            r"\boutages?\b",
        ],
        "accident": [
            r"\b(collision|collided|explosion|derail\w*|capsiz\w*|sank|sinking|grounded|"
            r"grounding|spill)\b",
            r"\b(fire|blaze)\b(?!\s+(sale|up))",
        ],
        "severe_weather": [
            r"\b(typhoons?|hurricanes?|cyclones?|earthquakes?|tsunami|flood(s|ing|ed)?|"
            r"wildfires?|blizzards?|(winter\s+|tropical\s+)?storms?)\b",
        ],
        "congestion_delay": [
            r"\b(congestion|congested|backlogs?|bottlenecks?|gridlock)\b",
            r"\b(berthing|port|shipping|cargo|vessel)\s+delays?\b",
            r"\b(rerout\w*|divert\w*|diversions?)\b",
        ],
        "shortage": [r"\bshortages?\b", r"\b(rationing|rationed|allocation\s+cuts?)\b"],
        "trade_measure": [
            r"\b(tariffs?|embargo\w*|sanctions?|export\s+controls?|import\s+bans?|bans?\s+on)\b",
        ],
        "insolvency_recall": [
            r"\b(bankrupt\w*|insolven\w*|receivership|liquidation|recall(s|ed)?)\b",
        ],
        "conflict": [r"\b(war|military\s+strikes?|armed\s+conflict|blockade)\b"],
        "disruption": [r"\bdisrupt(s|ed|ing|ion|ions)?\b"],
    }.items()
}

# Categories that on their own are context rather than an interruption.
_CONTEXT_ONLY = {"conflict", "disruption", "trade_measure", "severe_weather", "shortage"}

# A trade measure becomes an interruption when it has a date.
_EFFECTIVE_DATE = re.compile(
    r"\b(effective|takes?\s+effect|starting|from|as\s+of|beginning)\s+"
    r"(on\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+\d{1,2}\b",
    re.IGNORECASE,
)
# Severe weather becomes an interruption when it is acting on something.
_WEATHER_IMPACT = re.compile(
    rf"\b({_STOP_VERB}|disrupt\w*|damag\w*|strand\w*|batter\w*|hit|hits|landfall)\b",
    re.IGNORECASE,
)

RESOLVED = re.compile(
    r"\b(ends?|ended|reopen\w*|resum\w*|restor\w*|lift(s|ed)?|averted|called\s+off|"
    r"settle(d|s|ment)?|(tentative|new)\s+(\w+\s+)?(deal|pact|agreement|contract)|"
    r"reach(es|ed)?\s+(a\s+)?(tentative\s+)?(\w+\s+)?(deal|pact|agreement)|"
    r"return(s|ing)?\s+to|eas(e|es|ed|ing))\b",
    re.IGNORECASE,
)
SPECULATIVE = re.compile(
    r"\b(could|may|might|warns?|risks?|threat\w*|fears?|outlook|forecast\w*|"
    r"expected\s+to|plans?\s+to|propos\w+|consider\w*|weighs?|vote|talks|"
    r"negotiat\w*|on\s+hold|urg(e|es|ed)|seen\s+as|delays?\s+(\w+\s+){0,3}(fees?|"
    r"implementation|rules?|tariffs?)|suspension|extend\w*)\b",
    re.IGNORECASE,
)

# Article types that are not risk signals regardless of vocabulary (title only).
NOISE_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(p, re.IGNORECASE)
    for name, p in {
        "earnings": r"\b(earnings|q[1-4]\s+(results|profit|revenue)|quarterly\s+results|"
        r"profits?|revenues?|(raises?|cuts?)\s+(\d{4}\s+)?(outlook|guidance)|"
        r"(nine|six|three)-month|operating\s+performance|reports?\s+(solid|strong|"
        r"stronger|record|higher))\b",
        "deal": r"\b(acqui\w+|merger|partnership|collaborat\w+|invest(s|ing|ment)?|"
        r"funding|orders?\s+\d+|to\s+buy|agrees?\s+to\s+buy|to\s+sell|sells?|"
        r"strikes?\s+(a\s+)?deal|stake)\b",
        "people_events": r"\b(names?|appoints?|hires?|award|finalists|webinar|summit|"
        r"conference|keynote|veteran)\b",
        "opinion_howto": r"(^how\b|\bhow\s+to\b|^why\b|^what\b|\bstrategies\b|\btips\b|"
        r"^\d+\s+(ways|steps|things|reasons|lessons|questions)\b|"
        r"\blessons\b|\bpromises\s+vs|\bthe\s+next\b|\bguide\b|^analysis:)",
        "technology": r"\b(ai|agentic|automation|robot\w*|digital|software|platform|"
        r"integrat\w+|control\s+towers?|hydrogen|autonomous)\b",
        "expansion": r"\b(opens?|new\s+office|expands?|expansion|adds?\s+\d+|"
        r"launch\w*|boost\w*\s+\w*\s*fleet|deepens)\b",
    }.items()
}

# Words that make an article about supply chain risk even without an event.
RISK_TOPIC = re.compile(
    r"\b(freight\s+rates?|spot\s+rates?|rates?\s+(rise|climb|surge|jump|hike|increase)|"
    r"capacity|surcharges?|regulat\w+|inspections?|enforcement|customs|cbp|"
    r"labor|labour|union|contract\s+talks|pressure\w*|index|tight\w*|constraints?|"
    r"port\s+fees?|tariffs?|sanctions?|geopolit\w+|executive\s+order|security)\b",
    re.IGNORECASE,
)
SUPPLY_CHAIN = re.compile(
    r"\b(ports?|freight|cargo|shipp\w+|containers?|carriers?|vessels?|supply\s+chains?|"
    r"logistics|truck\w*|rail\w*|air\s*freight|warehous\w+|inventory|suppliers?|"
    r"manufactur\w+|plants?|imports?|exports?|trade|ltl|parcel)\b",
    re.IGNORECASE,
)

# Chokepoints and hubs where an interruption has outsized network effects.
CRITICAL_NODES = re.compile(
    r"\b(suez|panama\s+canal|hormuz|red\s+sea|bab\s+el-?mandeb|malacca|bosporus|"
    r"shanghai|ningbo|shenzhen|singapore|busan|kaohsiung|rotterdam|antwerp|hamburg|"
    r"los\s+angeles|long\s+beach|new\s+york|savannah|houston|taiwan|strait)\b",
    re.IGNORECASE,
)


@dataclass
class RiskAssessment:
    score: float
    level: str  # act | watch | relevant | noise
    categories: list[str] = field(default_factory=list)
    status: str = "none"  # ongoing | resolved | speculative | none
    noise_type: str | None = None
    evidence: list[str] = field(default_factory=list)
    reason: str = ""

    def as_detail(self) -> dict:
        return {
            "scorer": SCORER_ID,
            "level": self.level,
            "categories": self.categories,
            "status": self.status,
            "noise_type": self.noise_type,
            "evidence": self.evidence,
            "reason": self.reason,
        }


def _names(categories) -> str:
    return ", ".join(CATEGORY_LABELS.get(c, c).lower() for c in sorted(categories))


def _events(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for category, patterns in EVENT_PATTERNS.items():
        for p in patterns:
            if m := p.search(text):
                found.setdefault(category, []).append(m.group(0))
                break
    return found


def _is_interruption(cats: dict[str, list[str]], text: str) -> bool:
    """True if the matched categories describe goods or capacity actually stopping."""
    hard = set(cats) - _CONTEXT_ONLY
    if hard:
        return True
    if "trade_measure" in cats and _EFFECTIVE_DATE.search(text):
        return True
    if "severe_weather" in cats and _WEATHER_IMPACT.search(text):
        return True
    # Context categories combined (e.g. "war disrupts supply", "shortage disrupts output").
    return "disruption" in cats and bool(cats.keys() & {"conflict", "shortage", "severe_weather"})


def assess(title: str, summary: str) -> RiskAssessment:
    text = f"{title}. {summary}"
    title_events = _events(title)
    all_events = _events(text)
    noise_type = next((n for n, p in NOISE_PATTERNS.items() if p.search(title)), None)
    if noise_type is None and is_market_report(title):
        noise_type = "market_forecast"

    resolved = bool(RESOLVED.search(title))
    speculative = bool(SPECULATIVE.search(title))
    evidence = [s for v in all_events.values() for s in v][:6]

    title_interrupt = bool(title_events) and _is_interruption(title_events, text)
    any_interrupt = bool(all_events) and _is_interruption(all_events, text)
    critical = bool(CRITICAL_NODES.search(text))
    if critical and (m := CRITICAL_NODES.search(text)):
        evidence.append(m.group(0))

    def done(score: float, level: str, status: str, reason: str) -> RiskAssessment:
        # A small evidence count breaks ties inside a band without crossing it.
        score = round(min(score, 9.5) + 0.01 * min(len(evidence), 9), 2)
        return RiskAssessment(score, level, sorted(all_events), status, noise_type,
                              evidence, reason)

    if title_interrupt and not (resolved or speculative):
        if noise_type in {"deal", "earnings"}:
            # e.g. "X agrees to buy LNG as war disrupts supply": the news is the deal.
            return done(5.5, "watch", "ongoing",
                        f"{noise_type} story citing an ongoing interruption")
        n_hard = len(set(title_events) - _CONTEXT_ONLY)
        score = 7.0 + 0.5 * min(max(n_hard - 1, 0), 2)
        score += 0.5 if critical else 0.0
        score += 0.25 if len(all_events) > len(title_events) else 0.0
        return done(score, "act", "ongoing",
                    f"ongoing interruption: {_names(title_events)}")

    if title_events and (resolved or speculative):
        status = "resolved" if resolved else "speculative"
        return done(5.0 + (0.5 if critical else 0.0), "watch", status,
                    f"{status}: {_names(title_events)}")

    if resolved and noise_type is None and re.search(rf"\b{_FACILITY}\b", title, re.I):
        return done(4.5, "watch", "resolved", "recovery from an earlier interruption")

    if any_interrupt and noise_type is None:
        return done(5.5 + (0.5 if critical else 0.0), "watch", "ongoing",
                    "interruption reported in the summary, not the headline")

    if (title_events or RISK_TOPIC.search(title)) and noise_type is None:
        return done(4.0, "watch", "speculative" if speculative else "none",
                    "supply chain risk topic without a concrete interruption")

    if noise_type is None and SUPPLY_CHAIN.search(text):
        bump = 1.0 if RISK_TOPIC.search(summary) or all_events else 0.0
        return done(2.0 + bump, "relevant", "none", "supply chain news, no risk event")

    return done(1.0, "noise", "none",
                f"not a risk signal ({noise_type or 'off-topic'})")
