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
class AppConfig:
    feeds: list[FeedSource] = field(default_factory=list)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
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
            composite_weights=raw["scoring"].get(
                "composite_weights", config.scoring.composite_weights
            )
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
