from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .enums import BodyStyleType, TransmissionType, TrimType


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
    price_label: str | None = None
    mileage_km: int | None = None
    engine: str | None = None
    probable_engine: str | None = None
    engine_confidence: float | None = None
    engine_note: str | None = None
    power_hp: int | None = None
    estimated_power_hp: int | None = None
    power_note: str | None = None
    trim: TrimType | None = None
    first_registration: str | None = None
    tuv_until: str | None = None
    transmission: TransmissionType | None = None
    body_style: BodyStyleType | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    eu_spec: bool | None = None
    equipment: list[str] = field(default_factory=list)
    visual_flags: list[str] = field(default_factory=list)
    ai_enrichment: dict[str, Any] = field(default_factory=dict)
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
    inference_notes: list[str] = field(default_factory=list)
    conflict_flags: list[str] = field(default_factory=list)
    model_year: int | None = None
    power_kw: int | None = None
    displacement_cc: int | None = None
    drivetrain: str | None = None
    condition: str | None = None
    owners_count: int | None = None
    service_history: bool | None = None
    warranty: bool | None = None
    magnetic_ride: bool | None = None
    active_exhaust: bool | None = None
    head_up_display: bool | None = None
    navigation: bool | None = None
    bose_audio: bool | None = None
    leather_interior: bool | None = None
    heated_seats: bool | None = None
    lt_package: str | None = None
    speedo_300: bool | None = None
    score: int = 0
    change_type: str = "new"
    previous_price_eur: int | None = None
    cluster_id: str | None = None
    validation_flags: list[dict[str, Any]] = field(default_factory=list)
    hidden: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
