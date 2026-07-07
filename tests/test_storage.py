from pathlib import Path

from corvette_tracker.models import Listing
from corvette_tracker.storage import TrackerStore


def make_listing(price=54900, mileage=68000):
    return Listing(
        id="autoscout24_123",
        source="AutoScout24",
        source_listing_id="123",
        url="https://example.test/listing/123",
        title="Chevrolet Corvette C6 Grand Sport",
        generation="C6",
        price_eur=price,
        mileage_km=mileage,
        location_raw="Hamburg",
        trim="Grand Sport",
        engine="LS3",
        image_urls=["https://example.test/corvette.jpg"],
        risk_flags=[],
        score=80,
    )


def test_store_marks_first_seen_listing_as_new(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    result = store.upsert_listings([make_listing()])

    assert result[0].change_type == "new"
    assert store.list_active()[0].id == "autoscout24_123"


def test_store_detects_price_change_on_second_run(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing(price=54900)])
    changed = store.upsert_listings([make_listing(price=52900)])

    assert changed[0].change_type == "price_change"
    assert changed[0].previous_price_eur == 54900
