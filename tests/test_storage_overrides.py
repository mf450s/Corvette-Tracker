from pathlib import Path

from corvette_tracker.models import Listing
from corvette_tracker.storage import TrackerStore


def make_listing(price=54900, engine="LS3", title="Chevrolet Corvette C6"):
    return Listing(
        id="autoscout24_123",
        source="AutoScout24",
        source_listing_id="123",
        url="https://example.test/listing/123",
        title=title,
        generation="C6",
        price_eur=price,
        mileage_km=68000,
        engine=engine,
        score=80,
    )


def test_manual_override_is_applied_to_existing_listing(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing(engine=None)])

    updated = store.update_overrides("autoscout24_123", {"engine": "LS3", "transmission": "manual"})

    assert updated.engine == "LS3"
    assert updated.transmission == "manual"
    assert store.list_active()[0].engine == "LS3"


def test_manual_override_survives_later_source_upsert(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing(price=54900, engine=None)])
    store.update_overrides("autoscout24_123", {"engine": "LS3", "title": "Nachgebesserte C6"})

    changed = store.upsert_listings([make_listing(price=52900, engine="LS2", title="Source title")])
    active = store.list_active()[0]

    assert changed[0].change_type == "price_change"
    assert active.price_eur == 52900
    assert active.engine == "LS3"
    assert active.title == "Nachgebesserte C6"
    assert active.previous_price_eur == 54900


def test_manual_override_rejects_unknown_fields(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    try:
        store.update_overrides("autoscout24_123", {"does_not_exist": "x"})
    except ValueError as exc:
        assert "does_not_exist" in str(exc)
    else:
        raise AssertionError("unknown override field should fail")
