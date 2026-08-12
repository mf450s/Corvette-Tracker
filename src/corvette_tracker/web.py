from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from dataclasses import fields
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import yaml

from .enums import TrimType
from .favicon import favicon_data_uri
from .feed import build_feed_payload, format_eur, format_km, write_exports
from .health import CACHE_TTL_SECONDS, check_stale_offers, get_cached_status
from .models import Listing
from .re_scrape import re_scrape_offer
from .scoring import apply_score, apply_scores, merge_scoring_config
from .storage import EDITABLE_FIELDS, PROTECTED_OVERRIDE_FIELDS, FilterParams, TrackerStore, filter_listings

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
    def __init__(self, store: TrackerStore, output_dir: str | Path, run_callback: RunCallback | None = None, config_path: str | Path | None = None):
        self.store = store
        self.output_dir = Path(output_dir)
        self.run_callback = run_callback
        self.config_path = Path(config_path) if config_path else self.output_dir / "config.yaml"
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
            (self.output_dir / "index.html").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
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
        current_file = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
        if not isinstance(current_file, dict):
            current_file = {}
        current_scoring = current_file.get("scoring") if isinstance(current_file.get("scoring"), dict) else {}
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
            new_scoring["weights"] = new_scoring.get("weights", {}) | {str(key): int(value) for key, value in weights.items()}
        if "risk_penalties" in updates:
            penalties = updates["risk_penalties"]
            if not isinstance(penalties, dict):
                raise ValueError("risk_penalties must be an object")
            new_scoring["risk_penalties"] = new_scoring.get("risk_penalties", {}) | {str(key): int(value) for key, value in penalties.items()}
        current_file["scoring"] = new_scoring
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(yaml.safe_dump(current_file, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.refresh_exports()
        return new_scoring

    def run_once(self) -> tuple[int, dict[str, Any]]:
        if not self.run_callback:
            payload = self.refresh_exports()
            self.last_run = {"exit_code": 0, "generated_at": payload.get("generated_at"), "summary": payload.get("summary", {}), "warnings": payload.get("warnings", [])}
            return 0, payload
        with self.run_lock:
            exit_code, payload = self.run_callback()
            self.last_run = {"exit_code": exit_code, "generated_at": payload.get("generated_at"), "summary": payload.get("summary", {}), "warnings": payload.get("warnings", [])}
            return exit_code, payload


class TrackerRequestHandler(BaseHTTPRequestHandler):
    tracker_app: TrackerWebApp
    server_version = "CorvetteTrackerWeb/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        print(f"{self.address_string()} - {format % args}")

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
            scored = [apply_score(listing, scoring) for listing in self.tracker_app.store.list_active()]
            filtered = filter_listings(scored, filters)
            created_map = self.tracker_app.store.created_at_map()
            self._send_json({
                "listings": [{"created_at": created_map.get(l.id), **l.to_dict()} for l in filtered],
                "total": len(filtered),
                "total_all": len(scored),
                "last_run": self.tracker_app.last_run_status(),
                "last_crawl_at": self.tracker_app.last_crawl_at(),
            })
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
            self._send_json({"last_run": self.tracker_app.last_run_status(), "last_crawl_at": self.tracker_app.last_crawl_at(), "total_active": len(self.tracker_app.store.list_active())})
            return
        if path == "/api/offers/status":
            store = self.tracker_app.store
            status_data = get_cached_status(store)
            self._send_json(status_data)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/run":
            exit_code, payload = self.tracker_app.run_once()
            status = HTTPStatus.OK if exit_code in {0, 2} else HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json({"exit_code": exit_code, "summary": payload.get("summary", {}), "warnings": payload.get("warnings", []), "last_crawl_at": self.tracker_app.last_crawl_at()}, status)
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
            status = HTTPStatus.OK if result.get("success") else (
                HTTPStatus.NOT_FOUND if result.get("action") == "not_found"
                else HTTPStatus.INTERNAL_SERVER_ERROR
            )
            self._send_json(result, status)
            return
        if path == "/api/merge":
            try:
                body = self._read_json_body()
                listing_ids = body.get("listing_ids")
                if not isinstance(listing_ids, list) or len(listing_ids) < 2 or not all(isinstance(x, str) and x for x in listing_ids):
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
                        raise ValueError(f"{date_field} muss das Format JJJJ-MM haben (z.B. 2008-06)")
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


def render_app_shell() -> str:
    numeric_fields = {"price_eur", "mileage_km", "power_hp", "estimated_power_hp", "engine_confidence", "origin_confidence", "score", "previous_price_eur", "model_year", "power_kw", "displacement_cc", "owners_count"}
    boolean_fields = {"eu_spec", "has_damage", "service_history", "warranty", "magnetic_ride", "active_exhaust", "head_up_display", "navigation", "bose_audio", "leather_interior", "heated_seats"}
    list_fields = {"equipment", "visual_flags", "image_urls", "risk_flags", "inference_notes", "conflict_flags"}
    dict_fields = {"ai_enrichment"}
    trim_options = [trim.value for trim in TrimType]
    C6_EXTERIOR_COLORS = [
        "Arctic White", "Black", "Blade Silver", "Carbon Flash", "Carlisle Blue",
        "Crystal Red", "Cyber Gray", "Daytona Sunset Orange", "Inferno Orange",
        "Jetstream Blue", "LeMans Blue", "Machine Silver", "Magnetic Red",
        "Millennium Yellow", "Monterey Red", "Night Race Blue", "Precision Red",
        "Supersonic Blue", "Sunset Orange", "Torch Red", "Victory Red",
        "Velocity Yellow", "Atomic Orange",
    ]
    C6_INTERIOR_COLORS = [
        "Ebony", "Cashmere", "Titanium", "Cobalt Red", "Linen", "Red", "Steel Gray",
    ]
    color_options = {
        "exterior_color": C6_EXTERIOR_COLORS,
        "interior_color": C6_INTERIOR_COLORS,
    }
    FIELD_LABELS = {
        "id": "ID", "source": "Quelle", "source_listing_id": "Quellen-ID", "url": "URL",
        "title": "Titel", "generation": "Generation", "model": "Modell",
        "price_eur": "Preis (€)", "price_label": "Preis-Label", "mileage_km": "Kilometerstand",
        "engine": "Motor", "probable_engine": "Motor (geschätzt)", "engine_confidence": "Motor-Konfidenz",
        "engine_note": "Motor-Notiz", "power_hp": "Leistung (PS)", "estimated_power_hp": "Leistung (geschätzt)",
        "power_note": "Leistungs-Notiz", "trim": "Ausstattung",
        "model_year": "Modelljahr", "power_kw": "Leistung (kW)", "displacement_cc": "Hubraum (ccm)",
        "drivetrain": "Antrieb", "condition": "Zustand", "owners_count": "Vorbesitzer",
        "service_history": "Scheckheft gepflegt", "warranty": "Garantie",
        "magnetic_ride": "Magnetic Ride (F55)", "active_exhaust": "Klappenauspuff (NPP)",
        "head_up_display": "Head-Up-Display", "navigation": "Navigation", "bose_audio": "Bose-Sound",
        "leather_interior": "Lederausstattung", "heated_seats": "Sitzheizung",
        "first_registration": "Erstzulassung", "tuv_until": "TÜV bis",
        "transmission": "Getriebe", "body_style": "Karosserie",
        "exterior_color": "Außenfarbe", "interior_color": "Innenfarbe", "eu_spec": "EU-Spezifikation",
        "equipment": "Ausstattung", "visual_flags": "Visuelle Merkmale", "ai_enrichment": "KI-Anreicherung",
        "accident_status": "Unfallstatus", "damage": "Schaden", "has_damage": "Unfallschaden",
        "location_raw": "Standort", "location_country": "Standortland", "origin_country": "Herkunftsland",
        "origin_confidence": "Herkunfts-Konfidenz", "seller_type": "Verkäufer", "vin": "Fahrgestellnummer (VIN)",
        "image_urls": "Bilder", "description_text": "Beschreibung",
        "risk_flags": "Risiko-Flags", "inference_notes": "Inferenz-Notizen", "conflict_flags": "Konflikt-Flags",
        "score": "Score", "change_type": "Änderungstyp", "previous_price_eur": "Vorheriger Preis",
        "cluster_id": "Cluster", "validation_flags": "Validierungs-Flags", "hidden": "Ausgeblendet",
    }
    month_fields = {"first_registration", "tuv_until"}
    enum_options = {
        "transmission": [("manual", "Schalter"), ("automatic", "Automatik"), ("unknown", "Unbekannt")],
        "body_style": [("Cabrio", "Cabrio"), ("Coupé", "Coupé"), ("Targa", "Targa"), ("unknown", "Unbekannt")],
    }
    field_registry = [
        {
            "name": field.name,
            "label": FIELD_LABELS.get(field.name, field.name),
            "editable": field.name in EDITABLE_FIELDS,
            "protected": field.name in PROTECTED_OVERRIDE_FIELDS,
            "kind": "month" if field.name in month_fields else "select" if field.name == "trim" or field.name in enum_options else "number" if field.name in numeric_fields else "boolean" if field.name in boolean_fields else "list" if field.name in list_fields else "json" if field.name in dict_fields else "text",
            "options": trim_options if field.name == "trim" else [o for o, _ in enum_options[field.name]] if field.name in enum_options else None,
            "option_labels": [l for _, l in enum_options[field.name]] if field.name in enum_options else None,
            "color_options": color_options.get(field.name),
        }
        for field in fields(Listing)
    ]
    EDITOR_PRIORITY = [
        "price_eur", "price_label", "mileage_km", "title", "model", "model_year",
        "trim", "transmission", "body_style", "engine", "power_hp", "power_kw",
        "displacement_cc", "drivetrain", "exterior_color", "interior_color",
        "first_registration", "tuv_until", "condition", "owners_count",
        "service_history", "warranty", "magnetic_ride", "active_exhaust",
        "head_up_display", "navigation", "bose_audio", "leather_interior",
        "heated_seats", "eu_spec", "accident_status", "damage", "has_damage",
        "seller_type", "vin", "location_raw", "location_country", "origin_country",
        "equipment", "visual_flags", "description_text", "hidden",
    ]
    field_registry.sort(key=lambda f: EDITOR_PRIORITY.index(f["name"]) if f["name"] in EDITOR_PRIORITY else len(EDITOR_PRIORITY))
    field_registry_attr = html.escape(json.dumps(field_registry, ensure_ascii=False), quote=True)
    field_registry_js = json.dumps(field_registry, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Corvette Tracker WebUI</title>
  <link rel="icon" type="image/svg+xml" href="{favicon_data_uri()}">
  <style>
    :root {{ color-scheme: dark; --bg:#09090b; --card:#141418; --line:#27272a; --muted:#a1a1aa; --text:#fafafa; --accent:#ef4444; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; font-family:Inter,ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
    header,.wrap {{ max-width:1180px; margin:0 auto; padding:24px 20px; }} h1 {{ font-size:42px; letter-spacing:-.04em; margin:0 0 8px; }}
    button,a.button {{ border:0; border-radius:10px; padding:10px 12px; color:white; background:var(--accent); font-weight:700; cursor:pointer; text-decoration:none; }}
    a.secondary {{ background:#27272a; }} .button-row {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }} .title-link {{ color:var(--text); text-decoration:none; }} .title-link:hover {{ color:white; text-decoration:underline; }}
    .muted {{ color:var(--muted); }} .toolbar {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:16px; }} .card,.panel {{ border:1px solid var(--line); border-radius:18px; background:var(--card); overflow:hidden; }} .panel {{ padding:16px; margin-bottom:18px; }} .list-toolbar {{ display:flex; justify-content:space-between; align-items:end; gap:12px; flex-wrap:wrap; }}
    .image {{ aspect-ratio:16/9; background:#18181b; display:block; position:relative; overflow:hidden; }} .image img {{ width:100%; height:100%; object-fit:cover; }} .score-badge {{ position:absolute; top:10px; left:10px; z-index:1; display:inline-flex; align-items:center; justify-content:center; min-width:54px; padding:7px 11px; border-radius:999px; background:linear-gradient(135deg,#ef4444,#f59e0b); color:white; font-weight:900; box-shadow:0 10px 26px rgba(0,0,0,.38); }} .body {{ padding:16px; }}
    h2 {{ margin:0 0 8px; font-size:20px; }} .price {{ font-size:26px; font-weight:800; margin:0 0 10px; }}
    dl {{ display:grid; grid-template-columns:repeat(2,1fr); gap:8px; }} dl div {{ border:1px solid var(--line); border-radius:12px; padding:8px; }} dt {{ color:var(--muted); font-size:12px; }} dd {{ margin:3px 0 0; font-weight:700; overflow-wrap:anywhere; }}
    form {{ display:grid; gap:8px; margin-top:14px; grid-template-columns:1fr 1fr auto; }} .score-form {{ grid-template-columns:repeat(5,minmax(120px,1fr)); align-items:end; }} .score-form label {{ display:grid; gap:6px; color:var(--muted); font-size:12px; }} .field-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:8px; margin-top:12px; }} .field-editor {{ border:1px solid var(--line); border-radius:12px; padding:8px; background:rgba(0,0,0,.16); }} .field-editor label,.readonly-field span {{ display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }} .field-editor form {{ grid-template-columns:minmax(0,1fr) auto; margin-top:0; }} .field-editor textarea {{ min-height:76px; resize:vertical; }} select,input,textarea {{ min-width:0; border:1px solid var(--line); border-radius:10px; padding:10px; background:#09090b; color:var(--text); }}
    .status {{ min-height:1.4em; }} .crawl-meta {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:10px; color:var(--muted); }} .crawl-meta strong {{ color:var(--text); }}
    .status-dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align:middle; flex-shrink:0; }}
    .status-dot.online {{ background:#22c55e; box-shadow:0 0 6px rgba(34,197,94,.5); }}
    .status-dot.offline {{ background:#ef4444; box-shadow:0 0 6px rgba(239,68,68,.5); }}
    .status-dot.unknown {{ background:#6b7280; }}
    .offer-badge {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:11px; font-weight:700; background:rgba(239,68,68,.16); color:#f87171; margin-bottom:8px; }}
    .offer-links {{ margin-top:10px; font-size:13px; }} .offer-links a {{ color:var(--accent); text-decoration:none; margin:0 4px; }} .offer-links a:hover {{ text-decoration:underline; }}
    .meta-line {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
    .filter-input {{ min-width:160px; }}
    .ez-range {{ display:flex; gap:6px; align-items:center; }} .ez-range input {{ width:80px; }}
    .list-toolbar {{ display:flex; justify-content:initial; align-items:start; gap:12px; flex-wrap:wrap; }}
    .list-toolbar-head {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; }}
    .list-toolbar-head h2 {{ margin:0; }}
    .list-toolbar-actions {{ display:flex; align-items:center; gap:12px; }}
    .list-toolbar-actions .button {{ padding:8px 12px; font-size:13px; }}
    .filter-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px 14px; margin-top:14px; align-items:end; }}
    .filter-field {{ display:grid; gap:6px; font-size:12px; color:var(--muted); min-width:0; }}
    .filter-field select,.filter-field input {{ width:100%; min-width:0; }}
    .search-field {{ grid-column:span 2; }}
    .range-pair {{ display:flex; gap:4px; align-items:center; min-width:0; }}
    .range-pair input {{ flex:1; min-width:0; width:auto; }}
    .range-sep {{ color:var(--muted); flex-shrink:0; }}
    .range-unit {{ color:var(--muted); flex-shrink:0; font-size:12px; }}
    .score-field {{ }}
    .score-slider {{ width:100%; }}
    .score-field b {{ color:var(--accent); }}
    .filter-check {{ display:inline-flex; align-items:center; gap:8px; cursor:pointer; font-size:13px; color:var(--text); padding:10px 0; }}
    .filter-check input[type=checkbox] {{ width:18px; height:18px; accent-color:var(--accent); }}
    .visible-count {{ font-weight:700; font-size:15px; color:var(--text); }}
    .history-table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
    .history-table th,.history-table td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); font-size:13px; vertical-align:top; }}
    .history-table th {{ color:var(--muted); font-weight:600; font-size:12px; }}
    .history-table td.muted {{ color:var(--muted); }}
    .change-badge {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:11px; font-weight:700; }}
    .change-badge.new {{ background:rgba(34,197,94,.16); color:#4ade80; }}
    .change-badge.price_change {{ background:rgba(239,68,68,.16); color:#f87171; }}
    .change-badge.metadata_change {{ background:rgba(245,158,11,.16); color:#fbbf24; }}
    .change-badge.manual_override {{ background:rgba(139,92,246,.16); color:#c4b5fd; }}
    .change-badge.unchanged {{ background:rgba(161,161,170,.14); color:var(--muted); }}
    .change-badge.went_offline {{ background:rgba(239,68,68,.22); color:#f87171; }}
    .change-badge.came_online {{ background:rgba(34,197,94,.22); color:#4ade80; }}
    .delta-up {{ color:#4ade80; font-weight:700; }}
    .delta-down {{ color:#f87171; font-weight:700; }}
    .collapsed-hint {{ color:var(--muted); font-size:11px; font-weight:400; margin-left:4px; }}
    .history-summary {{ display:flex; gap:22px; flex-wrap:wrap; margin:14px 0 4px; }}
    .history-summary .stat {{ display:grid; gap:2px; }}
    .history-summary .stat dt {{ color:var(--muted); font-size:11px; }}
    .history-summary .stat dd {{ margin:0; font-weight:800; font-size:15px; }}
    .price-chart {{ width:100%; height:170px; margin:14px 0 6px; background:rgba(0,0,0,.18); border:1px solid var(--line); border-radius:12px; padding:10px; }}
    .price-chart svg {{ width:100%; height:100%; }}
    .online-event td {{ background:rgba(0,0,0,.14); }}
  </style>
</head>
<body>
  <header>
    <h1>Corvette Tracker WebUI</h1>
    <div class="toolbar"><button id="run">Jetzt crawlen</button><span id="status" class="status muted"></span></div>
    <p class="crawl-meta">Letzter Crawl: <strong id="last-crawl">noch nie</strong></p>
  </header>
  <main class="wrap"><section class="panel list-toolbar" id="filter-bar">
  <div class="list-toolbar-head"><h2>Listings</h2><div class="list-toolbar-actions"><p class="visible-count" id="visible-count">Alle Angebote</p><button id="reset-filters" class="button secondary" type="button">Filter zurücksetzen</button></div></div>
  <div class="filter-grid">
    <label class="filter-field search-field">Suche<input id="text-search" class="filter-input" type="text" placeholder="Titel, Beschreibung&hellip;"></label>
    <label class="filter-field">Status<select id="status-filter"><option value="all">Alle</option><option value="online">Online</option><option value="offline">Offline</option></select></label>
    <label class="filter-field">Quelle<select id="source-filter"><option value="all">Alle</option><option value="AutoScout24">AutoScout24</option><option value="AutoUncle">AutoUncle</option><option value="Kleinanzeigen">Kleinanzeigen</option></select></label>
    <label class="filter-field">Getriebe<select id="transmission-filter"><option value="all">Alle</option><option value="manual">Schalter</option><option value="automatic">Automatik</option></select></label>
    <label class="filter-field">Trim<select id="trim-filter"><option value="all">Alle</option><option value="Base">Base</option><option value="Grand Sport">Grand Sport</option><option value="Z06">Z06</option><option value="ZR1">ZR1</option></select></label>
    <label class="filter-field">Motor<select id="engine-filter"><option value="all">Alle</option><option value="LS2">LS2</option><option value="LS3">LS3</option><option value="LS7">LS7</option><option value="LS9">LS9</option></select></label>
    <label class="filter-field">Karosserie<select id="body-filter"><option value="all">Alle</option><option value="Cabrio">Cabrio</option><option value="Coupé">Coupé</option><option value="Targa">Targa</option></select></label>
    <div class="filter-field"><span>Preis</span><div class="range-pair"><input id="price-min" type="number" placeholder="von" min="0" step="1000"><span class="range-sep">&ndash;</span><input id="price-max" type="number" placeholder="bis" min="0" step="1000"><span class="range-unit">€</span></div></div>
    <div class="filter-field"><span>km</span><div class="range-pair"><input id="km-min" type="number" placeholder="von" min="0" step="1000"><span class="range-sep">&ndash;</span><input id="km-max" type="number" placeholder="bis" min="0" step="1000"><span class="range-unit">km</span></div></div>
    <div class="filter-field"><span>EZ (Jahr)</span><div class="range-pair"><input id="ez-from" type="text" placeholder="von" maxlength="4"><span class="range-sep">&ndash;</span><input id="ez-to" type="text" placeholder="bis" maxlength="4"></div></div>
    <label class="filter-field">Sortierung<select id="listing-sort"><option value="score-desc">Score hoch</option><option value="score-asc">Score niedrig</option><option value="status-online">Online zuerst</option><option value="status-offline">Offline zuerst</option><option value="price-asc">Preis niedrig</option><option value="price-desc">Preis hoch</option><option value="mileage-asc">km niedrig</option><option value="mileage-desc">km hoch</option><option value="ez-asc">EZ alt&rarr;neu</option><option value="ez-desc">EZ neu&rarr;alt</option><option value="created-desc">Neu hinzugefügt</option><option value="created-asc">Älteste zuerst</option><option value="source">Quelle</option></select></label>
    <label class="filter-field">Änderung<select id="change-filter"><option value="all">Alle</option><option value="new">Neu</option><option value="price_change">Preis geändert</option><option value="metadata_change">Metadaten geändert</option><option value="unchanged">Unverändert</option></select></label>
    <label class="filter-field score-field"><span>Score &ge; <b id="score-value">0</b></span><input id="score-min" class="score-slider" type="range" min="0" max="100" value="0"></label>
    <label class="filter-check"><input id="hide-risk" type="checkbox">Riskante ausblenden</label>
  </div>
</section><div id="listings" class="grid"></div></main>
<script data-field-registry="{field_registry_attr}">
const fieldRegistry = {field_registry_js};
let currentListings = [];
let healthStatusMap = {{}};
function getStatus(id) {{ return healthStatusMap[id] ?? 'unknown'; }}
function statusLabel(s) {{ return s === 'online' ? 'Online' : s === 'offline' ? 'Offline' : 'Unbekannt'; }}
function esc(value) {{ return String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[c])); }}
function fmtEur(value) {{ return value == null ? 'k.A.' : Number(value).toLocaleString('de-DE') + ' €'; }}
function fmtKm(value) {{ return value == null ? 'k.A.' : Number(value).toLocaleString('de-DE') + ' km'; }}
function fmtDateTime(value) {{
  if (!value) return 'noch nie';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('de-DE');
}}
function updateLastCrawl(value) {{ document.getElementById('last-crawl').textContent = fmtDateTime(value); }}
function fieldValue(item, name) {{ const value = item[name]; return Array.isArray(value) ? value.join(', ') : (value ?? ''); }}
function displayValue(value) {{
  if (value == null || value === '') return 'k.A.';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '[]';
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'boolean') return value ? 'ja' : 'nein';
  return String(value);
}}
function editorValue(value, kind) {{
  if (value == null) return '';
  if (kind === 'month') return String(value ?? '');
  if (kind === 'json') return JSON.stringify(value, null, 2);
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}}
function parseEditorValue(raw, kind) {{
  if (raw === '') return null;
  if (kind === 'month') return raw || null;
  if (kind === 'number') return Number(raw);
  if (kind === 'boolean') return raw === 'true' ? true : raw === 'false' ? false : null;
  if (kind === 'select') return raw;
  if (kind === 'list') return raw.split(',').map(value => value.trim()).filter(Boolean);
  if (kind === 'json') return JSON.parse(raw);
  return raw;
}}
async function loadStatus() {{
  const response = await fetch('/api/status');
  const payload = await response.json();
  updateLastCrawl(payload.last_crawl_at);
}}
async function loadHealthStatus() {{
  try {{
    const response = await fetch('/api/offers/status');
    const payload = await response.json();
    const map = {{}};
    (payload.offers || []).forEach(o => {{ map[o.listing_id] = o.is_online ? 'online' : 'offline'; }});
    healthStatusMap = map;
  }} catch (e) {{
    // silently ignore — show all as unknown
  }}
  renderListings();
}}
async function loadListings() {{
  const response = await fetch('/api/listings');
  const payload = await response.json();
  currentListings = payload.listings || [];
  updateLastCrawl(payload.last_crawl_at);
  document.getElementById('status').textContent = `${{currentListings.length}} aktive Treffer`;
  await loadHealthStatus();
  renderListings();
}}
function sortListings(listings) {{
  const order = document.getElementById('listing-sort').value;
  return [...listings].sort((a, b) => {{
    const sa = getStatus(a.id), sb = getStatus(b.id);
    const sta = sa === 'online' ? 1 : sa === 'offline' ? 2 : 3;
    const stb = sb === 'online' ? 1 : sb === 'offline' ? 2 : 3;
    if (order === 'status-online') return sta - stb;
    if (order === 'status-offline') return stb - sta;
    if (order === 'score-asc') return Number(a.score || 0) - Number(b.score || 0);
    if (order === 'price-asc') return Number(a.price_eur || 999999999) - Number(b.price_eur || 999999999);
    if (order === 'price-desc') return Number(b.price_eur || 0) - Number(a.price_eur || 0);
    if (order === 'mileage-asc') return Number(a.mileage_km || 999999999) - Number(b.mileage_km || 999999999);
    if (order === 'mileage-desc') return Number(b.mileage_km || 0) - Number(a.mileage_km || 0);
    if (order === 'ez-asc') return (a.first_registration || 'ZZZZ').localeCompare(b.first_registration || 'ZZZZ');
    if (order === 'ez-desc') return (b.first_registration || '').localeCompare(a.first_registration || '');
    if (order === 'created-desc') return (b.created_at || '').localeCompare(a.created_at || '');
    if (order === 'created-asc') return (a.created_at || '').localeCompare(b.created_at || '');
    if (order === 'source') return (a.source || '').localeCompare(b.source || '');
    return Number(b.score || 0) - Number(a.score || 0);
  }});
}}
function groupListings(listings) {{
  const groups = [];
  const byId = new Map();
  listings.forEach(item => {{
    const clusterId = item.cluster_id || null;
    if (clusterId) {{
      let group = byId.get(clusterId);
      if (!group) {{
        group = {{ clusterId: clusterId, members: [] }};
        byId.set(clusterId, group);
        groups.push(group);
      }}
      group.members.push(item);
    }} else {{
      groups.push({{ clusterId: null, members: [item] }});
    }}
  }});
  return groups.map(g => {{
    const primary = g.members.reduce((best, item) => {{
      const bestOnline = getStatus(best.id) === 'online';
      const itemOnline = getStatus(item.id) === 'online';
      if (bestOnline !== itemOnline) return itemOnline ? item : best;
      if (best.score === item.score) return best.id < item.id ? best : item;
      return item.score > best.score ? item : best;
    }});
    const sourceSummary = [...new Set(g.members.map(m => m.source).filter(Boolean))].join(' + ');
    return {{
      clusterId: g.clusterId,
      members: g.members,
      primary: primary,
      offerCount: g.members.length,
      sourceSummary: sourceSummary,
    }};
  }});
}}
function renderListings() {{
  renderRoute();
}}
function overviewSpec(label, value) {{ return `<div><dt>${{esc(label)}}</dt><dd>${{esc(displayValue(value))}}</dd></div>`; }}
function renderOverviewCard(item, group) {{
  const image = (item.image_urls || [])[0];
  const detailUrl = '/car/' + encodeURIComponent(item.id);
  const offerUrl = item.url || detailUrl;
  const st = getStatus(item.id);
  const extraBadge = group && group.offerCount > 1 ? `<span class="offer-badge">${{group.offerCount}} Angebote · ${{esc(group.sourceSummary)}}</span>` : '';
  const offerLinks = group && group.offerCount > 1 ? '<p class="offer-links muted">Angebote: ' + group.members.map(m => '<a href="' + esc(m.url) + '" target="_blank" rel="noreferrer">' + esc(m.source) + '</a>').join(' · ') + '</p>' : '';
  return `<article class="card" data-overview-card data-id="${{esc(item.id)}}" data-status="${{st}}">
    <a class="image" href="${{esc(offerUrl)}}" target="_blank" rel="noreferrer"><span class="score-badge">${{esc(item.score ?? 0)}}%</span>${{image ? `<img src="${{esc(image)}}" alt="">` : ''}}</a>
    <div class="body">
      <p class="muted meta-line"><span class="status-dot ${{st}}"></span>${{esc(item.source)}} &middot; ${{statusLabel(st)}} &middot; Score ${{esc(item.score)}}</p>
      ${{extraBadge}}
      <h2><a class="title-link" href="${{esc(offerUrl)}}" target="_blank" rel="noreferrer">${{esc(item.title)}}</a></h2>
      <p class="price">${{fmtEur(item.price_eur)}}</p>
      <dl class="overview-specs">
        ${{overviewSpec('Trim', item.trim || 'k.A.')}}
        ${{overviewSpec('Getriebe', item.transmission === 'manual' ? 'Schalter' : item.transmission === 'automatic' ? 'Automatik' : item.transmission || 'k.A.')}}
        ${{overviewSpec('km', fmtKm(item.mileage_km))}}
        ${{overviewSpec('Motor', item.engine || item.probable_engine || 'k.A.')}}
        ${{overviewSpec('Karosserie', item.body_style || 'k.A.')}}
        ${{overviewSpec('EZ', item.first_registration || 'k.A.')}}
      </dl>
      <div class="button-row"><a class="button" href="${{esc(offerUrl)}}" target="_blank" rel="noreferrer">Angebot öffnen</a><a class="button secondary" href="${{detailUrl}}" onclick="openDetail(event, '${{esc(item.id)}}')">Details bearbeiten</a></div>
      ${{offerLinks}}
    </div>
  </article>`;
}}
function inlineEditorValue(field, item) {{
  const value = item[field.name];
  const fieldLabel = field.label || field.name;
  if (!field.editable) return `<div class="field-editor readonly-field"><span>${{esc(fieldLabel)}}</span><strong>${{esc(displayValue(value))}}</strong></div>`;
  if (field.kind === 'boolean') {{
    return `<div class="field-editor" data-inline-field="${{esc(field.name)}}"><label>${{esc(fieldLabel)}}</label><select data-field-name="${{esc(field.name)}}" data-field-kind="${{esc(field.kind)}}"><option value="" ${{value == null ? 'selected' : ''}}>k.A.</option><option value="true" ${{value === true ? 'selected' : ''}}>ja</option><option value="false" ${{value === false ? 'selected' : ''}}>nein</option></select></div>`;
  }}
  if (field.kind === 'select' && Array.isArray(field.options)) {{
    const optionLabels = field.option_labels || field.options;
    const options = field.options.map((option, i) => `<option value="${{esc(option)}}" ${{value === option ? 'selected' : ''}}>${{esc(optionLabels[i] || option)}}</option>`).join('');
    return `<div class="field-editor" data-inline-field="${{esc(field.name)}}"><label>${{esc(fieldLabel)}}</label><select data-field-name="${{esc(field.name)}}" data-field-kind="select"><option value="" ${{value == null || value === '' ? 'selected' : ''}}>k.A.</option>${{options}}</select></div>`;
  }}
  if (field.color_options && Array.isArray(field.color_options) && field.color_options.length > 0) {{
    const listId = 'color-list-' + field.name;
    const datalist = '<datalist id="' + listId + '">' + field.color_options.map(opt => '<option value="' + esc(opt) + '">').join('') + '</datalist>';
    return `<div class="field-editor" data-inline-field="${{esc(field.name)}}"><label>${{esc(field.label || field.name)}}</label><input data-field-name="${{esc(field.name)}}" data-field-kind="text" list="${{listId}}" type="text" value="${{esc(editorValue(value, field.kind))}}" placeholder="Farbe wählen oder eingeben&hellip;">${{datalist}}</div>`;
  }}
  const tag = field.kind === 'json' || field.kind === 'list' || field.name === 'description_text' ? 'textarea' : 'input';
  let input = '';
  if (field.kind === 'month') {{
    input = `<input data-field-name="${{esc(field.name)}}" data-field-kind="month" type="month" value="${{esc(editorValue(value, field.kind))}}">`;
  }} else if (tag === 'textarea') {{
    input = `<textarea data-field-name="${{esc(field.name)}}" data-field-kind="${{esc(field.kind)}}">${{esc(editorValue(value, field.kind))}}</textarea>`;
  }} else {{
    const extraAttrs = field.kind === 'number' ? (field.name === 'model_year' ? ' min="2004" max="2014"' : (field.name === 'price_eur' || field.name === 'mileage_km' ? ' min="0"' : '')) : '';
    const type = field.kind === 'number' ? 'number' : 'text';
    input = `<input data-field-name="${{esc(field.name)}}" data-field-kind="${{esc(field.kind)}}" type="${{type}}"${{extraAttrs}} value="${{esc(editorValue(value, field.kind))}}">`;
  }}
  return `<div class="field-editor" data-inline-field="${{esc(field.name)}}"><label>${{esc(fieldLabel)}}</label>${{input}}</div>`;
}}
function renderAllFields(item) {{
  return `<details class="listing-fields" open><summary>Alle Werte anzeigen / inline bearbeiten</summary><div class="field-grid">${{fieldRegistry.map(field => inlineEditorValue(field, item)).join('')}}</div><div class="button-row" style="margin-top:16px"><button class="button" onclick="saveAllFields('${{esc(item.id)}}')">Speichern</button></div></details>`;
}}
function changeLabel(type) {{
  const labels = {{'new':'Neu','price_change':'Preis geändert','metadata_change':'Metadaten geändert','manual_override':'Manuell','unchanged':'Unverändert','went_offline':'Offline gegangen','came_online':'Wieder online'}};
  return labels[type] || type;
}}
function fmtDelta(value) {{
  if (value == null) return 'k.A.';
  const sign = value > 0 ? '+' : '';
  return sign + Number(value).toLocaleString('de-DE');
}}
function renderHistorySummary(summary) {{
  if (!summary) return '';
  const first = summary.first_price_eur;
  const current = summary.current_price_eur;
  let deltaHtml = '';
  if (first != null && current != null && first !== 0) {{
    const pct = ((current - first) / first) * 100;
    const cls = pct <= 0 ? 'delta-up' : 'delta-down';
    const sign = pct > 0 ? '+' : '';
    deltaHtml = `<div class="stat"><dt>seit Erstpreis</dt><dd class="${{cls}}">${{sign}}${{pct.toFixed(1)}}%</dd></div>`;
  }}
  return `<div class="history-summary">
    <div class="stat"><dt>Beobachtet seit</dt><dd>${{fmtDateTime(summary.first_seen_at)}}</dd></div>
    <div class="stat"><dt>Preisänderungen</dt><dd>${{summary.price_changes ?? 0}}</dd></div>
    <div class="stat"><dt>Preis min</dt><dd>${{fmtEur(summary.price_min_eur)}}</dd></div>
    <div class="stat"><dt>Preis max</dt><dd>${{fmtEur(summary.price_max_eur)}}</dd></div>
    <div class="stat"><dt>aktuell</dt><dd>${{fmtEur(summary.current_price_eur)}}</dd>
    ${{deltaHtml}}
  </div>`;
}}
function renderPriceChart(series) {{
  if (!series || series.length < 2) return '';
  const prices = series.map(p => p.price_eur).filter(v => v != null);
  if (prices.length < 2) return '';
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = (max - min) || 1;
  const W = 600, H = 150, PAD = 6;
  const pts = series.filter(p => p.price_eur != null).map((p, i, arr) => {{
    const x = PAD + (i / (arr.length - 1)) * (W - 2 * PAD);
    const y = H - PAD - ((p.price_eur - min) / span) * (H - 2 * PAD);
    return x.toFixed(1) + ',' + y.toFixed(1);
  }}).join(' ');
  return `<div class="price-chart"><svg viewBox="0 0 ${{W}} ${{H}}" preserveAspectRatio="none" role="img" aria-label="Preisverlauf">
    <polyline fill="none" stroke="#f87171" stroke-width="2" points="${{pts}}"/>
    <text x="${{W - 4}}" y="${{PAD + 10}}" text-anchor="end" fill="#a1a1aa" font-size="11">${{fmtEur(max)}}</text>
    <text x="${{W - 4}}" y="${{H - PAD - 4}}" text-anchor="end" fill="#a1a1aa" font-size="11">${{fmtEur(min)}}</text>
  </svg></div>`;
}}
function renderHistory(history, onlineHistory, summary, series) {{
  const events = [];
  (history || []).forEach(e => events.push({{
    captured_at: e.captured_at, until_at: e.until_at, change_type: e.change_type,
    price_eur: e.price_eur, mileage_km: e.mileage_km,
    is_collapsed: e.is_collapsed, count: e.count
  }}));
  (onlineHistory || []).forEach(e => events.push({{
    captured_at: e.captured_at, change_type: e.is_online ? 'came_online' : 'went_offline',
    price_eur: null, mileage_km: null, is_collapsed: false
  }}));
  events.sort((a, b) => String(a.captured_at).localeCompare(String(b.captured_at)));
  const reversed = [...events].reverse();
  const rows = reversed.map((row, idx) => {{
    const prev = reversed[idx + 1];
    const prevPrice = prev ? prev.price_eur : null;
    const prevKm = prev ? prev.mileage_km : null;
    const ts = row.until_at
      ? `<span title="${{esc(row.until_at)}}">${{fmtDateTime(row.captured_at)}}</span> <span class="collapsed-hint">bis ${{fmtDateTime(row.until_at)}} (×${{row.count}})</span>`
      : fmtDateTime(row.captured_at);
    if (row.change_type === 'went_offline' || row.change_type === 'came_online') {{
      return `<tr class="online-event"><td>${{ts}}</td><td><span class="change-badge ${{row.change_type}}">${{changeLabel(row.change_type)}}</span></td><td class="muted">—</td><td class="muted">—</td><td class="muted">—</td><td class="muted">—</td></tr>`;
    }}
    let priceDelta = '<td class="muted">—</td>';
    if (row.price_eur != null && prevPrice != null) {{
      const d = row.price_eur - prevPrice;
      priceDelta = d === 0 ? '<td class="muted">±0</td>' : `<td class="${{d > 0 ? 'delta-down' : 'delta-up'}}">${{fmtDelta(d)}} €</td>`;
    }}
    let kmDelta = '<td class="muted">—</td>';
    if (row.mileage_km != null && prevKm != null) {{
      const d = row.mileage_km - prevKm;
      kmDelta = d === 0 ? '<td class="muted">±0</td>' : `<td class="${{d > 0 ? 'delta-down' : 'delta-up'}}">${{fmtDelta(d)}} km</td>`;
    }}
    return `<tr><td>${{ts}}</td><td><span class="change-badge ${{row.change_type}}">${{changeLabel(row.change_type)}}</span></td><td>${{fmtEur(row.price_eur)}}</td>${{priceDelta}}<td>${{fmtKm(row.mileage_km)}}</td>${{kmDelta}}</tr>`;
  }}).join('');
  return `<section class="panel"><h2>Verlauf</h2>${{renderHistorySummary(summary)}}${{renderPriceChart(series)}}<table class="history-table"><thead><tr><th>Zeit</th><th>Änderung</th><th>Preis</th><th>Δ Preis</th><th>km</th><th>Δ km</th></tr></thead><tbody>${{rows || '<tr><td colspan="6">Noch kein Verlauf.</td></tr>'}}</tbody></table></section>`;
}}
async function renderDetailPage(item) {{
  const grid = document.getElementById('listings');
  grid.classList.remove('grid');
  grid.innerHTML = '<p class="muted">Lade Details...</p>';
  const response = await fetch('/api/listings/' + encodeURIComponent(item.id) + '/history');
  const payload = response.ok ? await response.json() : {{history: []}};
  const detailFields = renderAllFields(item);
  const groupMembers = item.cluster_id ? currentListings.filter(l => l.cluster_id === item.cluster_id) : [item];
  let groupPanel = '';
  if (groupMembers.length > 1) {{
    groupPanel = `<section class="panel"><h2>Angebote dieser Gruppe</h2><select id="offer-switch" onchange="switchOffer(this.value)">${{groupMembers.map(member => `<option value="${{esc(member.id)}}" ${{member.id === item.id ? 'selected' : ''}}>${{esc(member.source)}} · ${{fmtEur(member.price_eur)}} · ${{statusLabel(getStatus(member.id))}}</option>`).join('')}}</select><p class="offer-links muted">${{groupMembers.map(m => '<a href="' + esc(m.url || ('/car/' + m.id)) + '" target="_blank" rel="noreferrer">' + esc(m.source) + ' · ' + fmtEur(m.price_eur) + '</a>').join(' · ')}}</p></section>`;
  }}
  const mergeButtons = [];
  mergeButtons.push(`<button class="button secondary" onclick="toggleMergePicker('${{esc(item.id)}}')">Mit Angebot mergen</button>`);
  if (item.cluster_id && item.cluster_id.startsWith('manual_')) {{
    mergeButtons.push(`<button class="button secondary" onclick="unmergeOffer('${{esc(item.id)}}')">Vom Cluster trennen</button>`);
  }}
  const mergeButtonsHtml = mergeButtons.join('');
  grid.innerHTML = `${{groupPanel}}${{renderHistory(payload.history, payload.online_history || [], payload.summary, payload.series)}}<article class="card detail-card" data-detail-page data-id="${{esc(item.id)}}"><div class="body"><div class="button-row"><a class="button" href="/" onclick="openOverview(event)">← Zur Übersicht</a><button class="button secondary" onclick="reScrapeOffer('${{esc(item.id)}}')">Neu scrapen</button>${{mergeButtonsHtml}}</div><p class="muted">${{esc(item.source)}} · Score ${{esc(item.score)}} · ${{esc(item.change_type || 'unbekannt')}}</p><h2>${{esc(item.title)}}</h2><p class="price">${{fmtEur(item.price_eur)}}</p><dl class="overview-specs">${{overviewSpec('Trim', item.trim || 'k.A.')}}${{overviewSpec('Getriebe', item.transmission || 'k.A.')}}${{overviewSpec('km', fmtKm(item.mileage_km))}}${{overviewSpec('Motor', item.engine || item.probable_engine || 'k.A.')}}</dl>${{detailFields}}</div></article>`;
}}
function switchOffer(id) {{
  history.pushState({{id: id}}, '', '/car/' + encodeURIComponent(id));
  renderRoute();
}}
function toggleMergePicker(currentId) {{
  const picker = document.getElementById('merge-picker');
  if (picker) {{
    picker.remove();
    return;
  }}
  const current = currentListings.find(item => item.id === currentId);
  if (!current) return;
  const candidates = currentListings.filter(item => item.id !== currentId && (!current.cluster_id || item.cluster_id !== current.cluster_id));
  if (candidates.length === 0) {{
    alert('Keine anderen Angebote zum Mergen vorhanden.');
    return;
  }}
  const rows = candidates.map(candidate => {{
    const maxPrice = Math.max(current.price_eur || 0, candidate.price_eur || 0);
    const priceDiff = maxPrice > 0 ? Math.abs((current.price_eur || 0) - (candidate.price_eur || 0)) / maxPrice : 0;
    const maxKm = Math.max(current.mileage_km || 0, candidate.mileage_km || 0);
    const kmDiff = maxKm > 0 ? Math.abs((current.mileage_km || 0) - (candidate.mileage_km || 0)) / maxKm : 0;
    const priceWarn = priceDiff > 0.2 ? ' <span class="muted">(Preis weicht stark ab)</span>' : '';
    const kmWarn = kmDiff > 0.2 ? ' <span class="muted">(km weicht stark ab)</span>' : '';
    return `<div style="display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid var(--line)"><span>${{esc(candidate.source)}} · ${{esc(candidate.title)}} · ${{fmtEur(candidate.price_eur)}} · ${{statusLabel(getStatus(candidate.id))}}${{priceWarn}}${{kmWarn}}</span><button class="button secondary" onclick="mergeOffers('${{esc(currentId)}}','${{esc(candidate.id)}}')">Mergen</button></div>`;
  }}).join('');
  const html = `<div id="merge-picker" class="panel"><h2>Angebot mergen</h2>${{rows}}</div>`;
  const buttonRow = document.querySelector('.button-row');
  const detailCard = document.querySelector('.detail-card');
  const insertTarget = buttonRow || detailCard || document.getElementById('listings');
  insertTarget.insertAdjacentHTML('afterend', html);
  const pickerEl = document.getElementById('merge-picker');
  if (pickerEl) pickerEl.scrollIntoView({{behavior: 'smooth', block: 'nearest'}});
}}
async function mergeOffers(aId, bId) {{
  const response = await fetch('/api/merge', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{listing_ids:[aId,bId]}})}});
  if (response.ok) {{
    window.location.reload();
  }} else {{
    alert(JSON.stringify(await response.json()));
  }}
}}
async function unmergeOffer(id) {{
  const response = await fetch('/api/unmerge', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{listing_id:id}})}});
  if (response.ok) {{
    window.location.reload();
  }} else {{
    alert(JSON.stringify(await response.json()));
  }}
}}
function renderOverviewPage() {{
  const grid = document.getElementById('listings');
  grid.classList.add('grid');
  
  // Apply all filters
  const statusFilter = document.getElementById('status-filter').value;
  const textQuery = (document.getElementById('text-search').value || '').toLowerCase().trim();
  const ezFrom = (document.getElementById('ez-from').value || '').trim();
  const ezTo = (document.getElementById('ez-to').value || '').trim();
  const sourceFilter = document.getElementById('source-filter').value;
  const transmissionFilter = document.getElementById('transmission-filter').value;
  const trimFilter = document.getElementById('trim-filter').value;
  const engineFilter = document.getElementById('engine-filter').value;
  const bodyFilter = document.getElementById('body-filter').value;
  const changeFilter = document.getElementById('change-filter').value;
  const priceMin = parseFloat(document.getElementById('price-min').value) || 0;
  const priceMax = parseFloat(document.getElementById('price-max').value) || 0;
  const kmMin = parseFloat(document.getElementById('km-min').value) || 0;
  const kmMax = parseFloat(document.getElementById('km-max').value) || 0;
  const scoreMin = parseInt(document.getElementById('score-min').value) || 0;
  const hideRisk = document.getElementById('hide-risk').checked;
  
  let filtered = currentListings.filter(item => {{
    // Status filter
    if (statusFilter !== 'all') {{
      const st = getStatus(item.id);
      if (st !== statusFilter) return false;
    }}
    // Text search across title, description, source, engine, trim
    if (textQuery) {{
      const haystack = [
        item.title, item.description_text, item.source,
        item.engine, item.probable_engine, item.trim,
        item.transmission, item.body_style
      ].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(textQuery)) return false;
    }}
    // EZ year range
    if (ezFrom || ezTo) {{
      const yr = (item.first_registration || '').substring(0, 4);
      if (ezFrom && yr < ezFrom) return false;
      if (ezTo && yr > ezTo) return false;
    }}
    // Source filter
    if (sourceFilter !== 'all' && item.source !== sourceFilter) return false;
    // Transmission filter
    if (transmissionFilter !== 'all' && item.transmission !== transmissionFilter) return false;
    // Trim filter (match by name, handle null)
    if (trimFilter !== 'all' && (item.trim || '') !== trimFilter) return false;
    // Engine filter (check both engine and probable_engine)
    if (engineFilter !== 'all') {{
      const eng = (item.engine || item.probable_engine || '');
      if (eng !== engineFilter) return false;
    }}
    // Body style filter
    if (bodyFilter !== 'all' && item.body_style !== bodyFilter) return false;
    // Change type filter
    if (changeFilter !== 'all' && item.change_type !== changeFilter) return false;
    // Price range
    if (priceMin > 0 && (item.price_eur == null || item.price_eur < priceMin)) return false;
    if (priceMax > 0 && (item.price_eur == null || item.price_eur > priceMax)) return false;
    // Km range
    if (kmMin > 0 && (item.mileage_km == null || item.mileage_km < kmMin)) return false;
    if (kmMax > 0 && (item.mileage_km == null || item.mileage_km > kmMax)) return false;
    // Score minimum
    if (scoreMin > 0 && (item.score == null || item.score < scoreMin)) return false;
    // Hide risk — skip items with any risk_flag
    if (hideRisk && item.risk_flags && item.risk_flags.length > 0) return false;
    return true;
  }});
  
  const groups = groupListings(filtered);
  const primaries = groups.map(g => g.primary);
  const sortedPrimaries = sortListings(primaries);
  const groupByPrimaryId = new Map(groups.map(g => [g.primary.id, g]));
  grid.innerHTML = sortedPrimaries.map(item => {{
    const group = groupByPrimaryId.get(item.id);
    return renderOverviewCard(item, group);
  }}).join('') || '<p class="muted">Keine Treffer f&uuml;r diese Filter.</p>';
  document.getElementById('visible-count').textContent = sortedPrimaries.length + ' von ' + currentListings.length + ' Angeboten';
}}
function currentDetailId() {{
  const match = window.location.pathname.match(new RegExp('^/car/(.+)$'));
  return match ? decodeURIComponent(match[1]) : null;
}}
function renderRoute() {{
  const detailId = currentDetailId();
  const filterBar = document.getElementById('filter-bar');
  if (detailId) {{
    if (filterBar) filterBar.style.display = 'none';
    const item = currentListings.find(candidate => candidate.id === detailId);
    if (!item) {{ document.getElementById('listings').innerHTML = '<p class="muted">Listing nicht gefunden.</p>'; return; }}
    renderDetailPage(item);
    return;
  }}
  if (filterBar) filterBar.style.display = '';
  renderOverviewPage();
}}
function openDetail(event, id) {{
  event.preventDefault();
  history.pushState({{id}}, '', '/car/' + encodeURIComponent(id));
  renderRoute();
}}
function openOverview(event) {{
  event.preventDefault();
  history.pushState({{}}, '', '/');
  renderRoute();
}}
async function saveAllFields(id) {{
  const fields = {{}};
  document.querySelectorAll('.detail-card [data-field-name]').forEach(input => {{
    const name = input.dataset.fieldName;
    const kind = input.dataset.fieldKind || 'text';
    try {{
      fields[name] = parseEditorValue(input.value, kind);
    }} catch (error) {{
      document.getElementById('status').textContent = `${{name}} enthält ungültige Daten`;
    }}
  }});
  let validationError = null;
  document.querySelectorAll('.detail-card [data-field-name]').forEach(input => {{
    const name = input.dataset.fieldName;
    const kind = input.dataset.fieldKind || 'text';
    if (kind === 'month' && input.value && !/^\\d{{4}}-\\d{{2}}$/.test(input.value)) {{
      validationError = 'Datum muss das Format JJJJ-MM haben (z.B. 2008-06)';
    }}
    if (name === 'model_year' && input.value && (Number(input.value) < 2004 || Number(input.value) > 2014)) {{
      validationError = 'model_year muss zwischen 2004 und 2014 liegen';
    }}
  }});
  if (validationError) {{
    document.getElementById('status').textContent = validationError;
    return;
  }}
  const keys = Object.keys(fields);
  if (keys.length === 0) {{ document.getElementById('status').textContent = 'Keine Felder zum Speichern.'; return; }}
  const response = await fetch('/api/listings/' + encodeURIComponent(id), {{method:'PATCH', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(fields)}});
  if (!response.ok) {{ document.getElementById('status').textContent = 'Speichern fehlgeschlagen: ' + (await response.text()); return; }}
  document.getElementById('status').textContent = keys.length + ' Feld(er) gespeichert';
  await loadListings();
}}
async function reScrapeOffer(id) {{
  const statusEl = document.getElementById('status');
  statusEl.textContent = 'Scrape läuft...';
  const response = await fetch('/api/re-scrape', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{offer_id: id}}),
  }});
  const result = await response.json();
  if (result.success) {{
    statusEl.textContent = '✓ ' + (result.message || 'Angebot neu gescraped');
  }} else {{
    statusEl.textContent = '✗ ' + (result.message || 'Scrape fehlgeschlagen');
  }}
  await loadListings();
}}
function resetFilters() {{
    ['text-search','ez-from','ez-to','price-min','price-max','km-min','km-max'].forEach(id => {{
        const el = document.getElementById(id);
        if (el) el.value = '';
    }});
    ['status-filter','source-filter','transmission-filter','trim-filter','engine-filter','body-filter','listing-sort','change-filter'].forEach(id => {{
        const el = document.getElementById(id);
        if (el) el.value = 'all';
    }});
    const scoreSlider = document.getElementById('score-min');
    if (scoreSlider) {{
        scoreSlider.value = '0';
        const scoreValue = document.getElementById('score-value');
        if (scoreValue) scoreValue.textContent = '0';
    }}
    const hideRisk = document.getElementById('hide-risk');
    if (hideRisk) hideRisk.checked = false;
    renderListings();
}}
document.getElementById('reset-filters').addEventListener('click', resetFilters);
document.getElementById('listing-sort').addEventListener('change', renderListings);
document.getElementById('status-filter').addEventListener('change', renderListings);
document.getElementById('text-search').addEventListener('input', renderListings);
document.getElementById('ez-from').addEventListener('input', renderListings);
document.getElementById('ez-to').addEventListener('input', renderListings);
document.getElementById('source-filter').addEventListener('change', renderListings);
document.getElementById('transmission-filter').addEventListener('change', renderListings);
document.getElementById('trim-filter').addEventListener('change', renderListings);
document.getElementById('engine-filter').addEventListener('change', renderListings);
document.getElementById('body-filter').addEventListener('change', renderListings);
document.getElementById('change-filter').addEventListener('change', renderListings);
document.getElementById('price-min').addEventListener('input', renderListings);
document.getElementById('price-max').addEventListener('input', renderListings);
document.getElementById('km-min').addEventListener('input', renderListings);
document.getElementById('km-max').addEventListener('input', renderListings);
document.getElementById('score-min').addEventListener('input', function() {{
  document.getElementById('score-value').textContent = this.value;
  renderListings();
}});
document.getElementById('hide-risk').addEventListener('change', renderListings);
window.addEventListener('popstate', renderRoute);
document.getElementById('run').addEventListener('click', async () => {{
  document.getElementById('status').textContent = 'Crawl läuft...';
  const response = await fetch('/api/run', {{method:'POST'}});
  const payload = await response.json();
  document.getElementById('status').textContent = `Crawl fertig: ${{payload.summary?.total_active ?? 0}} Treffer`;
  updateLastCrawl(payload.last_crawl_at);
  await loadListings();
}});
loadStatus();
loadListings();
</script>
</body>
</html>"""


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

    _RETRIABLE_SQLITE_ERRORS = ("database is locked", "is not unique",
                                "UNIQUE constraint", "no such table")

    def _robust_check() -> None:
        for attempt in range(3):
            try:
                summary = check_stale_offers(app.store)
                print(f"Health check: {summary['checked']} checked, {summary['skipped']} skipped, "
                      f"{summary['online']} online, {summary['offline']} offline, "
                      f"{summary['failed']} failed, {summary['total']} total")
                return
            except Exception as exc:
                msg = str(exc)
                if any(e in msg for e in _RETRIABLE_SQLITE_ERRORS) and attempt < 2:
                    time.sleep(2 ** attempt)
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
    database_path = Path(os.getenv("CORVETTE_TRACKER_DATABASE", str(output_dir / "data" / "corvette_tracker.sqlite")))
    configured_path = os.getenv("CORVETTE_TRACKER_CONFIG", "/app/config.yaml")
    config_path = Path(configured_path) if configured_path else output_dir / "config.yaml"

    from .cli import run_tracker

    def run_callback() -> tuple[int, dict[str, Any]]:
        return run_tracker(str(config_path) if config_path.exists() else None, output_dir=output_dir, database=database_path)

    store = TrackerStore(database_path)
    app = TrackerWebApp(store=store, output_dir=output_dir, run_callback=run_callback, config_path=config_path)

    if os.getenv("CORVETTE_TRACKER_RUN_ON_START", "true").lower() in {"1", "true", "yes", "on"}:
        threading.Thread(target=app.run_once, name="corvette-tracker-initial-run", daemon=True).start()

    interval = parse_interval_seconds(os.getenv("CORVETTE_TRACKER_CRON_INTERVAL", "6h"))
    if interval is not None:
        _start_scheduler(app, interval)
        print(f"Scheduled crawl interval: {interval}s")
    else:
        print("Scheduled crawl disabled")

    health_interval = parse_interval_seconds(os.getenv("CORVETTE_TRACKER_HEALTH_INTERVAL", "5m"))
    if health_interval is not None:
        _start_health_scheduler(app, health_interval)
        print(f"Scheduled health check interval: {health_interval}s")

    server = app.make_server(host, port)
    print(f"Corvette Tracker WebUI listening on http://{host}:{port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
