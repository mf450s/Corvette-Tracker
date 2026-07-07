from __future__ import annotations

import csv
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Listing


def format_eur(value: int | None) -> str:
    return "k.A." if value is None else f"{value:,}".replace(",", ".") + " €"


def format_km(value: int | None) -> str:
    return "k.A." if value is None else f"{value:,}".replace(",", ".") + " km"


def engine_display(item: dict[str, Any]) -> str:
    if item.get("engine"):
        return str(item["engine"])
    if item.get("probable_engine"):
        confidence = item.get("engine_confidence")
        suffix = f" ({confidence:.0%})" if isinstance(confidence, int | float) else ""
        return f"wahrscheinlich {item['probable_engine']}{suffix}"
    return "k.A."


def engine_note_display(item: dict[str, Any]) -> str | None:
    note = item.get("engine_note")
    if not note or item.get("engine"):
        return None
    return str(note)


def build_feed_payload(listings: list[Listing]) -> dict[str, Any]:
    ordered = sorted(listings, key=lambda item: (item.score, item.price_eur or 0), reverse=True)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "generated_at": generated_at,
        "summary": {
            "total_active": len(ordered),
            "new_listings": sum(1 for item in ordered if item.change_type == "new"),
            "changed_listings": sum(1 for item in ordered if item.change_type not in {"new", "unchanged"}),
            "price_changes": sum(1 for item in ordered if item.change_type == "price_change"),
            "risk_warnings": sum(1 for item in ordered if item.risk_flags),
        },
        "listings": [item.to_dict() for item in ordered],
    }


def render_markdown_feed(payload: dict[str, Any]) -> str:
    lines = [
        f"# Neue C6 Corvette-Angebote — {payload['generated_at']}",
        "",
        f"Aktive Treffer: **{payload['summary']['total_active']}** · Neu: **{payload['summary']['new_listings']}** · Preisänderungen: **{payload['summary']['price_changes']}**",
        "",
    ]
    for index, item in enumerate(payload["listings"], start=1):
        lines += [
            f"## {index}. {item['title']} — {format_eur(item.get('price_eur'))}",
            "",
        ]
        if item.get("image_urls"):
            lines += [f"![{item['title']}]({item['image_urls'][0]})", ""]
        engine_note = engine_note_display(item)
        lines += [
            f"- Quelle: {item['source']}",
            f"- Score: {item['score']}/100",
            f"- Variante/Motor: {item.get('trim') or 'k.A.'} / {engine_display(item)}",
        ]
        if engine_note:
            lines.append(f"- Motor-Hinweis: {engine_note}")
        lines += [
            f"- Kilometer: {format_km(item.get('mileage_km'))}",
            f"- EZ: {item.get('first_registration') or 'k.A.'}",
            f"- TÜV/HU: {item.get('tuv_until') or 'k.A.'}",
            f"- Standort: {item.get('location_raw') or 'k.A.'}",
            f"- Unfallstatus: {item.get('accident_status') or 'unbekannt'}",
            f"- Änderung: {item.get('change_type') or 'unbekannt'}",
            f"- Risiko-Flags: {', '.join(item.get('risk_flags') or []) or 'keine'}",
            f"- Link: {item['url']}",
            "",
        ]
    if not payload["listings"]:
        lines.append("Keine C6-Corvette-Angebote gefunden oder Quellen waren blockiert.")
    return "\n".join(lines).rstrip() + "\n"


