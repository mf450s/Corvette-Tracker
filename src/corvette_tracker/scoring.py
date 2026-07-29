from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import Listing

DEFAULT_SCORING_CONFIG: dict[str, Any] = {
    "base_score": 30,
    "weights": {
        "manual_transmission": 15,
        "automatic_transmission": 5,
        "non_convertible": 10,
    },
    "engine_scores": {
        "LS2": 0,
        "LS3": 10,
        "LS7": 20,
        "LS9": 30,
    },
    "trim_scores": {
        "Base": 0,
        "Grand Sport": 5,
        "Z06": 10,
        "ZR1": 15,
    },
    "mileage_bonus": [
        {"max_km": 30000, "points": 10},
        {"max_km": 80000, "points": 5},
        {"max_km": 150000, "points": 2},
    ],
    "completeness": {
        "has_engine": 3,
        "has_mileage": 2,
        "has_price": 2,
        "has_images": 2,
    },
    "eu_spec_bonus": 5,
    "no_engine_penalty": 5,
    "preferred_trims": ["Grand Sport", "Z06", "ZR1"],
    "risk_penalties": {
        "accident_reported": 18,
        "damage_reported": 14,
        "salvage_import_possible": 10,
        "mileage_unclear": 8,
        "no_tuv": 8,
        "modified_heavily": 4,
        "sold_or_reserved": 20,
    },
}


def merge_scoring_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_SCORING_CONFIG)
    if not config:
        return merged
    for key, value in config.items():
        if key in {"weights", "engine_scores", "trim_scores",
                    "mileage_bonus", "completeness", "risk_penalties"
                    } and isinstance(value, dict if key != "mileage_bonus" else list):
            if key == "mileage_bonus":
                merged[key] = value
            else:
                merged[key] = merged.get(key, {}) | value
        else:
            merged[key] = value
    return merged


def _int_value(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _engine_code(listing: Listing) -> str | None:
    return listing.engine or listing.probable_engine


def score_listing(listing: Listing, config: dict[str, Any] | None = None) -> int:
    scoring = merge_scoring_config(config)
    score = _int_value(scoring.get("base_score"), 30)

    # ── 1. Engine score ───────────────────────────────────────────────
    engine = _engine_code(listing)
    engine_scores: dict[str, int] = scoring.get("engine_scores") or {}
    if engine and engine in engine_scores:
        score += _int_value(engine_scores[engine])
    else:
        score -= _int_value(scoring.get("no_engine_penalty"), 5)

    # ── 2. Trim score ─────────────────────────────────────────────────
    trim_scores: dict[str, int] = scoring.get("trim_scores") or {}
    if listing.trim and listing.trim in trim_scores:
        score += _int_value(trim_scores[listing.trim])

    # ── 3. Transmission ────────────────────────────────────────────────
    weights: dict[str, int] = scoring.get("weights") or {}
    if listing.transmission == "manual":
        score += _int_value(weights.get("manual_transmission"), 15)
    elif listing.transmission == "automatic":
        score += _int_value(weights.get("automatic_transmission"), 5)

    # ── 4. Body style ──────────────────────────────────────────────────
    if listing.body_style and listing.body_style not in {"Cabrio", "Convertible"}:
        score += _int_value(weights.get("non_convertible"), 10)

    # ── 5. Mileage bonus ───────────────────────────────────────────────
    if listing.mileage_km is not None:
        for bracket in scoring.get("mileage_bonus") or []:
            if listing.mileage_km <= _int_value(bracket.get("max_km"), 999999):
                score += _int_value(bracket.get("points"))
                break

    # ── 6. Data completeness ────────────────────────────────────────────
    completeness: dict[str, int] = scoring.get("completeness") or {}
    if listing.engine or listing.probable_engine:
        score += _int_value(completeness.get("has_engine"))
    if listing.mileage_km is not None:
        score += _int_value(completeness.get("has_mileage"))
    if listing.price_eur is not None:
        score += _int_value(completeness.get("has_price"))
    if listing.image_urls and len(listing.image_urls) > 0:
        score += _int_value(completeness.get("has_images"))

    # ── 7. EU spec bonus ───────────────────────────────────────────────
    if listing.eu_spec is True:
        score += _int_value(scoring.get("eu_spec_bonus"), 5)

    # ── 8. Risk penalties ──────────────────────────────────────────────
    penalties: dict[str, int] = scoring.get("risk_penalties") or {}
    for flag in listing.risk_flags or []:
        score -= _int_value(penalties.get(flag))

    return max(0, min(100, score))


def apply_score(listing: Listing, config: dict[str, Any] | None = None) -> Listing:
    listing.score = score_listing(listing, config)
    return listing


def apply_scores(listings: list[Listing], config: dict[str, Any] | None = None) -> list[Listing]:
    return [apply_score(listing, config) for listing in listings]
