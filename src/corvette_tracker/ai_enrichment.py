from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .models import Listing


@dataclass(slots=True)
class EnrichmentInput:
    listing_id: str
    source: str
    title: str
    url: str
    description: str | None
    image_urls: list[str]
    known_fields: dict[str, Any]


@dataclass(slots=True)
class EnrichmentResult:
    provider: str
    confidence: float
    exterior_color: str | None = None
    interior_color: str | None = None
    transmission: str | None = None
    body_style: str | None = None
    eu_spec: bool | None = None
    equipment: list[str] = field(default_factory=list)
    visual_flags: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    notes: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AIEnrichmentProvider(Protocol):
    def analyze_listing(self, enrichment_input: EnrichmentInput) -> EnrichmentResult:
        """Analyze one listing using description text and image URLs."""
        ...


def _compact_known_fields(listing: Listing) -> dict[str, Any]:
    keys = [
        "price_eur",
        "mileage_km",
        "engine",
        "probable_engine",
        "engine_confidence",
        "power_hp",
        "trim",
        "first_registration",
        "tuv_until",
        "transmission",
        "exterior_color",
        "interior_color",
        "accident_status",
        "damage",
        "location_raw",
        "origin_country",
        "risk_flags",
    ]
    data = listing.to_dict()
    return {key: data.get(key) for key in keys if data.get(key) not in (None, [], {})}


def build_enrichment_input(listing: Listing, *, max_images: int = 8) -> EnrichmentInput:
    return EnrichmentInput(
        listing_id=listing.id,
        source=listing.source,
        title=listing.title,
        url=listing.url,
        description=listing.description_text,
        image_urls=list(listing.image_urls[:max_images]),
        known_fields=_compact_known_fields(listing),
    )


def _merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    merged = list(existing)
    seen = {item.lower() for item in merged}
    for item in additions:
        clean = " ".join(str(item).split())
        if not clean or clean.lower() in seen:
            continue
        merged.append(clean)
        seen.add(clean.lower())
    return merged


def _set_if_missing(listing: Listing, field_name: str, value: Any) -> None:
    if value in (None, "", [], {}):
        return
    if getattr(listing, field_name) in (None, "", [], {}):
        setattr(listing, field_name, value)


def merge_enrichment_result(listing: Listing, result: EnrichmentResult) -> Listing:
    # AI enrichments may be wrong. Only fill missing scalar fields; never
    # overwrite explicit parser/source values like transmission or colors.
    _set_if_missing(listing, "exterior_color", result.exterior_color)
    _set_if_missing(listing, "interior_color", result.interior_color)
    _set_if_missing(listing, "transmission", result.transmission)
    _set_if_missing(listing, "eu_spec", result.eu_spec)

    listing.equipment = _merge_unique(listing.equipment, result.equipment)
    listing.visual_flags = _merge_unique(listing.visual_flags, result.visual_flags)
    listing.risk_flags = _merge_unique(listing.risk_flags, result.risk_flags)
    listing.ai_enrichment = {
        "provider": result.provider,
        "confidence": result.confidence,
        "notes": result.notes,
        "evidence": result.evidence,
        "fields": {
            "exterior_color": result.exterior_color,
            "interior_color": result.interior_color,
            "transmission": result.transmission,
            "body_style": result.body_style,
            "eu_spec": result.eu_spec,
            "equipment": result.equipment,
            "visual_flags": result.visual_flags,
            "risk_flags": result.risk_flags,
        },
    }
    return listing


def enrich_listings(listings: list[Listing], provider: AIEnrichmentProvider, *, max_images: int = 8) -> list[Listing]:
    enriched: list[Listing] = []
    for listing in listings:
        enrichment_input = build_enrichment_input(listing, max_images=max_images)
        result = provider.analyze_listing(enrichment_input)
        enriched.append(merge_enrichment_result(listing, result))
    return enriched
