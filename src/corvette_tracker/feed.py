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


def price_display(item: dict[str, Any]) -> str:
    label = item.get("price_label")
    if item.get("price_eur") is not None:
        value = format_eur(item.get("price_eur"))
        return f"{value} {label}" if label else value
    return str(label or "k.A.")


def format_km(value: int | None) -> str:
    return "k.A." if value is None else f"{value:,}".replace(",", ".") + " km"


def power_display(item: dict[str, Any]) -> str:
    if item.get("power_hp") is not None:
        return f"{item['power_hp']} PS"
    if item.get("estimated_power_hp") is not None:
        return f"ca. {item['estimated_power_hp']} PS"
    return "k.A."


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


def variant_display(item: dict[str, Any]) -> str:
    trim = item.get("trim")
    body_style = item.get("body_style")
    if trim and trim != "Base" and body_style:
        return f"{trim} {body_style}"
    if trim and trim != "Base":
        return str(trim)
    if body_style:
        return f"C6 {body_style}"
    return str(trim or "k.A.")


def transmission_display(item: dict[str, Any]) -> str:
    value = item.get("transmission")
    if value == "manual":
        return "Schalter"
    if value == "automatic":
        return "Automatik"
    return str(value or "k.A.")


def ai_summary_display(item: dict[str, Any]) -> str | None:
    enrichment = item.get("ai_enrichment") or {}
    if not enrichment:
        return None
    provider = enrichment.get("provider") or "AI"
    confidence = enrichment.get("confidence")
    confidence_text = f" ({confidence:.0%})" if isinstance(confidence, int | float) else ""
    notes = enrichment.get("notes")
    return f"{provider}{confidence_text}: {notes}" if notes else f"{provider}{confidence_text}"


