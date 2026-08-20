import base64
import json
import threading
import urllib.error
import urllib.request
from dataclasses import fields
from pathlib import Path

import pytest

from corvette_tracker.models import Listing
from corvette_tracker.storage import EDITABLE_FIELDS, PROTECTED_OVERRIDE_FIELDS, TrackerStore
from corvette_tracker.web import TrackerWebApp, parse_interval_seconds, render_app_shell

TEST_ADMIN_USER = "test-admin"
TEST_ADMIN_PASSWORD = "test-password"


@pytest.fixture(autouse=True)
def web_auth_env(monkeypatch):
    monkeypatch.setenv("CORVETTE_TRACKER_ADMIN_USER", TEST_ADMIN_USER)
    monkeypatch.setenv("CORVETTE_TRACKER_ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)


def make_listing():
    return Listing(
        id="autoscout24_123",
        source="AutoScout24",
        source_listing_id="123",
        url="https://example.test/listing/123",
        title="Chevrolet Corvette C6",
        generation="C6",
        price_eur=54900,
        mileage_km=68000,
        score=80,
    )


def request_json(url: str, method="GET", payload=None, auth=True):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth:
        credentials = f"{TEST_ADMIN_USER}:{TEST_ADMIN_PASSWORD}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def request_error(url: str, method="GET", payload=None, auth=True):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth:
        credentials = f"{TEST_ADMIN_USER}:{TEST_ADMIN_PASSWORD}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return (
                response.status,
                dict(response.headers),
                json.loads(response.read().decode("utf-8")),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = body
        return exc.code, dict(exc.headers), payload


def test_parse_interval_seconds_accepts_docker_env_values():
    assert parse_interval_seconds("300") == 300
    assert parse_interval_seconds("15m") == 900
    assert parse_interval_seconds("2h") == 7200
    assert parse_interval_seconds("never") is None


def test_web_api_lists_and_patches_manual_fields(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = request_json(f"{base_url}/api/listings")
        assert status == 200
        assert payload["listings"][0]["id"] == "autoscout24_123"

        status, updated = request_json(
            f"{base_url}/api/listings/autoscout24_123",
            method="PATCH",
            payload={"engine": "LS3", "transmission": "manual"},
        )
        assert status == 200
        assert updated["listing"]["engine"] == "LS3"
        assert updated["listing"]["transmission"] == "manual"
        assert store.list_active()[0].engine == "LS3"
        assert (tmp_path / "site" / "index.html").exists()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_api_returns_listing_history(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    store.update_overrides("autoscout24_123", {"price_eur": 52900})
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = request_json(f"{base_url}/api/listings/autoscout24_123/history")

        assert status == 200
        assert payload["listing_id"] == "autoscout24_123"
        # ASC order: new first, then manual_override
        assert [row["change_type"] for row in payload["history"]] == ["new", "manual_override"]
        assert payload["history"][1]["price_eur"] == 52900
        assert "captured_at" in payload["history"][0]
        assert "summary" in payload
        assert "series" in payload
        assert "online_history" in payload
        assert payload["summary"]["snapshot_count"] == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_api_status_returns_persisted_last_crawl_time(tmp_path: Path):
    export_dir = tmp_path / "data" / "exports"
    export_dir.mkdir(parents=True)
    export_dir.joinpath("latest.json").write_text(
        json.dumps({"generated_at": "2026-07-09T12:34:56+00:00"}), encoding="utf-8"
    )
    app = TrackerWebApp(store=TrackerStore(tmp_path / "tracker.sqlite"), output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = request_json(f"{base_url}/api/status")

        assert status == 200
        assert payload["last_crawl_at"] == "2026-07-09T12:34:56+00:00"
        assert payload["last_run"]["generated_at"] == "2026-07-09T12:34:56+00:00"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_api_run_response_includes_last_crawl_time(tmp_path: Path):
    def run_callback():
        return 0, {
            "generated_at": "2026-07-09T13:00:00+00:00",
            "summary": {"total_active": 1},
            "warnings": [],
        }

    app = TrackerWebApp(
        store=TrackerStore(tmp_path / "tracker.sqlite"),
        output_dir=tmp_path,
        run_callback=run_callback,
    )
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = request_json(f"{base_url}/api/run", method="POST")

        assert status == 200
        assert payload["last_crawl_at"] == "2026-07-09T13:00:00+00:00"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_api_reads_and_updates_scoring_config(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("scoring:\n  weights:\n    manual_transmission: 30\n", encoding="utf-8")
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path, config_path=config_file)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = request_json(f"{base_url}/api/scoring")
        assert status == 200
        assert payload["scoring"]["weights"]["manual_transmission"] == 30

        status, updated = request_json(
            f"{base_url}/api/scoring",
            method="PATCH",
            payload={
                "weights": {"manual_transmission": 45, "preferred_trim": 12},
                "preferred_trims": ["Z06"],
            },
        )

        assert status == 200
        assert updated["scoring"]["weights"]["manual_transmission"] == 45
        saved = config_file.read_text(encoding="utf-8")
        assert "manual_transmission: 45" in saved
        assert "preferred_trim: 12" in saved
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_shell_contains_scoring_configuration_form():
    html = render_app_shell()

    assert "Scoring" not in html
    assert "/api/scoring" not in html


def test_web_shell_always_shows_last_crawl_status():
    html = render_app_shell()

    assert "Letzter Crawl" in html
    assert "last-crawl" in html
    assert "/api/status" in html
    assert "updateLastCrawl" in html


def test_web_shell_can_sort_listings_by_score():
    html = render_app_shell()

    assert "listing-sort" in html
    assert "score-desc" in html
    assert "Score hoch" in html
    assert "score-asc" in html
    assert "Score niedrig" in html
    assert "sortListings" in html


def test_web_shell_exposes_all_listing_fields_and_inline_editors():
    html = render_app_shell()

    assert "data-field-registry" in html
    assert "renderAllFields" in html
    assert "inlineEditorValue" in html
    assert "renderDetailPage" in html
    assert "renderOverviewCard" in html
    assert "Verlauf" in html
    assert "/api/listings/" in html
    assert "/history" in html
    for field in fields(Listing):
        assert f'"{field.name}"' in html
    for field_name in EDITABLE_FIELDS:
        assert f'"{field_name}"' in html
    for field_name in PROTECTED_OVERRIDE_FIELDS:
        assert f'"{field_name}"' in html


def test_web_shell_overview_links_directly_to_original_offer_and_keeps_detail_editing():
    html = render_app_shell()

    assert "data-overview-card" in html
    assert "const offerUrl = item.url || detailUrl" in html
    assert 'href="${esc(offerUrl)}" target="_blank" rel="noreferrer"' in html
    assert "Angebot öffnen" in html
    assert "Details bearbeiten" in html
    assert "openDetail(event" in html
    assert "car/" in html
    assert "overview-specs" in html
    assert "sortedPrimaries.map" in html
    assert "renderOverviewCard(item, group)" in html
    assert "offer-badge" in html


def test_web_shell_shows_score_badge_on_overview_preview_image():
    html = render_app_shell()

    assert "score-badge" in html
    assert '<span class="score-badge">${badgeScore}</span>' in html
    assert html.index('<span class="score-badge">${badgeScore}</span>') > html.index(
        '<a class="image"'
    )
    assert html.index('<span class="score-badge">${badgeScore}</span>') < html.index(
        "${image ? `<img"
    )


def test_web_shell_contains_priorities_picker():
    html = render_app_shell()

    assert "Meine Prioritäten" in html
    assert "priorities-panel" in html
    assert "corvette_priorities_v1" in html
    assert "priority-weightbar" in html
    assert "priorities-reset" in html
    # Typ-A-Slider (Wichtigkeit 0-5) mit Default 3
    for key in ("price_eur", "mileage_km", "model_year", "accident", "eu_spec", "power_hp"):
        assert f'data-priority-key="{key}"' in html
        assert 'data-priority-type="a" min="0" max="5" step="1" value="3"' in html
    # Typ-B-Slider (Richtung -1/0/+1) mit Default 0
    for key in ("transmission", "body_style"):
        assert f'data-priority-key="{key}"' in html
        assert 'data-priority-type="b" data-left-label=' in html
        assert "data-right-label=" in html
        assert 'min="-1" max="1" step="1" value="0"' in html
    assert "Nicht wichtig" in html
    assert "Kritisch" in html
    assert "Schalter" in html
    assert "Automatik" in html
    assert "Coupé" in html
    assert "Cabrio" in html
    assert "weniger PS" in html
    assert "mehr PS" in html
    assert 'data-priority-dir="power_hp"' in html
    # Persönlicher Score: JS-Berechnung, Badge, Sortieroptionen
    assert "computeMyScores" in html
    assert "myScoreFor" in html
    assert "typeBPoints" in html
    assert '<span class="score-badge">${badgeScore}</span>' in html
    assert "mine-badge" not in html
    assert "Mein Score hoch" not in html
    assert "mein-score-desc" not in html


def test_web_shell_lazy_loading_images():
    html = render_app_shell()

    assert "data-lazy-src" in html
    assert 'loading="lazy"' in html
    assert "IntersectionObserver" in html
    assert "rootMargin: '300px 0px'" in html
    assert "unobserve" in html
    assert "if (!('IntersectionObserver' in window))" in html
    assert "loadLazyImages" in html
    assert "loadLazyImages()" in html
    assert "renderOverviewCard" in html
    assert html.rindex("loadLazyImages()") > html.index("grid.innerHTML = sortedPrimaries.map")


def test_web_api_returns_404_for_missing_listing(tmp_path: Path):
    app = TrackerWebApp(store=TrackerStore(tmp_path / "tracker.sqlite"), output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            request_json(
                f"{base_url}/api/listings/missing", method="PATCH", payload={"engine": "LS3"}
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("missing listing should return 404")
    finally:
        server.shutdown()
        thread.join(timeout=5)


# --- API filter integration tests ---


def _make_api_listing(
    id,
    source="Kleinanzeigen",
    transmission="manual",
    trim="Z06",
    engine="LS7",
    body_style="Coupé",
    price=35000,
    mileage=50000,
    change_type="new",
    score=70,
    risk_flags=None,
):
    return Listing(
        id=id,
        source=source,
        source_listing_id=id,
        url=f"https://example.test/{id}",
        title=f"Corvette C6 {trim}",
        generation="C6",
        transmission=transmission,
        trim=trim,
        engine=engine,
        body_style=body_style,
        price_eur=price,
        mileage_km=mileage,
        score=score,
        change_type=change_type,
        risk_flags=risk_flags or [],
    )


DIVERSE_LISTINGS = [
    _make_api_listing(
        "a",
        source="Kleinanzeigen",
        transmission="manual",
        trim="Z06",
        engine="LS7",
        body_style="Coupé",
        price=35000,
        mileage=50000,
        score=70,
    ),
    _make_api_listing(
        "b",
        source="AutoScout24",
        transmission="automatic",
        trim="Base",
        engine="LS2",
        body_style="Cabrio",
        price=25000,
        mileage=100000,
        score=35,
    ),
    _make_api_listing(
        "c",
        source="AutoUncle",
        transmission="manual",
        trim="Grand Sport",
        engine="LS3",
        body_style="Targa",
        price=45000,
        mileage=30000,
        score=85,
    ),
    _make_api_listing(
        "d",
        source="Kleinanzeigen",
        transmission="manual",
        trim="Z06",
        engine="LS7",
        body_style="Coupé",
        price=38000,
        mileage=45000,
        score=72,
        change_type="price_change",
    ),
    _make_api_listing(
        "e",
        source="Kleinanzeigen",
        transmission="automatic",
        trim="Base",
        engine="LS2",
        body_style="Cabrio",
        price=18000,
        mileage=120000,
        score=40,
        risk_flags=["damage_reported"],
    ),
]


def _make_filtered_request(base_url, query_string):
    url = f"{base_url}/api/listings"
    if query_string:
        url += "?" + query_string
    status, payload = request_json(url)
    return status, payload


def test_api_filter_no_params_returns_all(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings(DIVERSE_LISTINGS)
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _make_filtered_request(base_url, "")
        assert status == 200
        assert len(payload["listings"]) == 5
        assert payload["total"] == 5
        assert payload["total_all"] == 5
        ids = {l["id"] for l in payload["listings"]}
        assert ids == {"a", "b", "c", "d", "e"}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_api_filter_by_source(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings(DIVERSE_LISTINGS)
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _make_filtered_request(base_url, "source=Kleinanzeigen")
        assert status == 200
        ids = {l["id"] for l in payload["listings"]}
        assert ids == {"a", "d", "e"}
        assert payload["total"] == 3
        assert payload["total_all"] == 5
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_api_filter_by_transmission(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings(DIVERSE_LISTINGS)
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _make_filtered_request(base_url, "transmission=manual")
        assert status == 200
        ids = {l["id"] for l in payload["listings"]}
        assert ids == {"a", "c", "d"}
        assert payload["total"] == 3
        assert all(l["transmission"] == "manual" for l in payload["listings"])
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_api_filter_combined(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings(DIVERSE_LISTINGS)
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        qs = "source=Kleinanzeigen&transmission=manual&body_style=Coup%C3%A9&score_min=50&price_min=35000"
        status, payload = _make_filtered_request(base_url, qs)
        assert status == 200
        ids = {l["id"] for l in payload["listings"]}
        assert ids == {"a", "d"}
        assert payload["total"] == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_api_filter_risk_free(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings(DIVERSE_LISTINGS)
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _make_filtered_request(base_url, "risk_free=true")
        assert status == 200
        ids = {l["id"] for l in payload["listings"]}
        assert "e" not in ids
        assert payload["total"] == 4
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_api_filter_price_range(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings(DIVERSE_LISTINGS)
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _make_filtered_request(base_url, "price_min=30000&price_max=40000")
        assert status == 200
        ids = {l["id"] for l in payload["listings"]}
        assert ids == {"a", "d"}
        assert payload["total"] == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_api_filter_no_match_returns_empty(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings(DIVERSE_LISTINGS)
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _make_filtered_request(base_url, "source=Mobile.de")
        assert status == 200
        assert payload["listings"] == []
        assert payload["total"] == 0
        assert payload["total_all"] == 5
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_api_merge_listings_returns_manual_group_id(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    listing1 = make_listing()
    listing2 = Listing(
        id="autoscout24_456",
        source="AutoScout24",
        source_listing_id="456",
        url="https://example.test/listing/456",
        title="Chevrolet Corvette C6",
        generation="C6",
        price_eur=50000,
        mileage_km=30000,
        score=75,
    )
    store.upsert_listings([listing1, listing2])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = request_json(
            f"{base_url}/api/merge",
            method="POST",
            payload={"listing_ids": ["autoscout24_123", "autoscout24_456"]},
        )
        assert status == 200
        assert payload["group_id"].startswith("manual_")
        assert payload["listing_ids"] == ["autoscout24_123", "autoscout24_456"]
        assert len(payload["listings"]) == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_api_merge_with_unknown_listing_returns_404(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            request_json(
                f"{base_url}/api/merge",
                method="POST",
                payload={"listing_ids": ["missing-id", "autoscout24_123"]},
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("merge with unknown listing should return 404")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_api_merge_with_single_listing_returns_400(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            request_json(
                f"{base_url}/api/merge",
                method="POST",
                payload={"listing_ids": ["autoscout24_123"]},
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("merge with single listing should return 400")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_api_unmerge_returns_listing_without_cluster(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    listing1 = make_listing()
    listing2 = Listing(
        id="autoscout24_456",
        source="AutoScout24",
        source_listing_id="456",
        url="https://example.test/listing/456",
        title="Chevrolet Corvette C6",
        generation="C6",
        price_eur=50000,
        mileage_km=30000,
        score=75,
    )
    store.upsert_listings([listing1, listing2])
    store.merge_listings(["autoscout24_123", "autoscout24_456"])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = request_json(
            f"{base_url}/api/unmerge",
            method="POST",
            payload={"listing_id": "autoscout24_123"},
        )
        assert status == 200
        assert payload["listing"]["id"] == "autoscout24_123"
        assert payload["listing"]["cluster_id"] is None
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_patch_invalid_date_rejected(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            request_json(
                f"{base_url}/api/listings/autoscout24_123",
                method="PATCH",
                payload={"first_registration": "2010/06"},
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            assert "Format JJJJ-MM" in exc.read().decode("utf-8")
        else:
            raise AssertionError("invalid date should return 400")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_patch_invalid_model_year_rejected(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            request_json(
                f"{base_url}/api/listings/autoscout24_123",
                method="PATCH",
                payload={"model_year": 1999},
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("invalid model_year should return 400")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_patch_protected_field_rejected(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            request_json(
                f"{base_url}/api/listings/autoscout24_123",
                method="PATCH",
                payload={"score": 99},
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            assert "Unsupported override" in exc.read().decode("utf-8")
        else:
            raise AssertionError("protected field should return 400")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_post_run_without_credentials_returns_503(tmp_path, monkeypatch):
    monkeypatch.delenv("CORVETTE_TRACKER_ADMIN_USER", raising=False)
    monkeypatch.delenv("CORVETTE_TRACKER_ADMIN_PASSWORD", raising=False)
    app = TrackerWebApp(store=TrackerStore(tmp_path / "tracker.sqlite"), output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, _, payload = request_error(f"{base_url}/api/run", method="POST", auth=False)
        assert status == 503
        assert payload["error"] == "mutating API authentication is not configured"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_patch_without_auth_returns_401(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, headers, _ = request_error(
            f"{base_url}/api/listings/autoscout24_123",
            method="PATCH",
            payload={"engine": "LS3"},
            auth=False,
        )
        assert status == 401
        assert "Basic" in headers.get("WWW-Authenticate", "")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_get_listings_without_auth_works(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = request_json(f"{base_url}/api/listings", auth=False)
        assert status == 200
        assert payload["listings"][0]["id"] == "autoscout24_123"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_patch_with_auth_succeeds(tmp_path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    store.upsert_listings([make_listing()])
    app = TrackerWebApp(store=store, output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, updated = request_json(
            f"{base_url}/api/listings/autoscout24_123",
            method="PATCH",
            payload={"engine": "LS3"},
            auth=True,
        )
        assert status == 200
        assert updated["listing"]["engine"] == "LS3"
    finally:
        server.shutdown()
        thread.join(timeout=5)
