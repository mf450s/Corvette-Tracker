from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from .models import Listing

DEFAULT_SCORING_CONFIG: dict[str, Any] = {
    # Benutzer konfiguriert nur: Budget-Punkte pro Kategorie
    # Summe sollte total_budget nicht übersteigen
    "total_budget": 80,
    "budget": {
        "engine": 25,
        "transmission": 15,
        "trim": 12,
        "body": 10,
        "mileage": 10,
        "completeness": 5,
        "eu_spec": 3,
    },
    # Interne Verteilungslogik — selten ändern
    "engine_distribution": {
        "LS2": 0.0,
        "LS3": 0.33,
        "LS7": 0.66,
        "LS9": 1.0,
    },
    "trim_distribution": {
        "Base": 0.0,
        "Grand Sport": 0.33,
        "Z06": 0.66,
        "ZR1": 1.0,
    },
    "mileage_distribution": [
        {"max_km": 30000, "fraction": 1.0},
        {"max_km": 80000, "fraction": 0.5},
        {"max_km": 150000, "fraction": 0.2},
    ],
    "transmission": {
        "manual": 1.0,
        "automatic": 0.3,
    },
    "completeness_fields": 4,
    "completeness_keys": ["has_engine", "has_mileage", "has_price", "has_images"],
    "base_score": 20,
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
        if key in {"budget", "risk_penalties"} and isinstance(value, dict):
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
    budget = cast(dict[str, int], scoring.get("budget") or {})
    score = _int_value(scoring.get("base_score"), 20)

    # ── 1. Engine ──────────────────────────────────────────────────────
    engine = _engine_code(listing)
    eng_budget = _int_value(budget.get("engine"))
    distrib = cast(dict[str, float], scoring.get("engine_distribution") or {})
    if engine and engine in distrib:
        score += int(eng_budget * distrib[engine])
    elif engine is None:
        score -= max(3, eng_budget // 3)  # penalty for no engine info

    # ── 2. Transmission ────────────────────────────────────────────────
    trans_budget = _int_value(budget.get("transmission"))
    trans = cast(dict[str, float], scoring.get("transmission") or {})
    if listing.transmission in trans:
        score += int(trans_budget * trans[listing.transmission])

    # ── 3. Trim ────────────────────────────────────────────────────────
    trim_budget = _int_value(budget.get("trim"))
    tdistrib = cast(dict[str, float], scoring.get("trim_distribution") or {})
    if listing.trim and listing.trim in tdistrib:
        score += int(trim_budget * tdistrib[listing.trim])

    # ── 4. Body style ──────────────────────────────────────────────────
    body_budget = _int_value(budget.get("body"))
    if listing.body_style and listing.body_style not in {"Cabrio", "Convertible"}:
        score += body_budget

    # ── 5. Mileage ─────────────────────────────────────────────────────
    mile_budget = _int_value(budget.get("mileage"))
    if listing.mileage_km is not None:
        for bracket in scoring.get("mileage_distribution") or []:
            if listing.mileage_km <= _int_value(bracket.get("max_km"), 999999):
                score += int(mile_budget * bracket.get("fraction", 0))
                break

    # ── 6. Data completeness ────────────────────────────────────────────
    comp_budget = _int_value(budget.get("completeness"))
    n_fields = max(1, _int_value(scoring.get("completeness_fields"), 4))
    per_field = comp_budget / n_fields  # can be fractional
    if listing.engine or listing.probable_engine:
        score += per_field
    if listing.mileage_km is not None:
        score += per_field
    if listing.price_eur is not None:
        score += per_field
    if listing.image_urls and len(listing.image_urls) > 0:
        score += per_field

    # ── 7. EU spec ─────────────────────────────────────────────────────
    if listing.eu_spec is True:
        score += _int_value(budget.get("eu_spec"))

    # ── 8. Risk penalties ──────────────────────────────────────────────
    penalties = cast(dict[str, int], scoring.get("risk_penalties") or {})
    for flag in listing.risk_flags or []:
        score -= _int_value(penalties.get(flag))

    return max(0, min(100, int(score)))


def apply_score(listing: Listing, config: dict[str, Any] | None = None) -> Listing:
    listing.score = score_listing(listing, config)
    return listing


def apply_scores(listings: list[Listing], config: dict[str, Any] | None = None) -> list[Listing]:
    return [apply_score(listing, config) for listing in listings]
