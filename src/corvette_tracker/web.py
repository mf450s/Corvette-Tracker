from __future__ import annotations

import html
import json
import os
import threading
import time
from dataclasses import fields
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

import yaml

from .feed import build_feed_payload, format_eur, format_km, write_exports
from .models import Listing
from .scoring import apply_score, apply_scores, merge_scoring_config
from .storage import EDITABLE_FIELDS, PROTECTED_OVERRIDE_FIELDS, TrackerStore

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
            return 0, payload
        with self.run_lock:
            exit_code, payload = self.run_callback()
            self.last_run = {"exit_code": exit_code, "summary": payload.get("summary", {}), "warnings": payload.get("warnings", [])}
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
            scoring = self.tracker_app.scoring_config()
            listings = [apply_score(listing, scoring).to_dict() for listing in self.tracker_app.store.list_active()]
            self._send_json({"listings": listings, "last_run": self.tracker_app.last_run})
            return
        history_prefix = "/api/listings/"
        history_suffix = "/history"
        if path.startswith(history_prefix) and path.endswith(history_suffix):
            listing_id = unquote(path[len(history_prefix) : -len(history_suffix)])
            if self.tracker_app.store.get_listing(listing_id) is None:
                self._send_json({"error": "listing not found"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json({"listing_id": listing_id, "history": self.tracker_app.store.listing_history(listing_id)})
            return
        if path == "/api/scoring":
            self._send_json({"scoring": self.tracker_app.scoring_config()})
            return
        if path == "/api/status":
            self._send_json({"last_run": self.tracker_app.last_run, "total_active": len(self.tracker_app.store.list_active())})
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/run":
            exit_code, payload = self.tracker_app.run_once()
            status = HTTPStatus.OK if exit_code in {0, 2} else HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json({"exit_code": exit_code, "summary": payload.get("summary", {}), "warnings": payload.get("warnings", [])}, status)
            return
        if path == "/api/scoring":
            try:
                scoring = self.tracker_app.update_scoring_config(self._read_json_body())
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"scoring": scoring})
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
    numeric_fields = {"price_eur", "mileage_km", "power_hp", "estimated_power_hp", "engine_confidence", "origin_confidence", "score", "previous_price_eur"}
    boolean_fields = {"eu_spec", "has_damage"}
    list_fields = {"equipment", "visual_flags", "image_urls", "risk_flags", "inference_notes", "conflict_flags"}
    dict_fields = {"ai_enrichment"}
    field_registry = [
        {
            "name": field.name,
            "editable": field.name in EDITABLE_FIELDS,
            "protected": field.name in PROTECTED_OVERRIDE_FIELDS,
            "kind": "number" if field.name in numeric_fields else "boolean" if field.name in boolean_fields else "list" if field.name in list_fields else "json" if field.name in dict_fields else "text",
        }
        for field in fields(Listing)
    ]
    field_registry_attr = html.escape(json.dumps(field_registry, ensure_ascii=False), quote=True)
    field_registry_js = json.dumps(field_registry, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Corvette Tracker WebUI</title>
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
    .status {{ min-height:1.4em; }}
  </style>
</head>
<body>
  <header>
    <p class="muted">Frontend + Backend laufen zusammen im Container</p>
    <h1>Corvette Tracker WebUI</h1>
    <p class="muted">Manuelle Nachbesserungen werden als Overrides gespeichert und bei späteren Crawls nicht überschrieben.</p>
    <div class="toolbar"><button id="run">Jetzt crawlen</button><span id="status" class="status muted"></span></div>
  </header>
  <main class="wrap"><section class="panel"><h2>Scoring konfigurieren</h2><p class="muted">Standard: Schalter sehr wichtig, kein Cabrio wichtig, kein LS2 wichtig, Trim mittel. Werte werden in config.yaml gespeichert.</p><form id="scoring-form" class="score-form"><label>Schalter<input name="manual_transmission" type="number" min="0" max="100" data-score-weight="manual_transmission"></label><label>Kein Cabrio<input name="non_convertible" type="number" min="0" max="100" data-score-weight="non_convertible"></label><label>Kein LS2<input name="non_ls2" type="number" min="0" max="100" data-score-weight="non_ls2"></label><label>Trim<input name="preferred_trim" type="number" min="0" max="100" data-score-weight="preferred_trim"></label><label>Trims<input name="preferred_trims" placeholder="Grand Sport, Z06, ZR1"></label><button>Scoring speichern</button></form></section><section class="panel list-toolbar"><div><h2>Listings</h2><p class="muted">Sortierung basiert auf dem aktuellen Scoring.</p></div><label class="muted">Sortierung<select id="listing-sort"><option value="score-desc">Score hoch</option><option value="score-asc">Score niedrig</option><option value="price-asc">Preis niedrig</option><option value="price-desc">Preis hoch</option></select></label></section><div id="listings" class="grid"></div></main>
<script data-field-registry="{field_registry_attr}">
const fieldRegistry = {field_registry_js};
let currentListings = [];
function esc(value) {{ return String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[c])); }}
function fmtEur(value) {{ return value == null ? 'k.A.' : Number(value).toLocaleString('de-DE') + ' €'; }}
function fmtKm(value) {{ return value == null ? 'k.A.' : Number(value).toLocaleString('de-DE') + ' km'; }}
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
  if (kind === 'json') return JSON.stringify(value, null, 2);
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}}
function parseEditorValue(raw, kind) {{
  if (raw === '') return null;
  if (kind === 'number') return Number(raw);
  if (kind === 'boolean') return raw === 'true' ? true : raw === 'false' ? false : null;
  if (kind === 'list') return raw.split(',').map(value => value.trim()).filter(Boolean);
  if (kind === 'json') return JSON.parse(raw);
  return raw;
}}
async function loadScoring() {{
  const response = await fetch('/api/scoring');
  const payload = await response.json();
  const scoring = payload.scoring || {{}};
  const weights = scoring.weights || {{}};
  document.querySelectorAll('[data-score-weight]').forEach(input => input.value = weights[input.dataset.scoreWeight] ?? 0);
  document.querySelector('#scoring-form [name="preferred_trims"]').value = (scoring.preferred_trims || []).join(', ');
}}
async function loadListings() {{
  const response = await fetch('/api/listings');
  const payload = await response.json();
  currentListings = payload.listings || [];
  document.getElementById('status').textContent = `${{currentListings.length}} aktive Treffer`;
  renderListings();
}}
function sortListings(listings) {{
  const order = document.getElementById('listing-sort').value;
  return [...listings].sort((a, b) => {{
    if (order === 'score-asc') return Number(a.score || 0) - Number(b.score || 0);
    if (order === 'price-asc') return Number(a.price_eur || 999999999) - Number(b.price_eur || 999999999);
    if (order === 'price-desc') return Number(b.price_eur || 0) - Number(a.price_eur || 0);
    return Number(b.score || 0) - Number(a.score || 0);
  }});
}}
function renderListings() {{
  renderRoute();
}}
function overviewSpec(label, value) {{ return `<div><dt>${{esc(label)}}</dt><dd>${{esc(displayValue(value))}}</dd></div>`; }}
function renderOverviewCard(item) {{
  const image = (item.image_urls || [])[0];
  const detailUrl = '/car/' + encodeURIComponent(item.id);
  const offerUrl = item.url || detailUrl;
  return `<article class="card" data-overview-card data-id="${{esc(item.id)}}">
    <a class="image" href="${{esc(offerUrl)}}" target="_blank" rel="noreferrer"><span class="score-badge">${{esc(item.score ?? 0)}}%</span>${{image ? `<img src="${{esc(image)}}" alt="">` : ''}}</a>
    <div class="body">
      <p class="muted">${{esc(item.source)}} · Score ${{esc(item.score)}} · ${{esc(item.change_type || 'unbekannt')}}</p>
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
    </div>
  </article>`;
}}
function renderInlineEditor(field, item) {{
  const value = item[field.name];
  if (!field.editable) return `<div class="field-editor readonly-field"><span>${{esc(field.name)}}</span><strong>${{esc(displayValue(value))}}</strong></div>`;
  if (field.kind === 'boolean') {{
    return `<div class="field-editor" data-inline-field="${{esc(field.name)}}"><label>${{esc(field.name)}}</label><form onsubmit="saveInlineField(event, '${{esc(item.id)}}', '${{esc(field.name)}}', '${{esc(field.kind)}}')"><select name="value"><option value="" ${{value == null ? 'selected' : ''}}>k.A.</option><option value="true" ${{value === true ? 'selected' : ''}}>ja</option><option value="false" ${{value === false ? 'selected' : ''}}>nein</option></select><button>OK</button></form></div>`;
  }}
  const tag = field.kind === 'json' || field.kind === 'list' || field.name === 'description_text' ? 'textarea' : 'input';
  const input = tag === 'textarea'
    ? `<textarea name="value">${{esc(editorValue(value, field.kind))}}</textarea>`
    : `<input name="value" type="${{field.kind === 'number' ? 'number' : 'text'}}" value="${{esc(editorValue(value, field.kind))}}">`;
  return `<div class="field-editor" data-inline-field="${{esc(field.name)}}"><label>${{esc(field.name)}}</label><form onsubmit="saveInlineField(event, '${{esc(item.id)}}', '${{esc(field.name)}}', '${{esc(field.kind)}}')">${{input}}<button>OK</button></form></div>`;
}}
function renderAllFields(item) {{
  return `<details class="listing-fields" open><summary>Alle Werte anzeigen / inline bearbeiten</summary><div class="field-grid">${{fieldRegistry.map(field => renderInlineEditor(field, item)).join('')}}</div></details>`;
}}
function renderHistory(history) {{
  const rows = (history || []).map(row => `<tr><td>${{esc(row.captured_at)}}</td><td>${{esc(row.change_type)}}</td><td>${{fmtEur(row.price_eur)}}</td><td>${{fmtKm(row.mileage_km)}}</td></tr>`).join('');
  return `<section class="panel"><h2>Verlauf</h2><table class="history-table"><thead><tr><th>Zeit</th><th>Änderung</th><th>Preis</th><th>km</th></tr></thead><tbody>${{rows || '<tr><td colspan="4">Noch kein Verlauf.</td></tr>'}}</tbody></table></section>`;
}}
async function renderDetailPage(item) {{
  const grid = document.getElementById('listings');
  grid.classList.remove('grid');
  grid.innerHTML = '<p class="muted">Lade Details...</p>';
  const response = await fetch('/api/listings/' + encodeURIComponent(item.id) + '/history');
  const payload = response.ok ? await response.json() : {{history: []}};
  const detailFields = renderAllFields(item);
  grid.innerHTML = `<article class="card detail-card" data-detail-page data-id="${{esc(item.id)}}"><div class="body"><a class="button" href="/" onclick="openOverview(event)">← Zur Übersicht</a><p class="muted">${{esc(item.source)}} · Score ${{esc(item.score)}} · ${{esc(item.change_type || 'unbekannt')}}</p><h2>${{esc(item.title)}}</h2><p class="price">${{fmtEur(item.price_eur)}}</p><dl class="overview-specs">${{overviewSpec('Trim', item.trim || 'k.A.')}}${{overviewSpec('Getriebe', item.transmission || 'k.A.')}}${{overviewSpec('km', fmtKm(item.mileage_km))}}${{overviewSpec('Motor', item.engine || item.probable_engine || 'k.A.')}}</dl>${{detailFields}}</div></article>${{renderHistory(payload.history)}}`;
}}
function renderOverviewPage() {{
  const grid = document.getElementById('listings');
  grid.classList.add('grid');
  const sorted = sortListings(currentListings);
  grid.innerHTML = sorted.map(item => renderOverviewCard(item)).join('') || '<p class="muted">Noch keine Listings. Starte einen Crawl.</p>';
}}
function currentDetailId() {{
  const match = window.location.pathname.match(new RegExp('^/car/(.+)$'));
  return match ? decodeURIComponent(match[1]) : null;
}}
function renderRoute() {{
  const detailId = currentDetailId();
  if (detailId) {{
    const item = currentListings.find(candidate => candidate.id === detailId);
    if (!item) {{ document.getElementById('listings').innerHTML = '<p class="muted">Listing nicht gefunden.</p>'; return; }}
    renderDetailPage(item);
    return;
  }}
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
async function saveInlineField(event, id, field, kind) {{
  event.preventDefault();
  const form = event.target;
  let value;
  try {{
    value = parseEditorValue(form.value.value, kind);
  }} catch (error) {{
    document.getElementById('status').textContent = `${{field}} enthält ungültiges JSON`;
    return;
  }}
  const response = await fetch('/api/listings/' + encodeURIComponent(id), {{method:'PATCH', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{[field]: value}})}});
  if (!response.ok) {{ document.getElementById('status').textContent = 'Speichern fehlgeschlagen: ' + (await response.text()); return; }}
  document.getElementById('status').textContent = `${{field}} gespeichert`;
  await loadListings();
}}
document.getElementById('scoring-form').addEventListener('submit', async event => {{
  event.preventDefault();
  const form = event.target;
  const weights = {{}};
  form.querySelectorAll('[data-score-weight]').forEach(input => weights[input.dataset.scoreWeight] = Number(input.value || 0));
  const preferredTrims = form.preferred_trims.value.split(',').map(value => value.trim()).filter(Boolean);
  const response = await fetch('/api/scoring', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{weights, preferred_trims: preferredTrims}})}});
  if (!response.ok) {{ document.getElementById('status').textContent = 'Scoring speichern fehlgeschlagen: ' + (await response.text()); return; }}
  document.getElementById('status').textContent = 'Scoring gespeichert';
  await loadScoring();
  await loadListings();
}});
document.getElementById('listing-sort').addEventListener('change', renderListings);
window.addEventListener('popstate', renderRoute);
document.getElementById('run').addEventListener('click', async () => {{
  document.getElementById('status').textContent = 'Crawl läuft...';
  const response = await fetch('/api/run', {{method:'POST'}});
  const payload = await response.json();
  document.getElementById('status').textContent = `Crawl fertig: ${{payload.summary?.total_active ?? 0}} Treffer`;
  await loadListings();
}});
loadScoring();
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

    server = app.make_server(host, port)
    print(f"Corvette Tracker WebUI listening on http://{host}:{port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
