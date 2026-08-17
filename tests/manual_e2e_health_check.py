#!/usr/bin/env python3
"""Manual end-to-end test for the health-check / offline-detection pipeline.

Simulates the full lifecycle:
  1. Start a local HTTP server serving a listing.
  2. Insert a test Listing into a fresh DB.
  3. Run check_stale_offers(force=True) -> expect online.
  4. Simulate eBay Kleinanzeigen removal (server returns 404 / redirect).
  5. Run check_stale_offers(force=True) -> expect offline.
  6. Verify final DB state.

Usage:
    python tests/manual_e2e_health_check.py

Exit code 0 = all stages passed.
"""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

# Ensure src is on the path
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from corvette_tracker.health import check_stale_offers
from corvette_tracker.models import Listing
from corvette_tracker.storage import TrackerStore

PASS = 0
FAIL = 1


def _check(label: str, condition: bool, detail: str = "") -> bool:
    """Assert a condition and print pass/fail."""
    if condition:
        print(f"  ✓ {label}")
        return True
    msg = f"  ✗ {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return False


class ListingServer:
    """A tiny HTTP server that serves a configurable response per path."""

    def __init__(self) -> None:
        self._responses: dict[str, tuple[int, str]] = {}

    def set(self, path: str, status: int, body: str = "OK") -> None:
        self._responses[path] = (status, body)

    def _make_handler(self):
        responses = self._responses

        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self):
                self._respond()

            def do_GET(self):
                self._respond()

            def _respond(self):
                status, body = responses.get(self.path, (404, "Not Found"))
                body_bytes = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body_bytes)

            def log_message(self, fmt, *args):
                pass  # quiet

        return Handler

    def start(self) -> str:
        self.server = HTTPServer(("127.0.0.1", 0), self._make_handler())
        host, port = self.server.server_address[:2]
        base = f"http://{host}:{port}"
        t = threading.Thread(target=self.server.serve_forever, daemon=True)
        t.start()
        self._thread = t
        return base

    def stop(self) -> None:
        self.server.shutdown()


def main() -> int:
    all_ok = True
    server = ListingServer()

    with TemporaryDirectory(prefix="e2e-health-") as tmpdir:
        store = TrackerStore(Path(tmpdir) / "tracker.sqlite")
        db_path = store.path

        # --- Stage 1: listing is online ---
        print("\n=== Stage 1: Listing is online ===")
        server.set(
            "/auto/123", 200, ("<html><body>Chevrolet Corvette C6 6.0 V8, 39.900 €</body></html>")
        )
        base = server.start()
        print(f"  Server started at {base}")

        store.upsert_listings(
            [
                Listing(
                    id="kleinanzeigen_999",
                    source="Kleinanzeigen",
                    source_listing_id="999",
                    url=f"{base}/auto/123",
                    title="Corvette C6",
                    generation="C6",
                ),
            ]
        )
        print(f"  Inserted test listing → {base}/auto/123")

        summary = check_stale_offers(store, force=True)
        online = _check(
            "Listing marked as online",
            summary["online"] == 1 and summary["offline"] == 0 and summary["checked"] == 1,
            f"summary={summary}",
        )
        all_ok &= online

        cached = store.get_online_status("kleinanzeigen_999")
        all_ok &= _check(
            "DB says is_online=1",
            cached is not None and cached["is_online"] == 1,
            f"cached={cached}",
        )

        # --- Stage 2: listing removed (404) ---
        print("\n=== Stage 2: Listing removed (404) ===")
        server.set("/auto/123", 404, "Not Found")

        summary = check_stale_offers(store, force=True)
        offline = _check(
            "Listing marked as offline after 404",
            summary["offline"] == 1 and summary["online"] == 0 and summary["checked"] == 1,
            f"summary={summary}",
        )
        all_ok &= offline

        cached = store.get_online_status("kleinanzeigen_999")
        all_ok &= _check(
            "DB says is_online=0 with http_status=404",
            cached is not None and cached["is_online"] == 0 and cached["http_status"] == 404,
            f"cached={cached}",
        )

        # --- Stage 3: listing reappears (200) ---
        print("\n=== Stage 3: Listing reappears (200) ===")
        server.set("/auto/123", 200, "<html><body>Corvette C6, back in stock</body></html>")

        summary = check_stale_offers(store, force=True)
        all_ok &= _check(
            "Listing back to online after 200",
            summary["online"] == 1 and summary["offline"] == 0 and summary["checked"] == 1,
            f"summary={summary}",
        )

        cached = store.get_online_status("kleinanzeigen_999")
        all_ok &= _check(
            "DB says is_online=1 with http_status=200",
            cached is not None and cached["is_online"] == 1 and cached["http_status"] == 200,
            f"cached={cached}",
        )

        # --- Stage 4: redirect detection (302 → homepage) ---
        print("\n=== Stage 4: Redirect (302) — Kleinanzeigen offline pattern ===")
        server.set("/auto/123", 302, "Moved Temporarily")

        summary = check_stale_offers(store, force=True)
        all_ok &= _check(
            "Listing offline after 302 redirect",
            summary["offline"] == 1 and summary["online"] == 0 and summary["checked"] == 1,
            f"summary={summary}",
        )

        cached = store.get_online_status("kleinanzeigen_999")
        all_ok &= _check(
            "DB says is_online=0 with http_status=302",
            cached is not None and cached["is_online"] == 0 and cached["http_status"] == 302,
            f"cached={cached}",
        )

        # --- Stage 5: content-based detection (200 + 'nicht gefunden' body) ---
        print("\n=== Stage 5: Content-based detection (200 + body says 'not found') ===")
        server.set(
            "/auto/123", 200, ("<html><body>Die Anzeige wurde leider nicht gefunden.</body></html>")
        )

        summary = check_stale_offers(store, force=True)
        all_ok &= _check(
            "Listing offline after content-based detection (200 + body)",
            summary["offline"] == 1 and summary["online"] == 0 and summary["checked"] == 1,
            f"summary={summary}",
        )

        cached = store.get_online_status("kleinanzeigen_999")
        all_ok &= _check(
            "DB says is_online=0 with http_status=410 (synthetic Gone)",
            cached is not None and cached["is_online"] == 0 and cached["http_status"] == 410,
            f"cached={cached}",
        )

        # --- Stage 6: dry-run does not write ---
        print("\n=== Stage 6: Dry-run mode ===")
        # First make the listing online again
        server.set("/auto/123", 200, "<html><body>Corvette online</body></html>")
        check_stale_offers(store, force=True)  # write online

        # Now do a dry-run with 404 — should detect offline but NOT write
        server.set("/auto/123", 404, "Gone")
        summary = check_stale_offers(store, force=True, dry_run=True)

        all_ok &= _check(
            "Dry-run detected offline",
            summary["offline"] == 1 and summary["dry_run"] is True,
            f"summary={summary}",
        )

        cached = store.get_online_status("kleinanzeigen_999")
        all_ok &= _check(
            "DB still says online (dry-run didn't write)",
            cached is not None and cached["is_online"] == 1,
            f"cached={cached}",
        )

        # --- Summary ---
        server.stop()
        print(f"\n{'=' * 50}")
        if all_ok:
            print("ALL STAGES PASSED  ✓")
            return PASS
        else:
            print("SOME STAGES FAILED  ✗")
            return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
