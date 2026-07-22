from __future__ import annotations

import importlib
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from .enums import SourceType
from .scoring import DEFAULT_SCORING_CONFIG, merge_scoring_config

# ---------------------------------------------------------------------------
# Pydantic config models
# ---------------------------------------------------------------------------


class SourceConfig(BaseModel):
    """Configuration for a single marketplace source."""

    enabled: bool = True
    url: str = ""
    urls: list[str] = []


class QualityConfig(BaseModel):
    """Crawl-quality thresholds."""

    enabled: bool = True
    min_total: int = Field(default=10, ge=0)
    min_by_source: dict[str, int] = Field(
        default_factory=lambda: {"AutoScout24": 5, "Kleinanzeigen": 10}
    )


class AIEnrichmentConfig(BaseModel):
    """AI enrichment provider settings."""

    enabled: bool = False
    provider: str | None = None
    max_images: int = Field(default=8, ge=0)


class ScoringWeights(BaseModel):
    """Preference weights for scoring listings."""

    manual_transmission: int = 30
    non_convertible: int = 20
    non_ls2: int = 20
    preferred_trim: int = 10


class ScoringRiskPenalties(BaseModel):
    """Penalty values for risk flags."""

    accident_reported: int = 18
    damage_reported: int = 14
    salvage_import_possible: int = 10
    mileage_unclear: int = 8
    no_tuv: int = 8
    modified_heavily: int = 4
    sold_or_reserved: int = 20


class ScoringConfig(BaseModel):
    """Scoring configuration with weights and penalties."""

    base_score: int = Field(default=20, ge=0, le=100)
    weights: ScoringWeights = ScoringWeights()
    preferred_trims: list[str] = Field(default_factory=lambda: ["Grand Sport", "Z06", "ZR1"])
    risk_penalties: ScoringRiskPenalties = ScoringRiskPenalties()


