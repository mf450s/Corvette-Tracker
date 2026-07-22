from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self

from .enums import SourceType

# ---------------------------------------------------------------------------
# Source sub-config
# ---------------------------------------------------------------------------


class SourceConfig(BaseModel):
    """Per-source configuration block."""

    enabled: bool = True
    url: str = ""
    urls: list[str] = Field(default_factory=list)

    # Allow the YAML to carry extra keys (like comments) without failing
    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# AI enrichment sub-config
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Quality-assurance sub-config
# ---------------------------------------------------------------------------


class QualityConfig(BaseModel):
    """Crawl-quality thresholds that warn on suspiciously low counts."""

    enabled: bool = True
    min_total: int = 10
    min_by_source: dict[str, int] = Field(default_factory=lambda: {"AutoScout24": 5, "Kleinanzeigen": 10})

    model_config = {"extra": "ignore"}

    @field_validator("min_total")
    @classmethod
    def _min_total_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_total must be >= 1")
        return v


# ---------------------------------------------------------------------------
# Scoring sub-config
# ---------------------------------------------------------------------------


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
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    preferred_trims: list[str] = Field(default_factory=lambda: ["Grand Sport", "Z06", "ZR1"])
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
            "weights": self.weights.model_dump(),
            "preferred_trims": self.preferred_trims,
            "risk_penalties": self.risk_penalties.model_dump(),
        }


# ---------------------------------------------------------------------------
# Top-level config model
# ---------------------------------------------------------------------------


class CorvetteConfig(BaseModel):
    """Validated configuration for the Corvette Tracker."""

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
# Default source URLs (kept centralised)
# ---------------------------------------------------------------------------

DEFAULT_SOURCES: dict[str, dict[str, Any]] = {
    "autoscout24": {
        "enabled": True,
        "url": "https://www.autoscout24.de/lst?cat=ma16380mo19141%2Cma16380mo19140%2Cma16380mo20782%2Cma16380mo75462%2Cma16380mo21061%2Cma16380mo74838%2Cma16380mo19142%2Cma16380mo19143&cy=D&damaged_listing=exclude&desc=0&ocs_listing=include&powertype=kw&sort=standard&ustate=N%2CU&atype=C&search_id=nfg3gad0ed&source=homepage_search-mask",
        "urls": [
            "https://www.autoscout24.de/lst?cat=ma16380mo19141%2Cma16380mo19140%2Cma16380mo20782%2Cma16380mo75462%2Cma16380mo21061%2Cma16380mo74838%2Cma16380mo19142%2Cma16380mo19143&cy=D&damaged_listing=exclude&desc=0&ocs_listing=include&powertype=kw&sort=standard&ustate=N%2CU&atype=C&search_id=nfg3gad0ed&source=homepage_search-mask",
        ],
    },
    "kleinanzeigen": {
        "enabled": True,
        "url": "https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216",
        "urls": ["https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216"],
    },
    "autouncle": {
        "enabled": True,
        "url": "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette",
        "urls": [
            "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette",
            "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette?freetext=C6",
        ],
    },
    "classic_trader": {
        "enabled": True,
        "url": "https://www.classic-trader.com/de/automobile/suche/chevrolet/corvette",
        "urls": [
            "https://www.classic-trader.com/de/automobile/suche/chevrolet/corvette",
            "https://www.classic-trader.com/de/automobile/suche/chevrolet/corvette/c6",
        ],
    },
    "mobile_de": {
        "enabled": True,
        "url": "https://suchen.mobile.de/fahrzeuge/search.html?dam=false&fr=2005%3A2013&isSearchRequest=true&ms=5600%3B36%3B%3B&ref=quickSearch&s=Car&sb=rel&vc=Car",
    },
}


def make_default_config() -> CorvetteConfig:
    """Build the validated default configuration with production source URLs."""
    sources = {name: SourceConfig(**cfg) for name, cfg in DEFAULT_SOURCES.items()}
    return CorvetteConfig(
        sources=sources,
        output_dir=".",
        database_path="data/corvette_tracker.sqlite",
        ai_enrichment=AIEnrichmentConfig(enabled=False, provider=None, max_images=8),
        quality=QualityConfig(enabled=True, min_total=10, min_by_source={"AutoScout24": 5, "Kleinanzeigen": 10}),
        scoring=ScoringConfig(
            base_score=20,
            weights=ScoringWeights(manual_transmission=30, non_convertible=20, non_ls2=20, preferred_trim=10),
            preferred_trims=["Grand Sport", "Z06", "ZR1"],
            risk_penalties=RiskPenalties(
                accident_reported=18, damage_reported=14, salvage_import_possible=10,
                mileage_unclear=8, no_tuv=8, modified_heavily=4, sold_or_reserved=20,
            ),
        ),
    )


def load_config(path: str | None = None) -> dict[str, Any]:
    """Load, validate, and merge config from a YAML file.

    Returns a legacy flat dict to keep backward compatibility with existing
    callers. Validation errors raise ``ValidationError`` with a clear message.
    """
    if not path:
        return make_default_config().to_flat_dict()

    with Path(path).open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    # Merge loaded values on top of defaults
    defaults = make_default_config()

    merged_sources = {
        **defaults.sources,
        **{name: SourceConfig(**cfg) for name, cfg in loaded.get("sources", {}).items()},
    }

    merged_ai = AIEnrichmentConfig(**{
        **defaults.ai_enrichment.model_dump(),
        **(loaded.get("ai_enrichment") or {}),
    })

    merged_quality = QualityConfig(**{
        **defaults.quality.model_dump(),
        **(loaded.get("quality") or {}),
    })

    merged_scoring = ScoringConfig(**{
        **defaults.scoring.model_dump(),
        **(loaded.get("scoring") or {}),
    })

    validated = CorvetteConfig(
        sources=merged_sources,
        output_dir=loaded.get("output_dir", defaults.output_dir),
        database_path=loaded.get("database_path", defaults.database_path),
        ai_enrichment=merged_ai,
        quality=merged_quality,
        scoring=merged_scoring,
    )

    return validated.to_flat_dict()
