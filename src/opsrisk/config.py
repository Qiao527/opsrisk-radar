from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FeedSource:
    name: str
    url: str
    category: str
    enabled: bool = True


@dataclass
class ScoringConfig:
    # Scorer used by the pipeline: "rules-v1", "rules-v2" or "hybrid-v1".
    scorer: str = "rules-v2"
    composite_weights: dict[str, float] = field(
        default_factory=lambda: {
            "disruption_risk": 0.30,
            "business_impact": 0.25,
            "strategic_relevance": 0.20,
            "actionability": 0.15,
            "signal_strength": 0.10,
        }
    )


@dataclass
class LLMConfig:
    model: str = "claude-opus-5-5"
    max_calls_per_run: int = 200


@dataclass
class AppConfig:
    feeds: list[FeedSource] = field(default_factory=list)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    data_dir: Path = Path("data")
    briefs_dir: Path = Path("briefs")


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        path = Path("config/sources.toml")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    config = AppConfig()

    if "scoring" in raw:
        config.scoring = ScoringConfig(
            scorer=raw["scoring"].get("scorer", config.scoring.scorer),
            composite_weights=raw["scoring"].get(
                "composite_weights", config.scoring.composite_weights
            ),
        )
    if "llm" in raw:
        config.llm = LLMConfig(
            model=raw["llm"].get("model", config.llm.model),
            max_calls_per_run=int(raw["llm"].get("max_calls_per_run",
                                                 config.llm.max_calls_per_run)),
        )

    for entry in raw.get("feeds", []):
        config.feeds.append(
            FeedSource(
                name=entry["name"],
                url=entry["url"],
                category=entry["category"],
                enabled=entry.get("enabled", True),
            )
        )

    return config