def render_gallery(images: list[str], title: str) -> str:
    if not images:
        return ""
    thumbnails = "".join(
        f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer" data-gallery-image><img src="{html.escape(url)}" alt="{title} Bild {index}" loading="lazy"></a>'
        for index, url in enumerate(images, start=1)
    )
    return f'<div class="gallery"><div class="gallery-count">{len(images)} Bilder</div><div class="gallery-strip">{thumbnails}</div></div>'


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
            f"## {index}. {item['title']} — {price_display(item)}",
            "",
        ]
        if item.get("image_urls"):
            lines += [f"![{item['title']}]({item['image_urls'][0]})", ""]
        engine_note = engine_note_display(item)
        lines += [
            f"- Quelle: {item['source']}",
            f"- Score: {item['score']}/100",
            f"- Variante/Motor: {variant_display(item)} / {engine_display(item)}",
            f"- PS: {power_display(item)}",
            f"- Getriebe: {transmission_display(item)}",
            f"- Karosserie: {item.get('body_style') or 'k.A.'}",
        ]
        if engine_note:
            lines.append(f"- Motor-Hinweis: {engine_note}")
        if item.get("power_note"):
            lines.append(f"- PS-Hinweis: {item['power_note']}")
        if item.get("inference_notes"):
            lines.append(f"- Vermutungen: {', '.join(item.get('inference_notes') or [])}")
        if item.get("conflict_flags"):
            lines.append(f"- Konflikte: {', '.join(item.get('conflict_flags') or [])}")
        if item.get("equipment"):
            lines.append(f"- Ausstattung (AI): {', '.join(item.get('equipment') or [])}")
        if item.get("visual_flags"):
            lines.append(f"- Visuelle Hinweise (AI): {', '.join(item.get('visual_flags') or [])}")
        ai_summary = ai_summary_display(item)
        if ai_summary:
            lines.append(f"- AI-Auswertung: {ai_summary}")
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
        images = [str(url) for url in (item.get("image_urls") or [])]
        image = html.escape((images or [""])[0])
        risk = ", ".join(item.get("risk_flags") or []) or "keine"
        img_html = f'<img src="{image}" alt="{title}" loading="lazy">' if image else '<div class="placeholder">Kein Bild</div>'
        gallery_html = render_gallery(images, title)
        engine_text = html.escape(engine_display(item))
        engine_note = engine_note_display(item)
        engine_note_html = f'<p class="engine-note">{html.escape(engine_note)}</p>' if engine_note else ""
        equipment_html = ""
        if item.get("equipment"):
            equipment_html = f'<p class="ai-line"><strong>Ausstattung (AI):</strong> {html.escape(", ".join(item.get("equipment") or []))}</p>'
        visual_flags_html = ""
        if item.get("visual_flags"):
            visual_flags_html = f'<p class="ai-line"><strong>Visuelle Hinweise:</strong> {html.escape(", ".join(item.get("visual_flags") or []))}</p>'
        ai_summary = ai_summary_display(item)
        ai_html = f'<p class="ai-line"><strong>AI-Auswertung:</strong> {html.escape(ai_summary)}</p>' if ai_summary else ""
        inference_html = ""
        if item.get("inference_notes"):
            inference_items = "".join(f"<li>{html.escape(str(note))}</li>" for note in item.get("inference_notes") or [])
            inference_html = f'<div class="inference-line"><strong>Vermutungen</strong><ul>{inference_items}</ul></div>'
        conflict_html = ""
        if item.get("conflict_flags"):
            conflict_items = "".join(f"<li>{html.escape(str(flag))}</li>" for flag in item.get("conflict_flags") or [])
            conflict_html = f'<div class="conflict-line"><strong>Konflikte</strong><ul>{conflict_items}</ul></div>'
        cards.append(f'''
        <article class="card" data-listing-card data-trim="{html.escape(str(item.get('trim') or 'unknown'))}" data-risk="{'yes' if item.get('risk_flags') else 'no'}">
          <a class="image" href="{html.escape(item['url'])}" target="_blank" rel="noreferrer">{img_html}</a>
          {gallery_html}
          <div class="card-body">
            <div class="meta"><span>{html.escape(item['source'])}</span><span>Score {item['score']}/100</span></div>
            <h2>{title}</h2>
            <p class="price">{html.escape(price_display(item))}</p>
            <dl>
              <div><dt>Motor</dt><dd>{engine_text}</dd></div>
              <div><dt>PS</dt><dd>{html.escape(power_display(item))}</dd></div>
              <div><dt>km</dt><dd>{format_km(item.get('mileage_km'))}</dd></div>
              <div><dt>Variante</dt><dd>{html.escape(variant_display(item))}</dd></div>
              <div><dt>Getriebe</dt><dd>{html.escape(transmission_display(item))}</dd></div>
              <div><dt>Karosserie</dt><dd>{html.escape(str(item.get('body_style') or 'k.A.'))}</dd></div>
              <div><dt>Ort</dt><dd>{html.escape(str(item.get('location_raw') or 'k.A.'))}</dd></div>
              <div><dt>EZ</dt><dd>{html.escape(str(item.get('first_registration') or 'k.A.'))}</dd></div>
              <div><dt>TÜV</dt><dd>{html.escape(str(item.get('tuv_until') or 'k.A.'))}</dd></div>
            </dl>
            {engine_note_html}
            {f'<p class="engine-note">{html.escape(str(item.get("power_note")))}</p>' if item.get("power_note") else ""}
            {equipment_html}
            {visual_flags_html}
            {ai_html}
            {inference_html}
            {conflict_html}
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
    .gallery {{ border-top:1px solid var(--line); border-bottom:1px solid var(--line); background:rgba(0,0,0,.18); padding:10px 12px; }} .gallery-count {{ color:var(--muted); font-size:12px; margin-bottom:8px; }} .gallery-strip {{ display:flex; gap:8px; overflow-x:auto; padding-bottom:2px; scrollbar-width:thin; }} .gallery-strip a {{ flex:0 0 64px; width:64px; height:48px; border-radius:10px; overflow:hidden; border:1px solid var(--line); background:#18181b; }} .gallery-strip img {{ width:100%; height:100%; object-fit:cover; display:block; }}
    .card-body {{ padding:20px; }} .meta {{ display:flex; justify-content:space-between; color:var(--muted); font-size:13px; gap:12px; }} h2 {{ font-size:21px; line-height:1.15; margin:12px 0; letter-spacing:-.03em; }} .price {{ font-size:30px; font-weight:800; margin:0 0 16px; color:white; }}
    dl {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin:0 0 14px; }} dl div {{ border:1px solid var(--line); border-radius:14px; padding:10px; background:rgba(0,0,0,.15); }} dt {{ color:var(--muted); font-size:12px; }} dd {{ margin:3px 0 0; font-weight:700; }}
    .engine-note,.ai-line,.inference-line,.conflict-line {{ color:var(--accent2); font-size:13px; margin:0 0 10px; }} .ai-line {{ color:#d4d4d8; }} .ai-line strong,.inference-line strong,.conflict-line strong {{ color:var(--accent2); }} .inference-line ul,.conflict-line ul {{ margin:6px 0 0; padding-left:18px; color:#d4d4d8; }} .conflict-line strong {{ color:#fecaca; }} .risk {{ color:var(--muted); min-height:1.5em; }} .button {{ display:inline-flex; text-decoration:none; color:white; background:var(--accent); padding:11px 14px; border-radius:12px; font-weight:700; }} .empty {{ color:var(--muted); grid-column:1/-1; }}
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
        fieldnames = ["id", "source", "title", "price_eur", "price_label", "mileage_km", "trim", "engine", "power_hp", "estimated_power_hp", "power_note", "transmission", "body_style", "inference_notes", "conflict_flags", "location_raw", "score", "change_type", "url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in payload["listings"]:
            writer.writerow({key: item.get(key) for key in fieldnames})
    (site_dir / "index.html").write_text(render_html_site(payload), encoding="utf-8")