def render_html_site(payload: dict[str, Any]) -> str:
    cards = []
    for item in payload["listings"]:
        title = html.escape(item["title"])
        image = html.escape((item.get("image_urls") or [""])[0])
        risk = ", ".join(item.get("risk_flags") or []) or "keine"
        img_html = f'<img src="{image}" alt="{title}" loading="lazy">' if image else '<div class="placeholder">Kein Bild</div>'
        engine_text = html.escape(engine_display(item))
        engine_note = engine_note_display(item)
        engine_note_html = f'<p class="engine-note">{html.escape(engine_note)}</p>' if engine_note else ""
        cards.append(f'''
        <article class="card" data-listing-card data-trim="{html.escape(str(item.get('trim') or 'unknown'))}" data-risk="{'yes' if item.get('risk_flags') else 'no'}">
          <a class="image" href="{html.escape(item['url'])}" target="_blank" rel="noreferrer">{img_html}</a>
          <div class="card-body">
            <div class="meta"><span>{html.escape(item['source'])}</span><span>Score {item['score']}/100</span></div>
            <h2>{title}</h2>
            <p class="price">{format_eur(item.get('price_eur'))}</p>
            <dl>
              <div><dt>km</dt><dd>{format_km(item.get('mileage_km'))}</dd></div>
              <div><dt>Motor</dt><dd>{engine_text}</dd></div>
              <div><dt>Variante</dt><dd>{html.escape(str(item.get('trim') or 'k.A.'))}</dd></div>
              <div><dt>EZ</dt><dd>{html.escape(str(item.get('first_registration') or 'k.A.'))}</dd></div>
              <div><dt>TÜV</dt><dd>{html.escape(str(item.get('tuv_until') or 'k.A.'))}</dd></div>
              <div><dt>Ort</dt><dd>{html.escape(str(item.get('location_raw') or 'k.A.'))}</dd></div>
            </dl>
            {engine_note_html}
            <p class="risk">Risiko: {html.escape(risk)}</p>
            <a class="button" href="{html.escape(item['url'])}" target="_blank" rel="noreferrer">Angebot öffnen</a>
          </div>
        </article>
        ''')
    cards_html = "\n".join(cards) or '<p class="empty">Keine Angebote gefunden. Prüfe Quellen/Netzwerk oder nutze Fixture-Daten.</p>'
    warnings = payload.get("warnings") or []
    warnings_html = ""
    if warnings:
        warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
        warnings_html = f'<section class="warnings"><h2>Quellen-Hinweise</h2><ul>{warning_items}</ul></section>'
    summary = payload["summary"]
    return f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Corvette Tracker</title>
  <style>
    :root {{ color-scheme: dark; --bg:#09090b; --card:#141418; --muted:#a1a1aa; --text:#fafafa; --line:#27272a; --accent:#ef4444; --accent2:#f59e0b; }}
    * {{ box-sizing: border-box; }} body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: radial-gradient(circle at top left, #3f0b0b, transparent 34rem), var(--bg); color:var(--text); }}
    header {{ max-width:1180px; margin:0 auto; padding:56px 20px 28px; }}
    .eyebrow {{ color:var(--accent2); text-transform:uppercase; letter-spacing:.14em; font-size:12px; font-weight:700; }}
    h1 {{ margin:.2em 0; font-size:clamp(40px, 7vw, 80px); line-height:.95; letter-spacing:-.06em; }}
    .lead {{ max-width:760px; color:var(--muted); font-size:18px; line-height:1.6; }}
    .stats {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:24px; }} .stat,.filter-pill {{ border:1px solid var(--line); border-radius:999px; padding:10px 14px; background:rgba(255,255,255,.04); }}
    .toolbar {{ max-width:1180px; margin:0 auto; padding:0 20px 18px; display:flex; gap:10px; flex-wrap:wrap; }}
    .filter-pill {{ color:var(--muted); }}
    main {{ max-width:1180px; margin:0 auto; padding:0 20px 64px; display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:18px; }}
    .card {{ overflow:hidden; border:1px solid var(--line); border-radius:24px; background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.025)); box-shadow:0 18px 50px rgba(0,0,0,.24); }}
    .image {{ display:block; aspect-ratio:16/10; background:#18181b; overflow:hidden; }} .image img {{ width:100%; height:100%; object-fit:cover; transition:transform .22s ease; }} .card:hover img {{ transform:scale(1.035); }} .placeholder {{ height:100%; display:grid; place-items:center; color:var(--muted); }}
    .card-body {{ padding:20px; }} .meta {{ display:flex; justify-content:space-between; color:var(--muted); font-size:13px; gap:12px; }} h2 {{ font-size:21px; line-height:1.15; margin:12px 0; letter-spacing:-.03em; }} .price {{ font-size:30px; font-weight:800; margin:0 0 16px; color:white; }}
    dl {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin:0 0 14px; }} dl div {{ border:1px solid var(--line); border-radius:14px; padding:10px; background:rgba(0,0,0,.15); }} dt {{ color:var(--muted); font-size:12px; }} dd {{ margin:3px 0 0; font-weight:700; }}
    .engine-note {{ color:var(--accent2); font-size:13px; margin:0 0 10px; }} .risk {{ color:var(--muted); min-height:1.5em; }} .button {{ display:inline-flex; text-decoration:none; color:white; background:var(--accent); padding:11px 14px; border-radius:12px; font-weight:700; }} .empty {{ color:var(--muted); grid-column:1/-1; }}
    .warnings {{ max-width:1180px; margin:0 auto 18px; padding:0 20px; color:#fecaca; }} .warnings h2 {{ font-size:18px; margin:0 0 8px; }} .warnings ul {{ border:1px solid #7f1d1d; border-radius:16px; padding:14px 18px 14px 34px; background:rgba(127,29,29,.25); }}
    footer {{ max-width:1180px; margin:0 auto; padding:0 20px 34px; color:var(--muted); }}
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">C6 Corvette Angebotsfeed</div>
    <h1>Corvette Tracker</h1>
    <p class="lead">Aktuelle öffentlich gefundene C6-Angebote aus angebundenen Quellen. Mit Preis, Laufleistung, Motor, Risiko-Hinweisen und Bildern, soweit die Quelle sie ausliefert.</p>
    <div class="stats"><span class="stat">{summary['total_active']} aktive Treffer</span><span class="stat">{summary['new_listings']} neu</span><span class="stat">{summary['price_changes']} Preisänderungen</span><span class="stat">{summary['risk_warnings']} Warnungen</span></div>
  </header>
  <section class="toolbar"><span class="filter-pill">Grand Sport</span><span class="filter-pill">Z06</span><span class="filter-pill">ZR1</span><span class="filter-pill">ohne Risiko bevorzugen</span></section>
  {warnings_html}
  <main>{cards_html}</main>
  <footer>Generiert: {html.escape(payload['generated_at'])} · Exporte: feed/latest.md, data/exports/latest.json, data/exports/latest.csv</footer>
</body>
</html>
'''


def write_exports(payload: dict[str, Any], output_dir: str | Path) -> None:
    root = Path(output_dir)
    feed_dir = root / "feed"
    export_dir = root / "data" / "exports"
    site_dir = root / "site"
    feed_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    site_dir.mkdir(parents=True, exist_ok=True)
    (feed_dir / "latest.md").write_text(render_markdown_feed(payload), encoding="utf-8")
    (export_dir / "latest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with (export_dir / "latest.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["id", "source", "title", "price_eur", "mileage_km", "trim", "engine", "location_raw", "score", "change_type", "url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in payload["listings"]:
            writer.writerow({key: item.get(key) for key in fieldnames})
    (site_dir / "index.html").write_text(render_html_site(payload), encoding="utf-8")
