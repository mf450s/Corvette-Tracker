from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import Listing

DEFAULT_SCORING_CONFIG: dict[str, Any] = {
    "base_score": 20,
    "weights": {
        # User preference weighting: Schalter sehr wichtig, kein Cabrio/LS2 wichtig, Trim mittel.
        "manual_transmission": 30,
        "non_convertible": 20,
        "non_ls2": 20,
        "preferred_trim": 10,
    },
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
        if key in {"weights", "risk_penalties"} and isinstance(value, dict):
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
    weights = scoring.get("weights") or {}
    score = _int_value(scoring.get("base_score"), 20)

    if listing.transmission == "manual":
        score += _int_value(weights.get("manual_transmission"))

    if listing.body_style and listing.body_style not in {"Cabrio", "Convertible"}:
        score += _int_value(weights.get("non_convertible"))

    engine = _engine_code(listing)
    if engine and engine != "LS2":
        score += _int_value(weights.get("non_ls2"))

    preferred_trims = set(str(trim) for trim in scoring.get("preferred_trims") or [])
    if listing.trim in preferred_trims:
        score += _int_value(weights.get("preferred_trim"))

    penalties = scoring.get("risk_penalties") or {}
    score -= sum(_int_value(penalties.get(flag)) for flag in (listing.risk_flags or []))
    return max(0, min(100, score))


def apply_score(listing: Listing, config: dict[str, Any] | None = None) -> Listing:
    listing.score = score_listing(listing, config)
    return listing


def apply_scores(listings: list[Listing], config: dict[str, Any] | None = None) -> list[Listing]:
    return [apply_score(listing, config) for listing in listings]
