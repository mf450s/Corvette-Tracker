from pathlib import Path

from corvette_tracker.enums import TrimType
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


def test_store_context_manager_closes_connection(tmp_path: Path):
    db_path = tmp_path / "scoped.sqlite"
    with TrackerStore(db_path) as store:
        store.upsert_listings([make_listing()])
    store.close()


def test_list_filtered_reuses_public_filter_contract(tmp_path: Path):
    store = TrackerStore(tmp_path / "filtered.sqlite")
    store.upsert_listings([make_listing(id="cheap", price=20000)])
    store.upsert_listings([make_listing(id="expensive", price=80000)])

    result = store.list_filtered({"price_max": "30000"})

    assert [listing.id for listing in result] == ["cheap"]


def test_store_marks_first_seen_listing_as_new(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    result = store.upsert_listings([make_listing()])

    assert result[0].change_type == "new"
    assert store.list_active()[0].id == "autoscout24_123"


def test_update_listing_url_adopts_canonical_url(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    new_url = "https://example.test/listing/123-canonical"
    changed = store.update_listing_url("autoscout24_123", new_url)

    assert changed is True
    listing = store.get_listing("autoscout24_123")
    assert listing is not None
    assert listing.url == new_url
    # id is stable, other fields untouched
    assert listing.price_eur == 54900
    assert listing.title == "Chevrolet Corvette C6 Grand Sport"


def test_update_listing_url_noop_when_same(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    changed = store.update_listing_url("autoscout24_123", "https://example.test/listing/123")
    assert changed is False


def test_update_listing_url_unknown_listing(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    changed = store.update_listing_url("nope", "https://example.test/x")
    assert changed is False


def test_store_migrates_missing_hidden_column(tmp_path: Path):
    """A database created before the hidden column existed still works."""
    import sqlite3

    db_path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE listings (id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, "
        "price_eur INTEGER, mileage_km INTEGER, "
        "last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()

    # Opening the store must migrate the missing column
    store = TrackerStore(db_path)
    store.upsert_listings([make_listing()])

    listing = store.get_listing("autoscout24_123")
    assert listing is not None
    assert listing.hidden is False

    # Second open is idempotent
    store2 = TrackerStore(db_path)
    assert store2.get_listing("autoscout24_123") is not None


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


def test_online_status_history_records_transitions_only(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    # First check ever -> one history row
    store.update_online_status("autoscout24_123", is_online=True, http_status=200)
    # Same status -> no new row
    store.update_online_status("autoscout24_123", is_online=True, http_status=200)
    # Transition -> new row
    store.update_online_status(
        "autoscout24_123", is_online=False, http_status=404, error_message="Gone"
    )
    # Same status -> no new row
    store.update_online_status("autoscout24_123", is_online=False, http_status=410)

    history = store.online_status_history("autoscout24_123")
    assert len(history) == 2
    assert history[0]["is_online"] == 1
    assert history[0]["http_status"] == 200
    assert history[1]["is_online"] == 0
    assert history[1]["http_status"] == 404
    # chronological ascending
    assert history[0]["captured_at"] <= history[1]["captured_at"]


def test_listing_history_collapses_unchanged_runs(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    # Re-upsert identical data 3 times -> 3 "unchanged" snapshots
    store.upsert_listings([make_listing()])
    store.upsert_listings([make_listing()])
    store.upsert_listings([make_listing()])

    # Rewrite captured_at so the ordering is deterministic
    rows = store.conn.execute(
        "SELECT id FROM snapshots WHERE listing_id = ? ORDER BY id", ("autoscout24_123",)
    ).fetchall()
    for i, row in enumerate(rows):
        store.conn.execute(
            "UPDATE snapshots SET captured_at = ? WHERE id = ?",
            (f"2026-07-{10 + i:02d} 12:00:00", row["id"]),
        )
    store.conn.commit()

    data = store.listing_history("autoscout24_123")
    # 1 "new" + 1 collapsed "unchanged" run (3 snapshots)
    assert [e["change_type"] for e in data["history"]] == ["new", "unchanged"]
    collapsed = data["history"][1]
    assert collapsed["is_collapsed"] is True
    assert collapsed["count"] == 3
    assert collapsed["captured_at"] == "2026-07-11 12:00:00"
    assert collapsed["until_at"] == "2026-07-13 12:00:00"
    # No priced snapshots -> no series
    assert data["series"] == []
    assert data["summary"]["snapshot_count"] == 4
    assert data["summary"]["first_seen_at"] == "2026-07-10 12:00:00"
    assert data["summary"]["last_seen_at"] == "2026-07-13 12:00:00"


def test_listing_history_price_series_and_summary(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing(price=54900)])
    store.upsert_listings([make_listing(price=52900)])
    store.upsert_listings([make_listing(price=53900)])
    store.upsert_listings([make_listing(price=53900)])  # no change

    rows = store.conn.execute(
        "SELECT id FROM snapshots WHERE listing_id = ? ORDER BY id", ("autoscout24_123",)
    ).fetchall()
    for i, row in enumerate(rows):
        store.conn.execute(
            "UPDATE snapshots SET captured_at = ? WHERE id = ?",
            (f"2026-07-{10 + i:02d} 12:00:00", row["id"]),
        )
    store.conn.commit()

    data = store.listing_history("autoscout24_123")
    history_types = [e["change_type"] for e in data["history"]]
    assert history_types == ["new", "price_change", "price_change", "unchanged"]
    assert data["summary"]["price_changes"] == 2
    assert data["summary"]["first_price_eur"] == 54900
    assert data["summary"]["current_price_eur"] == 53900
    assert data["summary"]["price_min_eur"] == 52900
    assert data["summary"]["price_max_eur"] == 54900
    # Series: 3 distinct price levels (54900, 52900, 53900), ascending
    assert data["series"] == [
        {"captured_at": "2026-07-10 12:00:00", "price_eur": 54900},
        {"captured_at": "2026-07-11 12:00:00", "price_eur": 52900},
        {"captured_at": "2026-07-12 12:00:00", "price_eur": 53900},
    ]


def test_update_online_status_upserts_instead_of_duplicating(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    store.update_online_status("autoscout24_123", is_online=True)
    store.update_online_status(
        "autoscout24_123", is_online=False, http_status=404, error_message="Not found"
    )

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


# ── Trim type safety ──────────────────────────────────────────────────


def test_deserialize_coerces_trim_to_enum_and_handles_invalid(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")

    valid = make_listing(id="valid-trim")
    valid.trim = "Z06"
    store.upsert_listings([valid])

    loaded = store.get_listing("valid-trim")
    assert loaded is not None
    assert loaded.trim == TrimType.Z06
    assert isinstance(loaded.trim, TrimType)

    invalid = make_listing(id="invalid-trim")
    invalid.trim = "Lamborghini"
    store.upsert_listings([invalid])

    loaded_invalid = store.get_listing("invalid-trim")
    assert loaded_invalid is not None
    assert loaded_invalid.trim is None  # no crash, invalid value becomes None


# ── Hide / Unhide ──────────────────────────────────────────────────────


def test_hide_listing_marks_as_hidden(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    store.hide_listing("autoscout24_123")

    row = store.conn.execute(
        "SELECT hidden FROM listings WHERE id = ?", ("autoscout24_123",)
    ).fetchone()
    assert row is not None
    assert row["hidden"] == 1


def test_hide_listing_gets_roundtrip_via_get_listing(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    store.hide_listing("autoscout24_123")
    listing = store.get_listing("autoscout24_123")

    assert listing is not None
    assert listing.hidden is True


def test_unhide_listing_restores_visibility(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])

    store.hide_listing("autoscout24_123")
    store.unhide_listing("autoscout24_123")

    row = store.conn.execute(
        "SELECT hidden FROM listings WHERE id = ?", ("autoscout24_123",)
    ).fetchone()
    assert row is not None
    assert row["hidden"] == 0

    listing = store.get_listing("autoscout24_123")
    assert listing is not None
    assert listing.hidden is False


def test_hidden_survives_upsert_re_scrape(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing(price=54900)])
    store.hide_listing("autoscout24_123")

    # Simulate re-scrape: upsert same listing with new price
    store.upsert_listings([make_listing(price=52900)])

    row = store.conn.execute(
        "SELECT hidden FROM listings WHERE id = ?", ("autoscout24_123",)
    ).fetchone()
    assert row is not None
    assert row["hidden"] == 1, "hidden flag must survive upsert/re-scrape"

    listing = store.get_listing("autoscout24_123")
    assert listing is not None
    assert listing.hidden is True, "hidden flag must survive payload_json round-trip"
    assert listing.price_eur == 52900


def test_hidden_listings_excluded_from_build_feed_payload_by_default(tmp_path: Path):
    from corvette_tracker.feed import build_feed_payload

    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing(id="a", price=10000)])
    store.upsert_listings([make_listing(id="b", price=20000)])
    store.hide_listing("b")

    payload = build_feed_payload(store.list_active())
    ids = [l["id"] for l in payload["listings"]]
    assert "a" in ids
    assert "b" not in ids
    assert payload["summary"]["total_active"] == 1


def test_show_hidden_includes_hidden_listings(tmp_path: Path):
    from corvette_tracker.feed import build_feed_payload

    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing(id="a", price=10000)])
    store.upsert_listings([make_listing(id="b", price=20000)])
    store.hide_listing("b")

    payload = build_feed_payload(store.list_active(), show_hidden=True)
    ids = [l["id"] for l in payload["listings"]]
    assert "a" in ids
    assert "b" in ids
    assert payload["summary"]["total_active"] == 2


# ── Upsert error reporting ──────────────────────────────────────────────


def test_upsert_error_log_includes_url_and_counts(tmp_path: Path, caplog):
    import logging

    store = TrackerStore(tmp_path / "tracker.sqlite")

    invalid = make_listing(id="invalid")
    invalid.url = "https://example.test/listing/invalid"
    invalid.price_eur = ["bad"]  # invalid type for SQLite INTEGER column

    valid = make_listing(id="valid", price=30000)

    with caplog.at_level(logging.ERROR, logger="corvette_tracker.storage"):
        results = store.upsert_listings([invalid, valid])

    assert len(results) == 1
    assert results[0].id == "valid"
    assert store.get_listing("invalid") is None
    assert store.get_listing("valid") is not None
    assert "1/2 listings failed" in caplog.text
    assert "https://example.test/listing/invalid" in caplog.text


# ── Manual cluster merges ─────────────────────────────────────────────────


def test_sticky_cluster_id_survives_upsert(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")

    first = make_listing(id="sticky-car", price=40000)
    first.cluster_id = "manual_abc123"
    store.upsert_listings([first])

    # Re-scrape with a newly computed (different) cluster_id
    second = make_listing(id="sticky-car", price=40000)
    second.cluster_id = "soft_full_xyz"
    store.upsert_listings([second])

    listing = store.get_listing("sticky-car")
    assert listing is not None
    assert listing.cluster_id == "manual_abc123"


def test_automatic_cluster_id_can_be_readopted(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")

    first = make_listing(id="readopt-car", price=40000)
    first.cluster_id = "soft_old_abc"
    store.upsert_listings([first])

    # Simulate re-listing adoption: automatic cluster changes on re-scrape
    second = make_listing(id="readopt-car", price=40000)
    second.cluster_id = "soft_new_xyz"
    store.upsert_listings([second])

    listing = store.get_listing("readopt-car")
    assert listing is not None
    assert listing.cluster_id == "soft_new_xyz"


def test_merge_listings_assigns_manual_cluster_id(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    a = make_listing(id="merge-a", price=50000)
    b = make_listing(id="merge-b", price=52000)
    store.upsert_listings([a, b])

    result = store.merge_listings(["merge-a", "merge-b"])

    assert result["group_id"].startswith("manual_")
    assert result["listing_ids"] == ["merge-a", "merge-b"]
    assert len(result["listings"]) == 2

    merged_a = store.get_listing("merge-a")
    merged_b = store.get_listing("merge-b")
    assert merged_a.cluster_id == result["group_id"]
    assert merged_b.cluster_id == result["group_id"]


def test_unmerge_listing_clears_cluster_id(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    a = make_listing(id="unmerge-a", price=50000)
    b = make_listing(id="unmerge-b", price=52000)
    store.upsert_listings([a, b])
    result = store.merge_listings(["unmerge-a", "unmerge-b"])

    updated = store.unmerge_listing("unmerge-a")

    assert updated.cluster_id is None
    assert store.get_listing("unmerge-a").cluster_id is None
    # The other listing stays in the group
    assert store.get_listing("unmerge-b").cluster_id == result["group_id"]
