from __future__ import annotations

import importlib
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self

from .enums import SourceType
from .scoring import DEFAULT_SCORING_CONFIG, merge_scoring_config

# ---------------------------------------------------------------------------
# Pydantic config models
# ---------------------------------------------------------------------------


class SourceConfig(BaseModel):
    """Per-source configuration block."""

    enabled: bool = True
    url: str = ""
    urls: list[str] = Field(default_factory=list)

    # Allow the YAML to carry extra keys (like comments) without failing
    model_config = {"extra": "ignore"}


class AIEnrichmentConfig(BaseModel):
    """Configuration for the optional AI enrichment pipeline."""

    enabled: bool = False
    provider: str | None = None
    max_images: int = 8

    model_config = {"extra": "ignore"}

    @field_validator("max_images")
    @classmethod
    def _max_images_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_images must be >= 1")
        return v


class QualityConfig(BaseModel):
    """Crawl-quality thresholds that warn on suspiciously low counts."""

    enabled: bool = True
    min_total: int = 10
    min_by_source: dict[str, int] = Field(
        default_factory=lambda: {"AutoScout24": 5, "Kleinanzeigen": 10}
    )

    model_config = {"extra": "ignore"}

    @field_validator("min_total")
    @classmethod
    def _min_total_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_total must be >= 1")
        return v


class ScoringWeights(BaseModel):
    """User-preference weights for listing scoring."""

    manual_transmission: int = 30
    non_convertible: int = 20
    non_ls2: int = 20
    preferred_trim: int = 10

    model_config = {"extra": "ignore"}


class RiskPenalties(BaseModel):
    """Penalty values applied per risk flag."""

    accident_reported: int = 18
    damage_reported: int = 14
    salvage_import_possible: int = 10
    mileage_unclear: int = 8
    no_tuv: int = 8
    modified_heavily: int = 4
    sold_or_reserved: int = 20

    model_config = {"extra": "ignore"}


class ScoringConfig(BaseModel):
    """Complete scoring configuration block."""

    base_score: int = 20
    total_budget: int = 80
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    preferred_trims: list[str] = Field(
        default_factory=lambda: ["Grand Sport", "Z06", "ZR1"]
    )
    budget: dict[str, int] = Field(default_factory=lambda: {
        "engine": 15, "transmission": 10, "trim": 8,
        "body": 6, "mileage": 6, "completeness": 3, "eu_spec": 2,
    })
    risk_penalties: RiskPenalties = Field(default_factory=RiskPenalties)

    model_config = {"extra": "ignore"}

    @field_validator("base_score")
    @classmethod
    def _base_score_range(cls, v: int) -> int:
        if v < 0:
            raise ValueError("base_score must be >= 0")
        return v

    def to_flat_dict(self) -> dict[str, Any]:
        """Return the legacy flat dict format expected by scoring.py."""
        return {
            "base_score": self.base_score,
            "total_budget": self.total_budget,
            "weights": self.weights.model_dump(),
            "budget": dict(self.budget),
            "preferred_trims": self.preferred_trims,
            "risk_penalties": self.risk_penalties.model_dump(),
        }


class CorvetteConfig(BaseModel):
    """Validated configuration for the Corvette Tracker.

    Allows both attribute access (config.output_dir) and dict-like access
    (config["output_dir"]) for backward compatibility with existing code.
    """

    sources: dict[str, SourceConfig] = Field(default_factory=dict)
    output_dir: str = "."
    database_path: str = "data/corvette_tracker.sqlite"
    ai_enrichment: AIEnrichmentConfig = Field(default_factory=AIEnrichmentConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _ensure_source_names_known(self) -> Self:
        known = {s.value for s in SourceType}
        for name in self.sources:
            if name not in known:
                raise ValueError(
                    f"Unknown source '{name}'. Allowed: {', '.join(sorted(known))}"
                )
        return self

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

    def to_flat_dict(self) -> dict[str, Any]:
        """Return the legacy flat dict format expected by current code."""
        return {
            "sources": {
                name: src.model_dump()
                for name, src in self.sources.items()
            },
            "output_dir": self.output_dir,
            "database_path": self.database_path,
            "ai_enrichment": self.ai_enrichment.model_dump(),
            "quality": self.quality.model_dump(),
            "scoring": self.scoring.to_flat_dict(),
        }


# ---------------------------------------------------------------------------
# Default config (plain dict, keeps backward-compat with existing code)
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
_default_source_urls: dict[str, tuple[str, list[str]]] = {}


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


def make_default_config() -> CorvetteConfig:
    """Build the validated default configuration with production source URLs."""
    return _build_default_dict()  # reuse the same builder


def _build_default_dict() -> CorvetteConfig:
    """Build a CorvetteConfig from DEFAULT_CONFIG."""
    return CorvetteConfig(
        sources={
            name: SourceConfig(**cfg)
            for name, cfg in DEFAULT_CONFIG.get("sources", {}).items()
        },
        output_dir=DEFAULT_CONFIG["output_dir"],
        database_path=DEFAULT_CONFIG["database_path"],
        ai_enrichment=AIEnrichmentConfig(**DEFAULT_CONFIG["ai_enrichment"]),
        quality=QualityConfig(**DEFAULT_CONFIG["quality"]),
        scoring=ScoringConfig(**DEFAULT_CONFIG["scoring"]),
    )


def _merge_loaded_into_defaults(loaded: dict[str, Any]) -> dict[str, Any]:
    """Merge a loaded YAML dict into DEFAULT_CONFIG."""
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


def load_config(path: str | None = None) -> dict[str, Any]:
    """Load, validate, and merge config from a YAML file.

    Returns a legacy flat dict to keep backward compatibility with existing
    callers. Validation errors raise ``ValidationError`` with a clear message.
    """
    if not path:
        return _build_default_dict().to_flat_dict()

    with Path(path).open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    merged = _merge_loaded_into_defaults(loaded)
    validated = CorvetteConfig(**merged)
    return validated.to_flat_dict()


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
