from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from .models import Listing


# Scalar fields that can be cross-filled between cluster listings
SCALAR_FIELDS: set[str] = {
    "price_eur", "price_label", "mileage_km",
    "engine", "probable_engine", "engine_confidence", "engine_note",
    "power_hp", "estimated_power_hp", "power_note",
    "trim", "first_registration", "tuv_until",
    "transmission", "body_style",
    "exterior_color", "interior_color",
    "location_raw", "location_country",
    "origin_country", "origin_confidence",
    "seller_type", "vin", "description_text",
    "accident_status", "damage", "has_damage",
    "eu_spec",
}

# List fields that should be merged (deduplicated)
LIST_FIELDS: set[str] = {
    "equipment", "risk_flags", "inference_notes",
    "conflict_flags", "visual_flags", "image_urls",
}


def _slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "unknown").lower()).strip("-")


def _normalize_color(value: str | None) -> str:
    """Normalize color names across languages for matching."""
    if not value:
        return "unknown"
    v = value.strip().lower()
    mapping = {
        "schwarz": "black",
        "weiss": "white", "weiß": "white",
        "rot": "red",
        "blau": "blue",
        "grün": "green", "gruen": "green",
        "gelb": "yellow",
        "grau": "gray", "grey": "gray",
        "silber": "silver",
        "braun": "brown",
        "orange": "orange",
        "lila": "purple", "violett": "purple",
        "beige": "beige",
        "creme": "cream",
        "gold": "gold",
        "bronze": "bronze",
    }
    return mapping.get(v, v)


def _normalize_trim(value: str | None) -> str:
    """Normalize trim for matching — strip C6 prefix, normalize whitespace."""
    if not value:
        return "base"
    t = value.strip()
    t = re.sub(r"\bc\s*6\b", "", t, flags=re.I).strip()
    t = re.sub(r"\bZ\s*0*6\b", "z06", t, flags=re.I)
    t = re.sub(r"\bZ\s*R\s*1\b", "zr1", t, flags=re.I)
    return t.lower()


def _extract_year(value: str | None) -> str:
    """Extract 4-digit year from e.g. '2005-06' or '2005'."""
    if not value:
        return "0"
    m = re.search(r"(\d{4})", value)
    return m.group(1) if m else "0"


