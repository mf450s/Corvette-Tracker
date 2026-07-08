import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from corvette_tracker.models import Listing
from corvette_tracker.storage import TrackerStore
from corvette_tracker.web import TrackerWebApp, parse_interval_seconds


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
