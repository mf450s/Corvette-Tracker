from __future__ import annotations

import html
import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from .feed import build_feed_payload, format_eur, format_km, write_exports
from .models import Listing
from .storage import TrackerStore

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
    def __init__(self, store: TrackerStore, output_dir: str | Path, run_callback: RunCallback | None = None):
        self.store = store
        self.output_dir = Path(output_dir)
        self.run_callback = run_callback
        self.last_run: dict[str, Any] | None = None
        self.run_lock = threading.Lock()

    def make_server(self, host: str, port: int) -> ThreadingHTTPServer:
        app = self

        class Handler(TrackerRequestHandler):
            tracker_app = app

        return ThreadingHTTPServer((host, port), Handler)

    def refresh_exports(self) -> dict[str, Any]:
        payload = build_feed_payload(self.store.list_active())
        write_exports(payload, self.output_dir)
        source = self.output_dir / "site" / "index.html"
        if source.exists():
            (self.output_dir / "index.html").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return payload

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
        if path == "/api/listings":
            self._send_json({"listings": [listing.to_dict() for listing in self.tracker_app.store.list_active()], "last_run": self.tracker_app.last_run})
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
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
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
    editable_fields = [
        "title",
        "price_eur",
        "price_label",
        "mileage_km",
        "engine",
        "probable_engine",
        "power_hp",
        "trim",
        "transmission",
        "body_style",
        "first_registration",
        "tuv_until",
        "location_raw",
        "seller_type",
        "accident_status",
        "damage",
        "description_text",
    ]
    options = "".join(f'<option value="{html.escape(field)}">{html.escape(field)}</option>' for field in editable_fields)
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
    .muted {{ color:var(--muted); }} .toolbar {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:16px; }} .card {{ border:1px solid var(--line); border-radius:18px; background:var(--card); overflow:hidden; }}
    .image {{ aspect-ratio:16/9; background:#18181b; display:block; }} .image img {{ width:100%; height:100%; object-fit:cover; }} .body {{ padding:16px; }}
    h2 {{ margin:0 0 8px; font-size:20px; }} .price {{ font-size:26px; font-weight:800; margin:0 0 10px; }}
    dl {{ display:grid; grid-template-columns:repeat(2,1fr); gap:8px; }} dl div {{ border:1px solid var(--line); border-radius:12px; padding:8px; }} dt {{ color:var(--muted); font-size:12px; }} dd {{ margin:3px 0 0; font-weight:700; }}
    form {{ display:grid; gap:8px; margin-top:14px; grid-template-columns:1fr 1fr auto; }} select,input {{ min-width:0; border:1px solid var(--line); border-radius:10px; padding:10px; background:#09090b; color:var(--text); }}
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
  <main class="wrap"><div id="listings" class="grid"></div></main>
<script>
const editableOptions = `{options}`;
function esc(value) {{ return String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[c])); }}
function fmtEur(value) {{ return value == null ? 'k.A.' : Number(value).toLocaleString('de-DE') + ' €'; }}
function fmtKm(value) {{ return value == null ? 'k.A.' : Number(value).toLocaleString('de-DE') + ' km'; }}
function fieldValue(item, name) {{ const value = item[name]; return Array.isArray(value) ? value.join(', ') : (value ?? ''); }}
async function loadListings() {{
  const response = await fetch('/api/listings');
  const payload = await response.json();
  document.getElementById('status').textContent = `${{payload.listings.length}} aktive Treffer`;
  document.getElementById('listings').innerHTML = payload.listings.map(item => renderCard(item)).join('') || '<p class="muted">Noch keine Listings. Starte einen Crawl.</p>';
}}
function renderCard(item) {{
  const image = (item.image_urls || [])[0];
  return `<article class="card" data-id="${{esc(item.id)}}">
    <a class="image" href="${{esc(item.url)}}" target="_blank" rel="noreferrer">${{image ? `<img src="${{esc(image)}}" alt="">` : ''}}</a>
    <div class="body">
      <p class="muted">${{esc(item.source)}} · Score ${{esc(item.score)}}</p>
      <h2>${{esc(item.title)}}</h2>
      <p class="price">${{fmtEur(item.price_eur)}}</p>
      <dl><div><dt>Motor</dt><dd>${{esc(item.engine || item.probable_engine || 'k.A.')}}</dd></div><div><dt>km</dt><dd>${{fmtKm(item.mileage_km)}}</dd></div><div><dt>Getriebe</dt><dd>${{esc(item.transmission || 'k.A.')}}</dd></div><div><dt>Ort</dt><dd>${{esc(item.location_raw || 'k.A.')}}</dd></div></dl>
      <form onsubmit="saveOverride(event, '${{esc(item.id)}}')"><select name="field">${{editableOptions}}</select><input name="value" placeholder="Neuer Wert"><button>Speichern</button></form>
      <p class="muted">Aktueller Feldwert wird überschrieben und bleibt persistent.</p>
      <a class="button" href="${{esc(item.url)}}" target="_blank" rel="noreferrer">Angebot öffnen</a>
    </div>
  </article>`;
}}
async function saveOverride(event, id) {{
  event.preventDefault();
  const form = event.target;
  const field = form.field.value;
  const raw = form.value.value;
  const numeric = new Set(['price_eur','mileage_km','power_hp']);
  const value = numeric.has(field) && raw !== '' ? Number(raw) : raw;
  const response = await fetch('/api/listings/' + encodeURIComponent(id), {{method:'PATCH', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{[field]: value}})}});
  if (!response.ok) {{ document.getElementById('status').textContent = 'Speichern fehlgeschlagen: ' + (await response.text()); return; }}
  document.getElementById('status').textContent = 'Gespeichert';
  await loadListings();
}}
document.getElementById('run').addEventListener('click', async () => {{
  document.getElementById('status').textContent = 'Crawl läuft...';
  const response = await fetch('/api/run', {{method:'POST'}});
  const payload = await response.json();
  document.getElementById('status').textContent = `Crawl fertig: ${{payload.summary?.total_active ?? 0}} Treffer`;
  await loadListings();
}});
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
    config_path = os.getenv("CORVETTE_TRACKER_CONFIG", "/app/config.yaml")
    if config_path and not Path(config_path).exists():
        config_path = ""

    from .cli import run_tracker

    def run_callback() -> tuple[int, dict[str, Any]]:
        return run_tracker(config_path or None, output_dir=output_dir, database=database_path)

    store = TrackerStore(database_path)
    app = TrackerWebApp(store=store, output_dir=output_dir, run_callback=run_callback)

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