def _soft_key(listing: Listing) -> str:
    """Primary soft-matching key using all available fields."""
    price_bucket = (listing.price_eur or 0) // 1000
    mileage_bucket = (listing.mileage_km or 0) // 5000
    power_bucket = (listing.power_hp or 0) // 50
    year = _extract_year(listing.first_registration)

    raw = "|".join([
        _slug(listing.engine),
        _slug(_normalize_trim(listing.trim)),
        _slug(listing.location_raw),
        str(price_bucket),
        str(mileage_bucket),
        _slug(listing.transmission),
        _slug(listing.body_style),
        _slug(_normalize_color(listing.exterior_color)),
        year,
        str(power_bucket),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _all_soft_keys(listing: Listing) -> list[tuple[str, str]]:
    """Generate multiple soft keys with different levels of specificity.

    Returns list of (key_label, key_hash) pairs. Key labels tell us which
    strategy matched; tried in order from most to least specific.
    """
    keys: list[tuple[str, str]] = [("full", _soft_key(listing))]

    tb = (listing.price_eur or 0) // 1000
    mb = (listing.mileage_km or 0) // 5000
    pb = (listing.power_hp or 0) // 50
    yr = _extract_year(listing.first_registration)

    # Fallback: skip trim (most common source of variation between platforms)
    raw_no_trim = "|".join([
        _slug(listing.engine),
        _slug(listing.location_raw),
        str(tb), str(mb),
        _slug(listing.transmission),
        _slug(listing.body_style),
        _slug(_normalize_color(listing.exterior_color)),
        yr, str(pb),
    ])
    keys.append(("no_trim", hashlib.sha1(raw_no_trim.encode("utf-8")).hexdigest()[:12]))

    # Fallback: skip location (text varies between sources)
    raw_no_loc = "|".join([
        _slug(listing.engine),
        _slug(_normalize_trim(listing.trim)),
        str(tb), str(mb),
        _slug(listing.transmission),
        _slug(listing.body_style),
        _slug(_normalize_color(listing.exterior_color)),
        yr, str(pb),
    ])
    keys.append(("no_loc", hashlib.sha1(raw_no_loc.encode("utf-8")).hexdigest()[:12]))

    # Fallback: skip engine (inferred vs explicit between sources)
    raw_no_eng = "|".join([
        _slug(_normalize_trim(listing.trim)),
        _slug(listing.location_raw),
        str(tb), str(mb),
        _slug(listing.transmission),
        _slug(listing.body_style),
        _slug(_normalize_color(listing.exterior_color)),
        yr, str(pb),
    ])
    keys.append(("no_eng", hashlib.sha1(raw_no_eng.encode("utf-8")).hexdigest()[:12]))

    # Final fallback: legacy fields (engine + trim + location + price + mileage)
    # Same as the original _soft_key — ensures backward compatibility.
    raw_legacy = "|".join([
        _slug(listing.engine),
        _slug(_normalize_trim(listing.trim)),
        _slug(listing.location_raw),
        str(tb), str(mb),
    ])
    keys.append(("legacy", hashlib.sha1(raw_legacy.encode("utf-8")).hexdigest()[:12]))

    return keys


def _dedupe_exact_urls(listings: list[Listing]) -> list[Listing]:
    by_url: dict[str, Listing] = {}
    for listing in listings:
        existing = by_url.get(listing.url)
        if existing is None:
            by_url[listing.url] = listing
            continue
        existing_score = 1 if existing.source_listing_id and not existing.source_listing_id.startswith(("ka-", "as24-", "mobile-")) else 0
        listing_score = 1 if listing.source_listing_id and not listing.source_listing_id.startswith(("ka-", "as24-", "mobile-")) else 0
        if listing_score >= existing_score:
            by_url[listing.url] = listing
    return list(by_url.values())


def assign_clusters(listings: list[Listing]) -> list[Listing]:
    listings = _dedupe_exact_urls(listings)

    # VIN hard-match
    vin_groups: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        if listing.vin:
            vin_groups[listing.vin].append(listing)
    for vin, group in vin_groups.items():
        if len(group) > 1:
            for listing in group:
                listing.cluster_id = f"vin_{vin.lower()}"

    # Soft match: try multiple key strategies in order (most specific first).
    # Every listing gets a cluster_id — even singles, so downstream code can
    # always rely on it.
    for key_label, _ in _all_soft_keys(listings[0]) if listings else []:
        groups: dict[str, list[Listing]] = defaultdict(list)
        for listing in listings:
            if listing.cluster_id:
                continue
            keys = dict(_all_soft_keys(listing))
            groups[keys[key_label]].append(listing)

        for key, group in groups.items():
            if len(group) >= 2:
                cluster_id = f"soft_{key_label}_{key}"
                for listing in group:
                    listing.cluster_id = cluster_id

    # Remaining singles get a unique cluster_id from their full key
    for listing in listings:
        if not listing.cluster_id:
            keys = dict(_all_soft_keys(listing))
            listing.cluster_id = f"singleton_{keys['full']}"

    return listings


def _filled_count(listing: Listing) -> int:
    """Count non-None scalar + non-empty list fields."""
    count = 0
    for fname in SCALAR_FIELDS:
        val = getattr(listing, fname, None)
        if val is not None and val != "" and val != "unbekannt":
            count += 1
    for fname in LIST_FIELDS:
        val = getattr(listing, fname, None)
        if val:
            count += len(val)
    return count


def _pick_best_listing(group: list[Listing]) -> Listing:
    """Pick the listing with the most filled detail fields."""
    return max(group, key=lambda l: (_filled_count(l), l.score or 0))


def _fill_missing(target: Listing, source: Listing) -> bool:
    """Fill None/empty scalar fields in target from source. Returns True if anything changed."""
    changed = False
    for fname in SCALAR_FIELDS:
        tv = getattr(target, fname, None)
        sv = getattr(source, fname, None)
        if sv is None:
            continue
        if tv is None or tv == "" or tv == "unbekannt":
            if sv != "" and sv != "unbekannt":
                setattr(target, fname, sv)
                changed = True
        elif fname == "price_eur":
            # Prefer lower price (more recent/competitive)
            if isinstance(sv, int) and isinstance(tv, int) and sv < tv:
                setattr(target, fname, sv)
                changed = True
        elif fname == "mileage_km":
            # Prefer lower mileage (more recent/conservative estimate)
            if isinstance(sv, int) and isinstance(tv, int) and 0 < sv < tv:
                setattr(target, fname, sv)
                changed = True
        elif fname in ("exterior_color", "interior_color"):
            # Prefer more descriptive color when both normalize to same base
            if isinstance(sv, str) and isinstance(tv, str):
                if _normalize_color(sv) == _normalize_color(tv) and len(sv) > len(tv):
                    setattr(target, fname, sv)
                    changed = True
    return changed


def enrich_clusters(listings: list[Listing]) -> list[Listing]:
    """Cross-fill missing details within each cluster.

    Listings in the same cluster share their best-known detail values:
    - Scalar fields are filled from the most complete listing in the cluster
    - List fields are merged (deduplicated)
    - The best score is propagated

    Returns the same number of listings, each with enriched detail data.
    """
    clusters: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        if listing.cluster_id:
            clusters[listing.cluster_id].append(listing)

    for cluster_id, group in clusters.items():
        if len(group) < 2:
            continue

        best = _pick_best_listing(group)

        # First pass: fill all from best
        for listing in group:
            if listing is not best:
                _fill_missing(listing, best)

        # Second pass: fill best from others
        for listing in group:
            if listing is not best:
                _fill_missing(best, listing)

        # Third pass: propagate improved best values back to all members
        for listing in group:
            if listing is not best:
                _fill_missing(listing, best)

        # Merge list fields across cluster (unique union)
        merged_lists: dict[str, list[Any]] = {}
        for fname in LIST_FIELDS:
            all_items: list[Any] = []
            for l in group:
                all_items.extend(getattr(l, fname) or [])
            if fname == "validation_flags":
                seen = {str(d) for d in all_items}
                merged = [eval(s) for s in seen]
                merged_lists[fname] = merged
            else:
                merged_lists[fname] = list(dict.fromkeys(all_items))

        # Also merge score (take max)
        best_score = max(l.score for l in group)

        # Apply merged data to all listings in cluster
        for listing in group:
            for fname, merged in merged_lists.items():
                setattr(listing, fname, merged)
            listing.score = best_score

    return listings
