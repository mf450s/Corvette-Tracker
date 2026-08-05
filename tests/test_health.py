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


# --- Redirect detection tests ---


class _RedirectHandler(BaseHTTPRequestHandler):
    """Handler that redirects /old -> /new with 302."""
    _redirects: dict[str, tuple[int, str]] = {}

    @classmethod
    def set_redirect(cls, path: str, target_path: str) -> None:
        cls._redirects[path] = (302, target_path)

    def do_HEAD(self) -> None:
        self._respond()

    def do_GET(self) -> None:
        self._respond()

    def _respond(self) -> None:
        if self.path in self._redirects:
            code, target = self._redirects[self.path]
            self.send_response(code)
            self.send_header("Location", target)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args) -> None:
        pass


def make_redirect_handler(*, redirects: dict[str, str] | None = None):
    """Create a handler that returns redirect responses for specific paths."""
    normalized = {}
    for path, target in (redirects or {}).items():
        normalized[path] = target

    class CustomHandler(BaseHTTPRequestHandler):
        _redirects = normalized

        def do_HEAD(self):
            self._respond()

        def do_GET(self):
            self._respond()

        def _respond(self):
            if self.path in self._redirects:
                code = 302
                target = self._redirects[self.path]
                self.send_response(code)
                self.send_header("Location", target)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(b"OK")

        def log_message(self, format, *args):
            pass

    return CustomHandler


def test_check_single_url_redirect_is_offline():
    """A redirect (302) should be reported as offline (non-2xx status)."""
    handler_cls = make_redirect_handler(redirects={"/old": "/new"})
    server, base_url = serve(handler_cls)
    try:
        status, error = _check_single_url(f"{base_url}/old")
        # Should get 302, not 200 (redirect NOT followed)
        assert status == 302
        assert error is None
    finally:
        server.shutdown()


def test_check_single_url_redirect_not_followed():
    """Ensure that a redirect is NOT followed to the final 200."""
    handler_cls = make_redirect_handler(redirects={"/gone": "/homepage"})
    server, base_url = serve(handler_cls)
    try:
        status, error = _check_single_url(f"{base_url}/gone")
        # Must not follow redirect to /homepage — status must be 302
        assert status == 302
        assert 300 <= status < 400
    finally:
        server.shutdown()


# --- Canonical (same-listing) redirect tests ---


def test_check_single_url_canonical_redirect_is_online():
    """A redirect that preserves the listing identity (e.g. AutoScout24 URL
    rewrite) is a canonicalization — the offer is still online."""
    guid = "e65b455d-a2cc-4bb9-adbd-77189c0a0dc4"
    handler_cls = make_redirect_handler(redirects={
        f"/angebote/corvette-zr1-old-{guid}": f"/angebote/corvette-zr1-new-{guid}",
    })
    server, base_url = serve(handler_cls)
    try:
        status, error = _check_single_url(
            f"{base_url}/angebote/corvette-zr1-old-{guid}"
        )
        assert status == 200
        assert error is None
    finally:
        server.shutdown()


def test_check_single_url_redirect_to_homepage_still_offline():
    """A redirect to a page without the listing identity stays offline."""
    guid = "e65b455d-a2cc-4bb9-adbd-77189c0a0dc4"
    handler_cls = make_redirect_handler(redirects={
        f"/offer-{guid}": "/homepage",
    })
    server, base_url = serve(handler_cls)
    try:
        status, error = _check_single_url(f"{base_url}/offer-{guid}")
        assert status == 302
        assert 300 <= status < 400
    finally:
        server.shutdown()


def test_check_stale_offers_canonical_redirect_updates_url(tmp_path: Path):
    """A canonical redirect keeps the listing online and adopts the new URL."""
    guid = "e65b455d-a2cc-4bb9-adbd-77189c0a0dc4"
    handler_cls = make_redirect_handler(redirects={
        f"/old/offer-{guid}": f"/new/offer-{guid}",
    })
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/old/offer-{guid}")])

        summary = check_stale_offers(store, force=True)
        assert summary["online"] == 1
        assert summary["offline"] == 0

        cached = store.get_online_status("autoscout24_123")
        assert cached is not None
        assert cached["is_online"] == 1
        assert cached["http_status"] == 200

        updated = store.get_listing("autoscout24_123")
        assert updated is not None
        assert updated.url == f"{base_url}/new/offer-{guid}"
    finally:
        server.shutdown()


# --- Content-based not-found detection ---


def make_body_handler(*, responses: dict[str, tuple[int, str]]):
    """Handler with custom response bodies for content-check tests."""

    class CustomHandler(BaseHTTPRequestHandler):
        _responses = responses or {}

        def do_HEAD(self):
            # HEAD has no body — respond with same status but empty body
            self._respond()

        def do_GET(self):
            self._respond()

        def _respond(self):
            status, body = self._responses.get(self.path, (200, ""))
            body_bytes = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body_bytes)

        def log_message(self, format, *args):
            pass

    return CustomHandler


