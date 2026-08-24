from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import re
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import yaml
from typing_extensions import override

from .feed import build_feed_payload, write_exports
from .health import check_stale_offers, get_cached_status
from .presentation import render_app_shell
from .re_scrape import re_scrape_offer
from .scoring import apply_scores, merge_scoring_config
from .storage import FilterParams, TrackerStore, filter_listings

RunCallback = Callable[[], tuple[int, dict[str, Any]]]


def parse_interval_seconds(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    raw = value.strip().lower()
    if raw in {"never", "off", "disabled", "none", "0"}:
        return None
    multiplier = 1
    number = raw
    if raw.endswith("m"):
        multiplier = 60
        number = raw[:-1]
    elif raw.endswith("h"):
        multiplier = 3600
        number = raw[:-1]
    elif raw.endswith("d"):
        multiplier = 86400
        number = raw[:-1]
    seconds = int(float(number) * multiplier)
    if seconds < 1:
        raise ValueError("Cron interval must be at least 1 second or disabled")
    return seconds


class TrackerWebApp:
    def __init__(
        self,
        store: TrackerStore,
        output_dir: str | Path,
        run_callback: RunCallback | None = None,
        config_path: str | Path | None = None,
    ):
        self.store = store
        self.output_dir = Path(output_dir)
        self.run_callback = run_callback
        self.config_path = Path(config_path) if config_path else self.output_dir / "config.yaml"
        self.admin_user = os.getenv("CORVETTE_TRACKER_ADMIN_USER")
        self.admin_password = os.getenv("CORVETTE_TRACKER_ADMIN_PASSWORD")
        self.last_run: dict[str, Any] | None = None
        self.run_lock = threading.Lock()

    def make_server(self, host: str, port: int) -> ThreadingHTTPServer:
        app = self

        class Handler(TrackerRequestHandler):
            tracker_app = app

        return ThreadingHTTPServer((host, port), Handler)

    def refresh_exports(self) -> dict[str, Any]:
        payload = build_feed_payload(apply_scores(self.store.list_active(), self.scoring_config()))
        write_exports(payload, self.output_dir)
        source = self.output_dir / "site" / "index.html"
        if source.exists():
            (self.output_dir / "index.html").write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )
        return payload

    def latest_export_payload(self) -> dict[str, Any] | None:
        path = self.output_dir / "data" / "exports" / "latest.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return payload if isinstance(payload, dict) else None

    def last_run_status(self) -> dict[str, Any] | None:
        if self.last_run:
            return self.last_run
        payload = self.latest_export_payload()
        if not payload or not payload.get("generated_at"):
            return None
        return {
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary", {}),
            "warnings": payload.get("warnings", []),
        }

    def last_crawl_at(self) -> str | None:
        status = self.last_run_status() or {}
        value = status.get("generated_at")
        return str(value) if value else None

    def scoring_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return merge_scoring_config(None)
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        return merge_scoring_config((data.get("scoring") or {}) if isinstance(data, dict) else {})

    def update_scoring_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        current_file = (
            yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
            if self.config_path.exists()
            else {}
        )
        if not isinstance(current_file, dict):
            current_file = {}
        current_scoring = (
            current_file.get("scoring") if isinstance(current_file.get("scoring"), dict) else {}
        )
        new_scoring = merge_scoring_config(current_scoring)
        if "base_score" in updates:
            new_scoring["base_score"] = int(updates["base_score"])
        if "preferred_trims" in updates:
            trims = updates["preferred_trims"]
            if not isinstance(trims, list):
                raise ValueError("preferred_trims must be a list")
            new_scoring["preferred_trims"] = [str(trim) for trim in trims if str(trim).strip()]
        if "weights" in updates:
            weights = updates["weights"]
            if not isinstance(weights, dict):
                raise ValueError("weights must be an object")
            new_scoring["weights"] = new_scoring.get("weights", {}) | {
                str(key): int(value) for key, value in weights.items()
            }
        if "risk_penalties" in updates:
            penalties = updates["risk_penalties"]
            if not isinstance(penalties, dict):
                raise ValueError("risk_penalties must be an object")
            new_scoring["risk_penalties"] = new_scoring.get("risk_penalties", {}) | {
                str(key): int(value) for key, value in penalties.items()
            }
        current_file["scoring"] = new_scoring
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            yaml.safe_dump(current_file, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        self.refresh_exports()
        return new_scoring

    def run_once(self) -> tuple[int, dict[str, Any]]:
        if not self.run_callback:
            payload = self.refresh_exports()
            self.last_run = {
                "exit_code": 0,
                "generated_at": payload.get("generated_at"),
                "summary": payload.get("summary", {}),
                "warnings": payload.get("warnings", []),
            }
            return 0, payload
        with self.run_lock:
            exit_code, payload = self.run_callback()
            self.last_run = {
                "exit_code": exit_code,
                "generated_at": payload.get("generated_at"),
                "summary": payload.get("summary", {}),
                "warnings": payload.get("warnings", []),
            }
            return exit_code, payload


class TrackerRequestHandler(BaseHTTPRequestHandler):
    tracker_app: TrackerWebApp
    server_version = "CorvetteTrackerWeb/0.1"

    @override
    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _require_mutation_auth(self) -> bool:
        user = self.tracker_app.admin_user
        password = self.tracker_app.admin_password
        if not user or not password:
            self._send_json(
                {"error": "mutating API authentication is not configured"},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return False
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            self._send_unauthorized()
            return False
        try:
            decoded = base64.b64decode(auth_header[6:], validate=True).decode("utf-8")
            provided_user, _, provided_password = decoded.partition(":")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            self._send_unauthorized()
            return False
        if not hmac.compare_digest(provided_user, user) or not hmac.compare_digest(
            provided_password, password
        ):
            self._send_unauthorized()
            return False
        return True

    def _send_unauthorized(self) -> None:
        body = json.dumps({"error": "authentication required"}, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Corvette Tracker"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(render_app_shell())
            return
        if path.startswith("/car/"):
            self._send_html(render_app_shell())
            return
        if path == "/api/listings":
            parsed = urlparse(self.path)
            filters: FilterParams = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            scoring = self.tracker_app.scoring_config()
            non_score_filters = {key: value for key, value in filters.items() if key != "score_min"}
            filtered = apply_scores(
                self.tracker_app.store.list_filtered(non_score_filters), scoring
            )
            if "score_min" in filters:
                filtered = filter_listings(filtered, {"score_min": filters["score_min"]})
            created_map = self.tracker_app.store.created_at_map()
            self._send_json(
                {
                    "listings": [
                        {"created_at": created_map.get(l.id), **l.to_dict()} for l in filtered
                    ],
                    "total": len(filtered),
                    "total_all": len(self.tracker_app.store.list_active()),
                    "last_run": self.tracker_app.last_run_status(),
                    "last_crawl_at": self.tracker_app.last_crawl_at(),
                }
            )
            return
        history_prefix = "/api/listings/"
        history_suffix = "/history"
        if path.startswith(history_prefix) and path.endswith(history_suffix):
            listing_id = unquote(path[len(history_prefix) : -len(history_suffix)])
            if self.tracker_app.store.get_listing(listing_id) is None:
                self._send_json({"error": "listing not found"}, HTTPStatus.NOT_FOUND)
                return
            data = self.tracker_app.store.listing_history(listing_id)
            data["online_history"] = self.tracker_app.store.online_status_history(listing_id)
            data["listing_id"] = listing_id
            self._send_json(data)
            return
        if path == "/api/scoring":
            self._send_json({"scoring": self.tracker_app.scoring_config()})
            return
        if path == "/api/status":
            self._send_json(
                {
                    "last_run": self.tracker_app.last_run_status(),
                    "last_crawl_at": self.tracker_app.last_crawl_at(),
                    "total_active": len(self.tracker_app.store.list_active()),
                }
            )
            return
        if path == "/api/offers/status":
            store = self.tracker_app.store
            status_data = get_cached_status(store)
            self._send_json(status_data)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._require_mutation_auth():
            return
        path = urlparse(self.path).path
        if path == "/api/run":
            exit_code, payload = self.tracker_app.run_once()
            status = HTTPStatus.OK if exit_code in {0, 2} else HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json(
                {
                    "exit_code": exit_code,
                    "summary": payload.get("summary", {}),
                    "warnings": payload.get("warnings", []),
                    "last_crawl_at": self.tracker_app.last_crawl_at(),
                },
                status,
            )
            return
        if path == "/api/scoring":
            try:
                scoring = self.tracker_app.update_scoring_config(self._read_json_body())
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"scoring": scoring})
            return
        if path == "/api/offers/check":
            summary = check_stale_offers(self.tracker_app.store, force=True)
            self._send_json(summary)
            return
        if path == "/api/re-scrape":
            try:
                body = self._read_json_body()
                result = re_scrape_offer(
                    self.tracker_app.store,
                    offer_id=body.get("offer_id"),
                    url=body.get("url"),
                )
                self.tracker_app.refresh_exports()
            except json.JSONDecodeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            status = (
                HTTPStatus.OK
                if result.get("success")
                else (
                    HTTPStatus.NOT_FOUND
                    if result.get("action") == "not_found"
                    else HTTPStatus.INTERNAL_SERVER_ERROR
                )
            )
            self._send_json(result, status)
            return
        if path == "/api/merge":
            try:
                body = self._read_json_body()
                listing_ids = body.get("listing_ids")
                if (
                    not isinstance(listing_ids, list)
                    or len(listing_ids) < 2
                    or not all(isinstance(x, str) and x for x in listing_ids)
                ):
                    raise ValueError("listing_ids: mindestens 2 Angebote erforderlich")
                result = self.tracker_app.store.merge_listings(listing_ids)
                self.tracker_app.refresh_exports()
            except json.JSONDecodeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except KeyError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return
        if path == "/api/unmerge":
            try:
                body = self._read_json_body()
                listing_id = body.get("listing_id")
                if not isinstance(listing_id, str) or not listing_id:
                    raise ValueError("listing_id erforderlich")
                updated = self.tracker_app.store.unmerge_listing(listing_id)
                self.tracker_app.refresh_exports()
            except json.JSONDecodeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except KeyError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"listing": updated.to_dict()})
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        if not self._require_mutation_auth():
            return
        path = urlparse(self.path).path
        if path == "/api/scoring":
            try:
                scoring = self.tracker_app.update_scoring_config(self._read_json_body())
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"scoring": scoring})
            return
        prefix = "/api/listings/"
        if not path.startswith(prefix):
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        listing_id = unquote(path[len(prefix) :])
        try:
            updates = self._read_json_body()
            for date_field in ("first_registration", "tuv_until"):
                if date_field in updates and updates[date_field] not in (None, ""):
                    val = str(updates[date_field])
                    if not re.fullmatch(r"\d{4}-\d{2}", val):
                        raise ValueError(
                            f"{date_field} muss das Format JJJJ-MM haben (z.B. 2008-06)"
                        )
            if "model_year" in updates and updates["model_year"] not in (None, ""):
                try:
                    my = int(updates["model_year"])
                except (TypeError, ValueError):
                    raise ValueError("model_year muss eine Zahl sein")
                if not 2004 <= my <= 2014:
                    raise ValueError("model_year muss zwischen 2004 und 2014 liegen")
            updated = self.tracker_app.store.update_overrides(listing_id, updates)
            self.tracker_app.refresh_exports()
        except KeyError:
            self._send_json({"error": "listing not found"}, HTTPStatus.NOT_FOUND)
            return
        except json.JSONDecodeError:
            self._send_json({"error": "invalid json"}, HTTPStatus.BAD_REQUEST)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"listing": updated.to_dict()})

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object")
        return body

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _start_scheduler(app: TrackerWebApp, interval_seconds: int) -> None:
    def loop() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                app.run_once()
            except Exception as exc:  # keep scheduler alive
                app.last_run = {"exit_code": 1, "error": str(exc)}
                print(f"Scheduled crawl failed: {exc}")

    threading.Thread(target=loop, name="corvette-tracker-scheduler", daemon=True).start()


