from __future__ import annotations

import re
from typing import Any

from .models import Listing

# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------
CRITICAL = "critical"   # data should be rejected, not stored
ERROR = "error"         # likely wrong, still stored with big flag
WARN = "warning"        # improbable — store but call out
INFO = "info"           # advisory note

# ---------------------------------------------------------------------------
# Sane ranges for C6 Corvette listings
# ---------------------------------------------------------------------------
C6_YEARS = (2004, 2014)  # production + buffer for leftovers / over-runs
PRICE_MIN = 100           # anything under 100€ is suspicious (scraping error)
PRICE_MAX = 500_000
MILEAGE_MIN = 100         # under 100 km is unrealistic for a 10+ year old car
MILEAGE_MAX = 500_000
POWER_HZ = (50, 1200)

# Known valid engine->trim mappings for C6
ENGINE_TRIM_MAP: dict[str, set[str]] = {
    "LS9": {"ZR1"},
    "LS7": {"Z06"},
    "LS3": {"Base", "Grand Sport", "Special Edition"},
    "LS2": {"Base", "Special Edition"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flag(*, field: str, severity: str, code: str, message: str) -> dict:
    return {
        "field": field,
        "severity": severity,
        "code": code,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Individual field checks
# ---------------------------------------------------------------------------


def _check_price(listing: Listing) -> list[dict]:
    flags: list[dict] = []
    p = listing.price_eur
    if p is not None:
        if p < 0:
            flags.append(_flag(
                field="price_eur", severity=CRITICAL, code="price_negative",
                message=f"Preis negativ ({p} €)",
            ))
        elif p == 0:
            flags.append(_flag(
                field="price_eur", severity=ERROR, code="price_zero",
                message="Preis ist 0 € — wahrscheinlich Fehler beim Extrahieren",
            ))
        elif p < PRICE_MIN and listing.price_label is None:
            flags.append(_flag(
                field="price_eur", severity=WARN, code="price_very_low",
                message=f"Preis ungewöhnlich niedrig ({p} €)",
            ))
        elif p > PRICE_MAX:
            flags.append(_flag(
                field="price_eur", severity=WARN, code="price_very_high",
                message=f"Preis ungewöhnlich hoch ({p} €)",
            ))
    else:
        flags.append(_flag(
            field="price_eur", severity=INFO, code="price_missing",
            message="Kein Preis extrahiert"
        ))
    return flags


def _check_mileage(listing: Listing) -> list[dict]:
    flags: list[dict] = []
    m = listing.mileage_km
    if m is not None:
        if m < 0:
            flags.append(_flag(
                field="mileage_km", severity=CRITICAL, code="mileage_negative",
                message=f"Laufleistung negativ ({m} km)",
            ))
        elif m == 0:
            flags.append(_flag(
                field="mileage_km", severity=ERROR, code="mileage_zero",
                message="Laufleistung ist 0 km — wahrscheinlich Fehler beim Extrahieren",
            ))
        elif m < MILEAGE_MIN:
            flags.append(_flag(
                field="mileage_km", severity=WARN, code="mileage_very_low",
                message=f"Laufleistung ungewöhnlich niedrig ({m} km)",
            ))
        elif m > MILEAGE_MAX:
            flags.append(_flag(
                field="mileage_km", severity=WARN, code="mileage_very_high",
                message=f"Laufleistung ungewöhnlich hoch ({m} km)",
            ))
    else:
        flags.append(_flag(
            field="mileage_km", severity=INFO, code="mileage_missing",
            message="Keine Laufleistung extrahiert"
        ))
    return flags


def _check_power(listing: Listing) -> list[dict]:
    flags: list[dict] = []
    hp = listing.power_hp
    if hp is not None:
        if hp < 0:
            flags.append(_flag(
                field="power_hp", severity=CRITICAL, code="power_negative",
                message=f"Leistung negativ ({hp} PS)",
            ))
        elif hp == 0:
            flags.append(_flag(
                field="power_hp", severity=ERROR, code="power_zero",
                message="Leistung ist 0 PS — wahrscheinlich Fehler beim Extrahieren",
            ))
        elif hp < POWER_HZ[0]:
            flags.append(_flag(
                field="power_hp", severity=WARN, code="power_very_low",
                message=f"Leistung ungewöhnlich niedrig ({hp} PS)",
            ))
        elif hp > POWER_HZ[1]:
            flags.append(_flag(
                field="power_hp", severity=WARN, code="power_very_high",
                message=f"Leistung ungewöhnlich hoch ({hp} PS)",
            ))
    return flags


def _check_year(listing: Listing) -> list[dict]:
    flags: list[dict] = []
    reg = listing.first_registration
    if reg:
        year_match = re.search(r"\b(20\d\d)", reg)
        if year_match:
            year = int(year_match.group(1))
            if year < C6_YEARS[0] or year > C6_YEARS[1]:
                flags.append(_flag(
                    field="first_registration", severity=WARN, code="year_out_of_range",
                    message=f"EZ-Jahr {year} liegt außerhalb der C6-Produktionszeit "
                            f"({C6_YEARS[0]}–{C6_YEARS[1]})",
                ))
    return flags


def _check_missing_trim(listing: Listing) -> list[dict]:
    flags: list[dict] = []
    if listing.trim is None or listing.trim == "":
        flags.append(_flag(
            field="trim", severity=INFO, code="trim_missing",
            message="Kein Trim erkannt — als Base gelistet"
        ))
    return flags


def _check_body_style(listing: Listing) -> list[dict]:
    flags: list[dict] = []
    if listing.body_style is None or listing.body_style == "":
        flags.append(_flag(
            field="body_style", severity=INFO, code="body_style_missing",
            message="Keine Karosserieform erkannt"
        ))
    return flags


def _check_missing_price_and_label(listing: Listing) -> list[dict]:
    """Flag listings that have neither a numeric price nor a price label."""
    flags: list[dict] = []
    if listing.price_eur is None and (listing.price_label or "").strip() == "":
        flags.append(_flag(
            field="price_eur", severity=WARN, code="price_fully_missing",
            message="Weder Preis noch Preis-Label extrahiert — "
                    "wahrscheinlich Blockierung oder Parsing-Fehler"
        ))
    return flags


# ---------------------------------------------------------------------------
# Cross-field consistency checks
# ---------------------------------------------------------------------------


def _check_engine_trim_consistency(listing: Listing) -> list[dict]:
    flags: list[dict] = []
    engine = listing.engine or listing.probable_engine
    trim = listing.trim
    if engine and trim:
        allowed = ENGINE_TRIM_MAP.get(engine)
        if allowed is not None and trim not in allowed:
            flags.append(_flag(
                field="engine", severity=WARN, code="engine_trim_mismatch",
                message=f"Motor {engine} passt nicht zu Trim {trim} "
                        f"(erwartet: {', '.join(allowed)})"
            ))
    return flags


# ---------------------------------------------------------------------------
# Historical range sanity check (uses existing store data)
# ---------------------------------------------------------------------------


def sanity_check_against_previous(
    listing: Listing,
    previous_listings: list[Listing],
) -> list[dict]:
    """Compare a listing's price and mileage against aggregate of previous listings.

    Uses simple percentile-based outlier detection (box-plot style).
    Flags values that fall more than 3 times IQR above the 3rd quartile or below Q1.
    """
    flags: list[dict] = []

    prices = sorted(
        [p.price_eur for p in previous_listings if p.price_eur is not None],
    )
    mileages = sorted(
        [m.mileage_km for m in previous_listings if m.mileage_km is not None],
    )

    if listing.price_eur is not None and len(prices) >= 10:
        q1 = prices[len(prices) // 4]
        q3 = prices[(3 * len(prices)) // 4]
        iqr = q3 - q1
        lower = q1 - 3.0 * iqr
        upper = q3 + 3.0 * iqr
        if listing.price_eur < lower:
            flags.append(_flag(
                field="price_eur", severity=INFO, code="price_below_historical_range",
                message=f"Preis ({listing.price_eur} €) liegt deutlich unter "
                        f"historischem Bereich (Q1={q1}, IQR={iqr})"
            ))
        elif listing.price_eur > upper:
            flags.append(_flag(
                field="price_eur", severity=INFO, code="price_above_historical_range",
                message=f"Preis ({listing.price_eur} €) liegt deutlich über "
                        f"historischem Bereich (Q3={q3}, IQR={iqr})"
            ))

    if listing.mileage_km is not None and len(mileages) >= 10:
        q1 = mileages[len(mileages) // 4]
        q3 = mileages[(3 * len(mileages)) // 4]
        iqr = q3 - q1
        upper = q3 + 3.0 * iqr
        if listing.mileage_km > upper:
            flags.append(_flag(
                field="mileage_km", severity=INFO, code="mileage_above_historical_range",
                message=f"Laufleistung ({listing.mileage_km} km) liegt deutlich über "
                        f"historischem Bereich (Q3={q3}, IQR={iqr})"
            ))

    return flags


# ---------------------------------------------------------------------------
# Combined entry-points
# ---------------------------------------------------------------------------


def validate_listing(listing: Listing) -> list[dict]:
    """Run all field-level and cross-field validation checks.

    Returns a list of flag dicts: {field, severity, code, message}.
    Does NOT mutate the listing — call ``apply_validation_flags`` to do that.
    """
    flags: list[dict] = []
    flags.extend(_check_price(listing))
    flags.extend(_check_mileage(listing))
    flags.extend(_check_power(listing))
    flags.extend(_check_year(listing))
    flags.extend(_check_engine_trim_consistency(listing))
    flags.extend(_check_missing_trim(listing))
    flags.extend(_check_body_style(listing))
    flags.extend(_check_missing_price_and_label(listing))
    return flags


def apply_validation_flags(
    listing: Listing, flags: list[dict] | None = None
) -> Listing:
    """Attach validation flags to the listing in-place and return it.

    If ``flags`` is not provided, runs ``validate_listing`` automatically.
    """
    if flags is None:
        flags = validate_listing(listing)
    listing.validation_flags = flags
    return listing


def safe_normalize_listing(
    normalize_func: Any,
    *args: Any,
    **kwargs: Any,
) -> Listing | None:
    """Call ``normalize_listing`` with per-item error isolation.

    Returns the listing on success, None on exception (the exception
    is accessible via ``safe_normalize_listing.last_error[0]``).
    """
    try:
        return normalize_func(*args, **kwargs)
    except Exception as exc:
        safe_normalize_listing._last_error[0] = exc  # type: ignore[attr-defined]
        return None


safe_normalize_listing._last_error = [None]  # type: ignore[attr-defined]