class AppConfig(BaseModel):
    """Top-level validated application configuration.

    Allows both attribute access (config.output_dir) and dict-like access
    (config["output_dir"]) for backward compatibility with existing code.
    """

    sources: dict[str, SourceConfig] = Field(default_factory=dict)
    output_dir: str = "."
    database_path: str = "data/corvette_tracker.sqlite"
    ai_enrichment: AIEnrichmentConfig = AIEnrichmentConfig()
    quality: QualityConfig = QualityConfig()
    scoring: ScoringConfig = ScoringConfig()

    # --- dict-like access for backward compat ---

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        """Recursively serialize to plain dicts (same as model_dump)."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# Builder: convert validated AppConfig → flat dict for backward compat
# ---------------------------------------------------------------------------


def _app_config_to_flat_dict(cfg: AppConfig) -> dict[str, Any]:
    """Serialize AppConfig to the same dict shape existing code expects.

    ``model_dump()`` on the nested models already produces the right
    structure (scoring.weights → dict, sources → dict of dicts, etc.),
    so this is effectively just ``cfg.model_dump()``.
    """
    return cfg.model_dump()


# ---------------------------------------------------------------------------
# Default config (plain dict, keeps backward-compat with existing tests)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "sources": {},
    "output_dir": ".",
    "database_path": "data/corvette_tracker.sqlite",
    "ai_enrichment": {"enabled": False, "provider": None, "max_images": 8},
    "quality": {
        "enabled": True,
        "min_total": 10,
        "min_by_source": {"AutoScout24": 5, "Kleinanzeigen": 10},
    },
    "scoring": DEFAULT_SCORING_CONFIG,
}

# Inject known source defaults so they're always present after merge.
_default_source_urls: dict[str, tuple[str, list[str]]] = {}  # filled below via lazy import


def _fill_source_defaults() -> None:
    if _default_source_urls:
        return
    # Late imports to avoid circular dependency at module level.
    from .sources.autouncle import DEFAULT_URL as AUTOUNCLE_URL
    from .sources.autoscout24 import DEFAULT_URL as AS24_URL
    from .sources.classic_trader import DEFAULT_URL as CLASSIC_TRADER_URL
    from .sources.kleinanzeigen import DEFAULT_URL as KA_URL
    from .sources.mobile_de import DEFAULT_URL as MOBILE_URL

    _default_source_urls["autoscout24"] = (AS24_URL, [AS24_URL])
    _default_source_urls["kleinanzeigen"] = (KA_URL, [KA_URL])
    _default_source_urls["autouncle"] = (
        AUTOUNCLE_URL,
        [AUTOUNCLE_URL, "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette?freetext=C6"],
    )
    _default_source_urls["classic_trader"] = (
        CLASSIC_TRADER_URL,
        [
            CLASSIC_TRADER_URL,
            "https://www.classic-trader.com/de/automobile/suche/chevrolet/corvette/c6",
        ],
    )
    _default_source_urls["mobile_de"] = (MOBILE_URL, [])

    for key, (url, urls) in _default_source_urls.items():
        DEFAULT_CONFIG["sources"][key] = {
            "enabled": True,
            "url": url,
            "urls": [url, *urls],
        }

_fill_source_defaults()


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_config(path: str | None) -> dict[str, Any]:
    """Load and validate config from a YAML file.

    Returns a plain dict (backward-compatible) whose values have been
    validated against the Pydantic ``AppConfig`` model. On invalid input
    a ``ValidationError`` is raised with detailed error messages listing
    allowed values/paths.
    """
    if not path:
        validated = AppConfig(**_build_default_dict())
        return _app_config_to_flat_dict(validated)

    with Path(path).open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    merged = _merge_loaded_into_defaults(loaded)
    validated = AppConfig(**merged)
    return _app_config_to_flat_dict(validated)


def _build_default_dict() -> dict[str, Any]:
    """Build a dict matching AppConfig fields from DEFAULT_CONFIG."""
    return {
        "sources": {
            name: SourceConfig(**cfg)
            for name, cfg in DEFAULT_CONFIG.get("sources", {}).items()
        },
        "output_dir": DEFAULT_CONFIG["output_dir"],
        "database_path": DEFAULT_CONFIG["database_path"],
        "ai_enrichment": AIEnrichmentConfig(**DEFAULT_CONFIG["ai_enrichment"]),
        "quality": QualityConfig(**DEFAULT_CONFIG["quality"]),
        "scoring": ScoringConfig(**DEFAULT_CONFIG["scoring"]),
    }


def _merge_loaded_into_defaults(loaded: dict[str, Any]) -> dict[str, Any]:
    """Merge a loaded YAML dict into DEFAULT_CONFIG (same logic as original)."""
    merged: dict[str, Any] = dict(DEFAULT_CONFIG)
    merged.update(
        (k, v)
        for k, v in loaded.items()
        if k not in {"sources", "ai_enrichment", "quality", "scoring"}
    )
    merged["sources"] = DEFAULT_CONFIG["sources"] | loaded.get("sources", {})
    merged["ai_enrichment"] = DEFAULT_CONFIG["ai_enrichment"] | loaded.get("ai_enrichment", {})
    merged["quality"] = DEFAULT_CONFIG["quality"] | loaded.get("quality", {})
    merged["scoring"] = merge_scoring_config(loaded.get("scoring"))
    return merged


# ---------------------------------------------------------------------------
# Crawl quality validation
# ---------------------------------------------------------------------------


def validate_crawl_quality(
    payload: dict[str, Any], *, min_total: int, min_by_source: dict[str, int]
) -> list[str]:
    """Check that a crawl payload meets minimum listing counts."""
    listings = payload.get("listings") or []
    source_counts = Counter(str(item.get("source") or "unknown") for item in listings)
    warnings: list[str] = []
    if len(listings) < min_total:
        warnings.append(
            f"Crawler quality: only {len(listings)} total listings parsed; expected at least {min_total}"
        )
    for source, expected in min_by_source.items():
        actual = source_counts.get(source, 0)
        if actual < expected:
            warnings.append(
                f"Crawler quality: only {actual} {source} listings parsed; expected at least {expected}"
            )
    return warnings


# ---------------------------------------------------------------------------
# AI provider loader
# ---------------------------------------------------------------------------


def load_ai_provider(dotted_path: str) -> Any:
    """Dynamically import an AI enrichment provider by 'module:ClassName'."""
    if ":" not in dotted_path:
        raise ValueError("AI provider must use 'module:ClassName' format")
    module_name, class_name = dotted_path.split(":", 1)
    module = importlib.import_module(module_name)
    provider_class = getattr(module, class_name)
    return provider_class()
