from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from corvette_tracker.health import (
    CACHE_TTL_SECONDS,
    _check_single_url,
    check_stale_offers,
    get_cached_status,
)
from corvette_tracker.models import Listing
from corvette_tracker.storage import TrackerStore


def make_listing(id="autoscout24_123", url="https://example.test/listing/123"):
    return Listing(
        id=id,
        source="AutoScout24",
        source_listing_id="123",
        url=url,
        title="Chevrolet Corvette C6 Grand Sport",
        generation="C6",
        price_eur=54900,
        mileage_km=68000,
        location_raw="Hamburg",
        trim="Grand Sport",
        engine="LS3",
        score=80,
    )


# --- Helper: local test server ---


class _TestHandler(BaseHTTPRequestHandler):
    """Simple handler that serves configurable responses based on request path."""
    _responses: dict[str, tuple[int, str]] = {}

    @classmethod
    def set_response(cls, path: str, status: int, body: str = "OK") -> None:
        cls._responses[path] = (status, body)

    def do_HEAD(self) -> None:
        self._respond()

    def do_GET(self) -> None:
        self._respond()

    def _respond(self) -> None:
        status, body = self._responses.get(self.path, (404, "Not Found"))
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body_bytes)

    def log_message(self, format, *args) -> None:
        pass  # suppress log output during tests


def serve(handler_cls=BaseHTTPRequestHandler):
    """Start a local HTTP server and return (server, base_url)."""
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, base_url


def make_handler(*, responses: dict[str, tuple[int, str]] | None = None):
    """Create a handler class with preset responses for test requests."""
    class CustomHandler(BaseHTTPRequestHandler):
        _responses = responses or {}

        def do_HEAD(self):
            self._respond()

        def do_GET(self):
            self._respond()

        def _respond(self):
            status, body = self._responses.get(self.path, (404, "Not Found"))
            body_bytes = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body_bytes)

        def log_message(self, format, *args):
            pass

    return CustomHandler


# --- _check_single_url unit tests ---


def test_check_single_url_returns_response_on_reachable():
    handler_cls = make_handler(responses={"/test": (200, "OK")})
    server, base_url = serve(handler_cls)
    try:
        status, error = _check_single_url(f"{base_url}/test")
        assert status == 200
        assert error is None
    finally:
        server.shutdown()


def test_check_single_url_reports_non_2xx():
    handler_cls = make_handler(responses={"/gone": (410, "Gone")})
    server, base_url = serve(handler_cls)
    try:
        status, error = _check_single_url(f"{base_url}/gone")
        assert status == 410
        assert error is None
    finally:
        server.shutdown()


def test_check_single_url_reports_empty_url():
    status, error = _check_single_url("")
    assert status is None
    assert error == "empty URL"


def test_check_single_url_connection_error():
    """Unreachable address yields an error message."""
    status, error = _check_single_url("http://127.0.0.1:1/nope")
    assert status is None
    assert error is not None


# --- check_stale_offers tests ---


def test_check_stale_offers_checks_unchecked_listings(tmp_path: Path):
    handler_cls = make_handler(responses={"/list/1": (200, "OK")})
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/list/1")])

        summary = check_stale_offers(store, force=True)

        assert summary["checked"] == 1
        assert summary["online"] == 1
        assert summary["offline"] == 0
        assert summary["total"] == 1

        cached = store.get_online_status("autoscout24_123")
        assert cached is not None
        assert cached["is_online"] == 1
        assert cached["http_status"] == 200
    finally:
        server.shutdown()


def test_check_stale_offers_reports_offline(tmp_path: Path):
    handler_cls = make_handler(responses={"/gone": (404, "Gone")})
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/gone")])

        summary = check_stale_offers(store, force=True)

        assert summary["checked"] == 1
        assert summary["online"] == 0
        assert summary["offline"] == 1
        assert summary["failed"] == 0

        cached = store.get_online_status("autoscout24_123")
        assert cached is not None
        assert cached["is_online"] == 0
        assert cached["http_status"] == 404
    finally:
        server.shutdown()