def test_check_single_url_not_found_body():
    """A 200 response with 'Anzeige nicht gefunden' should be treated as offline."""
    handler_cls = make_body_handler(responses={
        "/gone-listing": (200, "<html><body>Die Anzeige wurde leider nicht gefunden.</body></html>"),
    })
    server, base_url = serve(handler_cls)
    try:
        # HEAD returns 200 (no body check), then GET returns 200 but body says not found
        status, error = _check_single_url(f"{base_url}/gone-listing")
        # Should report 410 (our synthetic 'Gone' status) with error
        assert status == 410
        assert error == "not found body"
    finally:
        server.shutdown()


def test_check_single_url_real_content_not_offline():
    """A real 200 response without not-found phrases should be online."""
    handler_cls = make_body_handler(responses={
        "/real-listing": (200, "<html><body>Chevrolet Corvette C6 Grand Sport, 54.900 €</body></html>"),
    })
    server, base_url = serve(handler_cls)
    try:
        status, error = _check_single_url(f"{base_url}/real-listing")
        assert status == 200
        assert error is None
    finally:
        server.shutdown()


def test_check_stale_offers_redirect_marked_offline(tmp_path: Path):
    """A redirecting listing should be marked offline by check_stale_offers."""
    handler_cls = make_redirect_handler(redirects={"/offer/1": "/homepage"})
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/offer/1")])

        summary = check_stale_offers(store, force=True)

        assert summary["checked"] == 1
        assert summary["online"] == 0
        assert summary["offline"] == 1
        assert summary["failed"] == 0

        cached = store.get_online_status("autoscout24_123")
        assert cached is not None
        assert cached["is_online"] == 0
        assert cached["http_status"] == 302
    finally:
        server.shutdown()


def test_check_stale_offers_content_not_found_offline(tmp_path: Path):
    """A listing returning 200 with 'not found' body should be marked offline."""
    handler_cls = make_body_handler(responses={
        "/offer": (200, "<html><body>Anzeige nicht gefunden</body></html>"),
    })
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/offer")])

        summary = check_stale_offers(store, force=True)

        assert summary["checked"] == 1
        assert summary["online"] == 0
        assert summary["offline"] == 1

        cached = store.get_online_status("autoscout24_123")
        assert cached is not None
        assert cached["is_online"] == 0
        assert cached["http_status"] == 410
    finally:
        server.shutdown()


# --- Already-offline and dry-run tests ---


def test_check_stale_offers_offline_stays_offline_on_recheck(tmp_path: Path):
    """An already-offline listing re-checked (still offline) stays offline."""
    handler = make_handler(responses={
        "/still-gone": (404, "Gone"),
    })
    server, base_url = serve(handler)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/still-gone")])

        # First check: mark offline
        summary1 = check_stale_offers(store, force=True)
        assert summary1["offline"] == 1

        cached1 = store.get_online_status("autoscout24_123")
        assert cached1 is not None
        assert cached1["is_online"] == 0

        # Second check (force re-check): still offline, status unchanged
        summary2 = check_stale_offers(store, force=True)
        assert summary2["offline"] == 1
        assert summary2["online"] == 0

        cached2 = store.get_online_status("autoscout24_123")
        assert cached2 is not None
        assert cached2["is_online"] == 0  # still offline
        assert cached2["http_status"] == 404
    finally:
        server.shutdown()


def test_check_stale_offers_already_offline_no_change_without_check(tmp_path: Path):
    """An already-offline listing that hasn't been re-checked should persist as
    offline in the DB — the cache keeps the previous result."""
    handler = make_handler(responses={
        "/was-offline": (404, "Gone"),
    })
    server, base_url = serve(handler)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/was-offline")])

        # Mark offline
        check_stale_offers(store, force=True)

        # Non-forced check should skip (cache is fresh) — offline status persists
        summary = check_stale_offers(store)
        assert summary["checked"] == 0
        assert summary["skipped"] == 1
        assert summary["offline"] == 1  # counted from cached entry

        cached = store.get_online_status("autoscout24_123")
        assert cached is not None
        assert cached["is_online"] == 0
    finally:
        server.shutdown()


def test_check_stale_offers_dry_run_does_not_write(tmp_path: Path):
    """dry_run=True checks URLs but does NOT update the database."""
    handler = make_handler(responses={
        "/dry": (404, "Gone"),
    })
    server, base_url = serve(handler)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/dry")])

        # Pre-condition: no status record exists
        cached_before = store.get_online_status("autoscout24_123")
        assert cached_before is None

        # Dry run — URL checked, DB NOT written
        summary = check_stale_offers(store, force=True, dry_run=True)

        assert summary["checked"] == 1
        assert summary["offline"] == 1  # 404 detected
        assert summary["dry_run"] is True

        # DB should still have no status record
        cached_after = store.get_online_status("autoscout24_123")
        assert cached_after is None
    finally:
        server.shutdown()


