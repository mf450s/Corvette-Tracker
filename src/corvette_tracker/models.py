from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Listing:
    id: str
    source: str
    source_listing_id: str | None
    url: str
    title: str
    generation: str = "C6"
    model: str | None = None
    price_eur: int | None = None
    mileage_km: int | None = None
    engine: str | None = None
    probable_engine: str | None = None
    engine_confidence: float | None = None
    engine_note: str | None = None
    power_hp: int | None = None
    trim: str | None = None
    first_registration: str | None = None
    tuv_until: str | None = None
    transmission: str | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    accident_status: str = "unbekannt"
    damage: str | None = None
    has_damage: bool | None = None
    location_raw: str | None = None
    location_country: str | None = None
    origin_country: str | None = None
    origin_confidence: float | None = None
    seller_type: str | None = None
    vin: str | None = None
    image_urls: list[str] = field(default_factory=list)
    description_text: str | None = None
    risk_flags: list[str] = field(default_factory=list)
    score: int = 0
    change_type: str = "new"
    previous_price_eur: int | None = None
    cluster_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