def test_check_stale_offers_skips_fresh_entries(tmp_path: Path):
    handler_cls = make_handler(responses={"/fresh": (200, "OK")})
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/fresh")])

        # First check populates cache
        check_stale_offers(store, force=True)

        # Second check without force should skip
        summary = check_stale_offers(store)
        assert summary["checked"] == 0
        assert summary["skipped"] == 1
    finally:
        server.shutdown()


def test_check_stale_offers_force_refresh(tmp_path: Path):
    handler_cls = make_handler(responses={"/force-test": (200, "OK")})
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/force-test")])

        # First check
        check_stale_offers(store, force=True)

        # Force refresh should re-check
        summary = check_stale_offers(store, force=True)
        assert summary["checked"] == 1
        assert summary["skipped"] == 0
    finally:
        server.shutdown()


# --- get_cached_status tests ---


def test_get_cached_status_returns_empty_for_empty_store(tmp_path: Path):
    store = TrackerStore(tmp_path / "tracker.sqlite")
    result = get_cached_status(store)
    assert result["total"] == 0
    assert result["offers"] == []


def test_get_cached_status_includes_listings_without_status(tmp_path: Path):
    handler_cls = make_handler(responses={"/ok": (200, "OK")})
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/ok")])

        result = get_cached_status(store)
        assert result["total"] == 1
        assert result["offers"][0]["is_online"] is True
        assert result["offers"][0]["last_checked_at"] is None
    finally:
        server.shutdown()


def test_get_cached_status_shows_cached_values(tmp_path: Path):
    handler_cls = make_handler(responses={"/cached": (200, "OK")})
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/cached")])

        check_stale_offers(store, force=True)

        result = get_cached_status(store)
        assert result["total"] == 1
        assert result["offers"][0]["is_online"] is True
        assert result["offers"][0]["http_status"] == 200
        assert result["offers"][0]["last_checked_at"] is not None
        assert result["cache_remaining_seconds"] > 0
        assert result["cache_remaining_seconds"] <= CACHE_TTL_SECONDS
    finally:
        server.shutdown()


# --- Integration test with web API ---


def test_web_offers_status_endpoint(tmp_path: Path):
    """GET /api/offers/status should return JSON with offer status data."""
    from corvette_tracker.web import TrackerWebApp
    import urllib.request

    handler_cls = make_handler(responses={"/integrate": (200, "OK")})
    api_server, api_base = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{api_base}/integrate")])

        app = TrackerWebApp(store=store, output_dir=tmp_path)
        web_server = app.make_server("127.0.0.1", 0)
        thread = threading.Thread(target=web_server.serve_forever, daemon=True)
        thread.start()
        web_base = f"http://127.0.0.1:{web_server.server_address[1]}"

        try:
            req = urllib.request.Request(f"{web_base}/api/offers/status")
            with urllib.request.urlopen(req, timeout=5) as response:
                assert response.status == 200
                payload = json.loads(response.read().decode("utf-8"))

            assert payload["total"] == 1
            assert payload["offers"][0]["listing_id"] == "autoscout24_123"
            assert payload["offers"][0]["url"] == f"{api_base}/integrate"
            assert payload["cache_ttl_seconds"] == CACHE_TTL_SECONDS
        finally:
            web_server.shutdown()
            thread.join(timeout=5)
    finally:
        api_server.shutdown()


def test_web_offers_check_endpoint(tmp_path: Path):
    """POST /api/offers/check should trigger a health check and return summary."""
    from corvette_tracker.web import TrackerWebApp
    import urllib.request

    handler_cls = make_handler(responses={"/check-me": (200, "OK")})
    api_server, api_base = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{api_base}/check-me")])

        app = TrackerWebApp(store=store, output_dir=tmp_path)
        web_server = app.make_server("127.0.0.1", 0)
        thread = threading.Thread(target=web_server.serve_forever, daemon=True)
        thread.start()
        web_base = f"http://127.0.0.1:{web_server.server_address[1]}"

        try:
            data = json.dumps({}).encode("utf-8")
            req = urllib.request.Request(
                f"{web_base}/api/offers/check",
                data=data,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                assert response.status == 200
                payload = json.loads(response.read().decode("utf-8"))

            assert payload["checked"] == 1
            assert payload["online"] == 1
            assert payload["offline"] == 0
        finally:
            web_server.shutdown()
            thread.join(timeout=5)
    finally:
        api_server.shutdown()

