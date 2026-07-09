import json
import threading
import urllib.error
import urllib.request
from dataclasses import fields
from pathlib import Path

from corvette_tracker.models import Listing
from corvette_tracker.storage import EDITABLE_FIELDS, PROTECTED_OVERRIDE_FIELDS, TrackerStore
from corvette_tracker.web import TrackerWebApp, parse_interval_seconds, render_app_shell


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


def request_json(url: str, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


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
        assert [row["change_type"] for row in payload["history"]] == ["manual_override", "new"]
        assert payload["history"][0]["price_eur"] == 52900
        assert "captured_at" in payload["history"][0]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_web_api_status_returns_persisted_last_crawl_time(tmp_path: Path):
    export_dir = tmp_path / "data" / "exports"
    export_dir.mkdir(parents=True)
    export_dir.joinpath("latest.json").write_text(json.dumps({"generated_at": "2026-07-09T12:34:56+00:00"}), encoding="utf-8")
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
        return 0, {"generated_at": "2026-07-09T13:00:00+00:00", "summary": {"total_active": 1}, "warnings": []}

    app = TrackerWebApp(store=TrackerStore(tmp_path / "tracker.sqlite"), output_dir=tmp_path, run_callback=run_callback)
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
            payload={"weights": {"manual_transmission": 45, "preferred_trim": 12}, "preferred_trims": ["Z06"]},
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

    assert "Scoring konfigurieren" in html
    assert "manual_transmission" in html
    assert "/api/scoring" in html


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
    assert "renderInlineEditor" in html
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
    assert "sorted.map(item => renderOverviewCard(item))" in html


def test_web_shell_shows_score_badge_on_overview_preview_image():
    html = render_app_shell()

    assert "score-badge" in html
    assert '<span class="score-badge">${esc(item.score ?? 0)}%</span>' in html
    assert html.index('<span class="score-badge">${esc(item.score ?? 0)}%</span>') > html.index('<a class="image"')
    assert html.index('<span class="score-badge">${esc(item.score ?? 0)}%</span>') < html.index('${image ? `<img')


def test_web_api_returns_404_for_missing_listing(tmp_path: Path):
    app = TrackerWebApp(store=TrackerStore(tmp_path / "tracker.sqlite"), output_dir=tmp_path)
    server = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            request_json(f"{base_url}/api/listings/missing", method="PATCH", payload={"engine": "LS3"})
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("missing listing should return 404")
    finally:
        server.shutdown()
        thread.join(timeout=5)