def _start_health_scheduler(app: TrackerWebApp, interval_seconds: int) -> None:
    """Background thread that periodically checks offer URLs for online status."""

    _RETRIABLE_SQLITE_ERRORS = (
        "database is locked",
        "is not unique",
        "UNIQUE constraint",
        "no such table",
    )

    def _robust_check() -> None:
        for attempt in range(3):
            try:
                summary = check_stale_offers(app.store)
                print(
                    f"Health check: {summary['checked']} checked, {summary['skipped']} skipped, "
                    f"{summary['online']} online, {summary['offline']} offline, "
                    f"{summary['failed']} failed, {summary['total']} total"
                )
                return
            except Exception as exc:
                msg = str(exc)
                if any(e in msg for e in _RETRIABLE_SQLITE_ERRORS) and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                import traceback

                traceback.print_exc()
                print(f"Scheduled health check failed (attempt {attempt + 1}): {exc}")

    def loop() -> None:
        while True:
            time.sleep(interval_seconds)
            _robust_check()

    threading.Thread(target=loop, name="corvette-tracker-health-scheduler", daemon=True).start()


def main() -> int:
    host = os.getenv("CORVETTE_TRACKER_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("CORVETTE_TRACKER_PORT", "8096")))
    output_dir = Path(os.getenv("CORVETTE_TRACKER_OUTPUT_DIR", "/app/runtime"))
    database_path = Path(
        os.getenv("CORVETTE_TRACKER_DATABASE", str(output_dir / "data" / "corvette_tracker.sqlite"))
    )
    configured_path = os.getenv("CORVETTE_TRACKER_CONFIG", "/app/config.yaml")
    config_path = Path(configured_path) if configured_path else output_dir / "config.yaml"

    from .cli import run_tracker

    def run_callback() -> tuple[int, dict[str, Any]]:
        return run_tracker(
            str(config_path) if config_path.exists() else None,
            output_dir=output_dir,
            database=database_path,
        )

    with TrackerStore(database_path) as store:
        app = TrackerWebApp(
            store=store, output_dir=output_dir, run_callback=run_callback, config_path=config_path
        )

        if os.getenv("CORVETTE_TRACKER_RUN_ON_START", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            threading.Thread(
                target=app.run_once, name="corvette-tracker-initial-run", daemon=True
            ).start()

        interval = parse_interval_seconds(os.getenv("CORVETTE_TRACKER_CRON_INTERVAL", "6h"))
        if interval is not None:
            _start_scheduler(app, interval)
            print(f"Scheduled crawl interval: {interval}s")
        else:
            print("Scheduled crawl disabled")

        health_interval = parse_interval_seconds(
            os.getenv("CORVETTE_TRACKER_HEALTH_INTERVAL", "5m")
        )
        if health_interval is not None:
            _start_health_scheduler(app, health_interval)
            print(f"Scheduled health check interval: {health_interval}s")

        server = app.make_server(host, port)
        print(f"Corvette Tracker WebUI listening on http://{host}:{port}")
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