def test_check_stale_offers_dry_run_returns_results(tmp_path: Path):
    """dry_run=True still returns result details without writing."""
    handler = make_handler(responses={
        "/dry2": (200, "OK"),
    })
    server, base_url = serve(handler)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([make_listing(url=f"{base_url}/dry2")])

        summary = check_stale_offers(store, force=True, dry_run=True)

        assert summary["checked"] == 1
        assert summary["online"] == 1
        assert summary["dry_run"] is True
        assert len(summary["results"]) == 1
        assert summary["results"][0]["is_online"] is True
        assert summary["results"][0]["http_status"] == 200
    finally:
        server.shutdown()


def test_check_stale_offers_dry_run_mixed_results(tmp_path: Path):
    """dry_run=True with both online and offline listings."""
    handler_cls = make_handler(responses={
        "/online": (200, "OK"),
        "/offline": (404, "Gone"),
    })
    server, base_url = serve(handler_cls)
    try:
        store = TrackerStore(tmp_path / "tracker.sqlite")
        store.upsert_listings([
            make_listing(id="listing_a", url=f"{base_url}/online"),
            make_listing(id="listing_b", url=f"{base_url}/offline"),
        ])

        summary = check_stale_offers(store, force=True, dry_run=True)

        assert summary["checked"] == 2
        assert summary["online"] == 1
        assert summary["offline"] == 1
        assert summary["dry_run"] is True
        # DB should be untouched
        assert store.get_online_status("listing_a") is None
        assert store.get_online_status("listing_b") is None
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
        store.upsert_listings([make_listing(url=f"{base_url}/check-me")])

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


# --- JSON-LD positive signal tests ---


def test_positive_jsonld_signal_overrides_notfound_body():
    class PositiveHandler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._respond()

        def do_GET(self):
            self._respond()

        def _respond(self):
            if self.path != "/listing":
                self.send_response(404)
                self.end_headers()
                return
            host, port = self.server.server_address[:2]
            base = f"http://{host}:{port}"
            body = (
                '<html><body>'
                'Dieses Inserat ist nicht mehr verfügbar, aber Sie können:'
                '<script type="application/ld+json">'
                f'{{"@type": "Car", "url": "{base}/listing", '
                '"offers": {"availability": "InStock"}}'
                '</script>'
                '</body></html>'
            )
            body_bytes = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body_bytes)

        def log_message(self, format, *args):
            pass

    server, base_url = serve(PositiveHandler)
    try:
        status, error = _check_single_url(f"{base_url}/listing")
        assert status == 200
        assert error is None
    finally:
        server.shutdown()


def test_no_positive_signal_stays_offline():
    body = (
        "<html><body>"
        "Dieses Inserat ist nicht mehr verfügbar."
        "</body></html>"
    )
    handler_cls = make_body_handler(responses={"/listing": (200, body)})
    server, base_url = serve(handler_cls)
    try:
        status, error = _check_single_url(f"{base_url}/listing")
        assert status == 410
        assert error == "not found body"
    finally:
        server.shutdown()


def test_show_deleted_veil_wins_over_jsonld():
    class VeilHandler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._respond()

        def do_GET(self):
            self._respond()

        def _respond(self):
            if self.path != "/listing":
                self.send_response(404)
                self.end_headers()
                return
            host, port = self.server.server_address[:2]
            base = f"http://{host}:{port}"
            body = (
                '<html><body>'
                'var config = {showDeletedVeil: true}; '
                'Dieses Inserat ist nicht mehr verfügbar.'
                '<script type="application/ld+json">'
                f'{{"@type": "Car", "url": "{base}/listing", '
                '"offers": {"availability": "InStock"}}'
                '</script>'
                '</body></html>'
            )
            body_bytes = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body_bytes)

        def log_message(self, format, *args):
            pass

    server, base_url = serve(VeilHandler)
    try:
        status, error = _check_single_url(f"{base_url}/listing")
        assert status == 410
        assert error == "not found body"
    finally:
        server.shutdown()


def test_positive_signal_wrong_url_ignored():
    body = (
        "<html><body>"
        "Dieses Inserat ist nicht mehr verfügbar."
        '<script type="application/ld+json">'
        '{"@type": "Car", "url": "https://other.example/not-this", '
        '"offers": {"availability": "InStock"}}'
        '</script>'
        "</body></html>"
    )
    handler_cls = make_body_handler(responses={"/listing": (200, body)})
    server, base_url = serve(handler_cls)
    try:
        status, error = _check_single_url(f"{base_url}/listing")
        assert status == 410
        assert error == "not found body"
    finally:
        server.shutdown()
