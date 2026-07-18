from pathlib import Path

from corvette_tracker.models import Listing
from corvette_tracker.storage import TrackerStore


def make_listing(id="autoscout24_123", price=54900, mileage=68000):
    return Listing(
        id=id,
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


def test_update_online_status_creates_and_returns_row(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    # Need an existing listing for FK constraint
    store.upsert_listings([make_listing()])

    row = store.update_online_status("autoscout24_123", is_online=True, http_status=200)

    assert row["listing_id"] == "autoscout24_123"
    assert row["is_online"] == 1  # SQLite stores bools as 0/1
    assert row["http_status"] == 200
    assert row["error_message"] is None
    assert row["last_checked_at"] is not None


def test_update_online_status_upserts_instead_of_duplicating(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    store.update_online_status("autoscout24_123", is_online=True)
    store.update_online_status("autoscout24_123", is_online=False, http_status=404, error_message="Not found")

    rows = store.list_online_statuses()
    assert len(rows) == 1  # still one row
    assert rows[0]["is_online"] == 0
    assert rows[0]["http_status"] == 404
    assert rows[0]["error_message"] == "Not found"


def test_get_online_status_returns_none_for_unknown_listing(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    assert store.get_online_status("nonexistent") is None


def test_get_online_status_after_update(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    store.update_online_status("autoscout24_123", is_online=False)

    status = store.get_online_status("autoscout24_123")
    assert status is not None
    assert status["is_online"] == 0


def test_list_online_statuses_filters_by_flag(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing(id="a", price=10000)])
    store.upsert_listings([make_listing(id="b", price=20000)])
    store.upsert_listings([make_listing(id="c", price=30000)])

    store.update_online_status("a", is_online=True)
    store.update_online_status("b", is_online=False, http_status=410)
    store.update_online_status("c", is_online=True)

    offline = store.list_online_statuses(is_online=False)
    assert len(offline) == 1
    assert offline[0]["listing_id"] == "b"

    online = store.list_online_statuses(is_online=True)
    assert len(online) == 2


def test_list_online_statuses_all_when_no_filter(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    assert store.list_online_statuses() == []

    store.upsert_listings([make_listing(id="x", price=10000)])
    store.update_online_status("x", is_online=True)
    assert len(store.list_online_statuses()) == 1
