from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .models import Listing


def _slug(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "unknown").lower()).strip("-")


def _soft_key(listing: Listing) -> str:
    price_bucket = (listing.price_eur or 0) // 1000
    mileage_bucket = (listing.mileage_km or 0) // 5000
    raw = "|".join([
        _slug(listing.trim),
        _slug(listing.engine),
        _slug(listing.location_raw),
        str(price_bucket),
        str(mileage_bucket),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


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
    vin_groups: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        if listing.vin:
            vin_groups[listing.vin].append(listing)

    for vin, group in vin_groups.items():
        if len(group) > 1:
            for listing in group:
                listing.cluster_id = f"vin_{vin.lower()}"

    soft_groups: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        if not listing.cluster_id:
            soft_groups[_soft_key(listing)].append(listing)

    for key, group in soft_groups.items():
        cluster_id = f"soft_{key}"
        for listing in group:
            listing.cluster_id = cluster_id
    return listings
