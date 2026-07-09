from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
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


def price_per_1000_km(item: dict[str, Any]) -> int | None:
    price = item.get("price_eur")
    mileage = item.get("mileage_km")
    if not price or not mileage:
        return None
    return round(int(price) / int(mileage) * 1000)


def _average(values: list[int]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def _distribution(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts = Counter(str(item.get(key) or "k.A.") for item in items)
    return [{"label": label, "count": count} for label, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]


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
    listing_dicts = [item.to_dict() for item in ordered]
    prices = [int(item["price_eur"]) for item in listing_dicts if item.get("price_eur") is not None]
    mileages = [int(item["mileage_km"]) for item in listing_dicts if item.get("mileage_km") is not None]
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "generated_at": generated_at,
        "summary": {
            "total_active": len(ordered),
            "new_listings": sum(1 for item in ordered if item.change_type == "new"),
            "changed_listings": sum(1 for item in ordered if item.change_type not in {"new", "unchanged"}),
            "price_changes": sum(1 for item in ordered if item.change_type == "price_change"),
            "risk_warnings": sum(1 for item in ordered if item.risk_flags),
            "avg_price_eur": _average(prices),
            "median_price_eur": int(median(prices)) if prices else None,
            "min_price_eur": min(prices) if prices else None,
            "max_price_eur": max(prices) if prices else None,
            "avg_mileage_km": _average(mileages),
            "sources": _distribution(listing_dicts, "source"),
            "trims": _distribution(listing_dicts, "trim"),
        },
        "listings": listing_dicts,
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


def _metric(label: str, value: str, meta: str, key: str) -> str:
    return f'<article class="metric" data-metric="{html.escape(key)}"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong><small>{html.escape(meta)}</small></article>'


def _attr(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def render_html_site(payload: dict[str, Any]) -> str:
    cards = []
    for item in payload["listings"]:
        title = html.escape(item["title"])
        images = [str(url) for url in (item.get("image_urls") or [])]
        image = html.escape((images or [""])[0])
        risk_flags = item.get("risk_flags") or []
        risk = ", ".join(risk_flags) or "keine"
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
        per_1000 = price_per_1000_km(item)
        description = html.escape(str(item.get("description_text") or "Keine Beschreibung aus der Quelle."))
        cards.append(f'''
        <article class="card" data-listing-card data-source="{_attr(item.get('source'))}" data-trim="{_attr(item.get('trim') or 'k.A.')}" data-risk="{'yes' if risk_flags else 'no'}" data-price="{_attr(item.get('price_eur'))}" data-mileage="{_attr(item.get('mileage_km'))}" data-score="{_attr(item.get('score'))}">
          <div class="score-badge">{html.escape(str(item.get('score', 0)))}%</div>
          <a class="image" href="{html.escape(item['url'])}" target="_blank" rel="noreferrer">{img_html}</a>
          {gallery_html}
          <div class="card-body">
            <div class="meta"><span>{html.escape(str(item.get('source') or 'Quelle'))}</span><span>Score {html.escape(str(item.get('score', 0)))}</span></div>
            <h2>{title}</h2>
            <p class="price">{html.escape(price_display(item))}</p>
            <div class="quick-specs"><span>{format_km(item.get('mileage_km'))}</span><span>{engine_text}</span><span>{html.escape(variant_display(item))}</span><span>{html.escape(transmission_display(item))}</span></div>
            {engine_note_html}
            <details class="listing-details">
              <summary>Details ansehen</summary>
              <dl>
                <div><dt>Preis / 1.000 km</dt><dd>{format_eur(per_1000) if per_1000 is not None else 'k.A.'}</dd></div>
                <div><dt>Motor</dt><dd>{engine_text}</dd></div>
                <div><dt>PS</dt><dd>{html.escape(power_display(item))}</dd></div>
                <div><dt>km</dt><dd>{format_km(item.get('mileage_km'))}</dd></div>
                <div><dt>Variante</dt><dd>{html.escape(variant_display(item))}</dd></div>
                <div><dt>Getriebe</dt><dd>{html.escape(transmission_display(item))}</dd></div>
                <div><dt>Karosserie</dt><dd>{html.escape(str(item.get('body_style') or 'k.A.'))}</dd></div>
                <div><dt>EZ</dt><dd>{html.escape(str(item.get('first_registration') or 'k.A.'))}</dd></div>
                <div><dt>TÜV</dt><dd>{html.escape(str(item.get('tuv_until') or 'k.A.'))}</dd></div>
                <div><dt>Ort</dt><dd>{html.escape(str(item.get('location_raw') or 'k.A.'))}</dd></div>
                <div><dt>Unfallstatus</dt><dd>{html.escape(str(item.get('accident_status') or 'unbekannt'))}</dd></div>
                <div><dt>Änderung</dt><dd>{html.escape(str(item.get('change_type') or 'unbekannt'))}</dd></div>
              </dl>
              <p class="description">{description}</p>
              {f'<p class="engine-note">{html.escape(str(item.get("power_note")))}</p>' if item.get("power_note") else ""}
              {equipment_html}
              {visual_flags_html}
              {ai_html}
              {inference_html}
              {conflict_html}
              <p class="risk">Risiko: {html.escape(risk)}</p>
            </details>
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
    source_options = "".join(f'<option value="{html.escape(row["label"])}">{html.escape(row["label"])} ({row["count"]})</option>' for row in summary.get("sources", []))
    trim_options = "".join(f'<option value="{html.escape(row["label"])}">{html.escape(row["label"])} ({row["count"]})</option>' for row in summary.get("trims", []))
    chart_json = html.escape(json.dumps({"sources": summary.get("sources", []), "trims": summary.get("trims", [])}, ensure_ascii=False), quote=True)
    metrics_html = "".join([
        _metric("Aktive Treffer", str(summary["total_active"]), f'{summary["new_listings"]} neu', "count"),
        _metric("Ø Preis", format_eur(summary.get("avg_price_eur")), f'Median {format_eur(summary.get("median_price_eur"))}', "price"),
        _metric("Ø Laufleistung", format_km(summary.get("avg_mileage_km")), "Angebote mit km", "mileage"),
        _metric("Risiko", str(summary["risk_warnings"]), f'{summary["price_changes"]} Preisänderungen', "risk"),
    ])
    return f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Corvette Tracker</title>
  <style>
    :root {{ color-scheme: dark; --bg:#08090b; --panel:#111318; --card:#151820; --muted:#9aa3b2; --text:#f4f7fb; --line:#2a303b; --accent:#ef4444; --accent2:#f59e0b; }}
    * {{ box-sizing: border-box; }} body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background:radial-gradient(circle at top left, rgba(239,68,68,.22), transparent 32rem), linear-gradient(180deg,#0b0d12,var(--bg)); color:var(--text); }}
    .shell {{ max-width:1240px; margin:0 auto; padding:32px 20px 72px; }} header {{ display:grid; grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr); gap:24px; align-items:end; padding:28px 0; }}
    .eyebrow {{ color:var(--accent2); text-transform:uppercase; letter-spacing:.16em; font-size:12px; font-weight:800; }} h1 {{ margin:.2em 0; font-size:clamp(42px,7vw,84px); line-height:.92; letter-spacing:-.065em; }} .lead {{ max-width:760px; color:var(--muted); font-size:18px; line-height:1.65; }}
    .panel,.card {{ border:1px solid var(--line); border-radius:28px; background:linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.018)); box-shadow:0 22px 70px rgba(0,0,0,.25); }} .overview,.controls {{ padding:18px; }} .overview h2,.controls h2 {{ margin:0 0 14px; font-size:16px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }} .metric {{ border:1px solid var(--line); border-radius:18px; padding:14px; background:rgba(255,255,255,.035); }} .metric span,.metric small {{ display:block; color:var(--muted); font-size:12px; }} .metric strong {{ display:block; margin:5px 0; font-size:24px; letter-spacing:-.04em; }}
    .dashboard {{ display:grid; grid-template-columns:320px minmax(0,1fr); gap:18px; align-items:start; }} .controls {{ position:sticky; top:16px; }} .field {{ display:grid; gap:7px; margin-bottom:14px; }} label,.toggle span {{ color:var(--muted); font-size:13px; }} select {{ width:100%; border:1px solid var(--line); border-radius:14px; padding:11px 12px; background:#0c0f14; color:var(--text); }} .toggle {{ display:flex; justify-content:space-between; gap:12px; align-items:center; padding:10px 0; border-top:1px solid var(--line); }} .toggle input {{ accent-color:var(--accent); }}
    .chart {{ display:grid; gap:10px; margin-top:16px; }} .bar-row {{ display:grid; grid-template-columns:90px 1fr 28px; align-items:center; gap:8px; color:var(--muted); font-size:12px; }} .bar {{ height:9px; border-radius:999px; background:#0c0f14; border:1px solid var(--line); overflow:hidden; }} .bar i {{ display:block; height:100%; border-radius:999px; background:linear-gradient(90deg,var(--accent),var(--accent2)); }}
    .list-head {{ display:flex; justify-content:space-between; gap:12px; align-items:center; margin:0 0 14px; color:var(--muted); }} main {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:18px; }}
    .card {{ overflow:hidden; border-radius:26px; position:relative; }} .score-badge {{ margin:12px 12px 0; display:inline-flex; align-items:center; justify-content:center; min-width:58px; padding:8px 12px; border-radius:999px; background:linear-gradient(135deg,var(--accent),var(--accent2)); color:white; font-weight:900; box-shadow:0 10px 28px rgba(0,0,0,.32); }} .image {{ display:block; aspect-ratio:16/10; background:#12151b; overflow:hidden; margin-top:10px; }} .image img {{ width:100%; height:100%; object-fit:cover; transition:transform .25s ease; }} .card:hover img {{ transform:scale(1.035); }} .placeholder {{ height:100%; display:grid; place-items:center; color:var(--muted); }}
    .gallery {{ border-top:1px solid var(--line); border-bottom:1px solid var(--line); background:rgba(0,0,0,.18); padding:10px 12px; }} .gallery-count {{ color:var(--muted); font-size:12px; margin-bottom:8px; }} .gallery-strip {{ display:flex; gap:8px; overflow-x:auto; padding-bottom:2px; scrollbar-width:thin; }} .gallery-strip a {{ flex:0 0 64px; width:64px; height:48px; border-radius:10px; overflow:hidden; border:1px solid var(--line); }} .gallery-strip img {{ width:100%; height:100%; object-fit:cover; display:block; }}
    .card-body {{ padding:18px; }} .meta {{ display:flex; justify-content:space-between; color:var(--muted); font-size:13px; gap:12px; }} h2 {{ font-size:20px; line-height:1.18; margin:12px 0; letter-spacing:-.035em; }} .price {{ font-size:30px; font-weight:850; margin:0 0 14px; letter-spacing:-.045em; }} .quick-specs {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }} .quick-specs span {{ border:1px solid var(--line); border-radius:999px; padding:7px 10px; background:rgba(255,255,255,.035); color:#dce3ee; font-size:13px; }}
    .listing-details {{ border-top:1px solid var(--line); margin-top:12px; padding-top:12px; }} .listing-details summary {{ cursor:pointer; font-weight:800; }} dl {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin:12px 0; }} dl div {{ border:1px solid var(--line); border-radius:14px; padding:10px; background:rgba(0,0,0,.14); }} dt {{ color:var(--muted); font-size:12px; }} dd {{ margin:3px 0 0; font-weight:750; overflow-wrap:anywhere; }}
    .engine-note,.ai-line,.inference-line,.conflict-line {{ color:var(--accent2); font-size:13px; }} .ai-line {{ color:#d4d4d8; }} .ai-line strong,.inference-line strong,.conflict-line strong {{ color:var(--accent2); }} .inference-line ul,.conflict-line ul {{ margin:6px 0 0; padding-left:18px; color:#d4d4d8; }} .conflict-line strong {{ color:#fecaca; }} .description,.risk,.empty {{ color:var(--muted); line-height:1.55; }} .button {{ display:inline-flex; text-decoration:none; color:white; background:var(--accent); padding:11px 14px; border-radius:14px; font-weight:800; margin-top:10px; }} .warnings {{ margin:0 0 18px; color:#fecaca; }} footer {{ margin-top:26px; color:var(--muted); font-size:13px; }}
    @media (max-width:900px) {{ header,.dashboard {{ grid-template-columns:1fr; }} .controls {{ position:static; }} }} @media (max-width:520px) {{ .shell {{ padding:20px 14px 52px; }} .metrics,main,dl {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body><div class="shell">
  <header><div><div class="eyebrow">C6 Corvette Angebotsfeed</div><h1>Cleaner Überblick. Schnellere Entscheidung.</h1><p class="lead">Aktuelle öffentlich gefundene C6-Angebote mit Preisniveau, Laufleistung, Risiko-Hinweisen und Details pro Inserat. Die Übersicht ist lokal filter- und sortierbar.</p></div><section class="panel overview" data-dashboard-config><h2>Übersicht</h2><div class="metrics">{metrics_html}</div></section></header>
  {warnings_html}
  <section class="dashboard"><aside class="panel controls"><h2>Ansicht konfigurieren</h2><div class="field"><label for="source-filter">Quelle</label><select id="source-filter"><option value="all">Alle Quellen</option>{source_options}</select></div><div class="field"><label for="trim-filter">Variante</label><select id="trim-filter"><option value="all">Alle Varianten</option>{trim_options}</select></div><div class="field"><label for="sort-order">Sortierung</label><select id="sort-order"><option value="score-desc">Score hoch</option><option value="price-asc">Preis niedrig</option><option value="price-desc">Preis hoch</option><option value="mileage-asc">km niedrig</option></select></div><label class="toggle"><span>Riskante Angebote ausblenden</span><input id="hide-risk" type="checkbox"></label><label class="toggle"><span>Ø Preis anzeigen</span><input type="checkbox" data-toggle-metric="price" checked></label><label class="toggle"><span>Ø Laufleistung anzeigen</span><input type="checkbox" data-toggle-metric="mileage" checked></label><div class="chart" id="source-chart" data-chart="sources" data-chart-json="{chart_json}"></div></aside><section><div class="list-head"><span id="visible-count">{summary['total_active']} Angebote</span><span>Details direkt in jeder Karte</span></div><main id="listing-grid">{cards_html}</main></section></section>
  <footer>Generiert: {html.escape(payload['generated_at'])} · Exporte: feed/latest.md, data/exports/latest.json, data/exports/latest.csv</footer>
</div><script>
(function() {{
  const cards = Array.from(document.querySelectorAll('[data-listing-card]'));
  const sourceFilter = document.getElementById('source-filter'); const trimFilter = document.getElementById('trim-filter'); const sortOrder = document.getElementById('sort-order'); const hideRisk = document.getElementById('hide-risk'); const grid = document.getElementById('listing-grid'); const visibleCount = document.getElementById('visible-count');
  function num(card, name, fallback) {{ const value = Number(card.dataset[name] || fallback); return Number.isFinite(value) ? value : fallback; }}
  function apply() {{ const source = sourceFilter.value; const trim = trimFilter.value; const filtered = cards.filter(card => (source === 'all' || card.dataset.source === source) && (trim === 'all' || card.dataset.trim === trim) && (!hideRisk.checked || card.dataset.risk !== 'yes')); const sorted = filtered.sort((a,b) => {{ if (sortOrder.value === 'price-asc') return num(a,'price',999999999)-num(b,'price',999999999); if (sortOrder.value === 'price-desc') return num(b,'price',0)-num(a,'price',0); if (sortOrder.value === 'mileage-asc') return num(a,'mileage',999999999)-num(b,'mileage',999999999); return num(b,'score',0)-num(a,'score',0); }}); cards.forEach(card => card.hidden = true); sorted.forEach(card => {{ card.hidden = false; grid.appendChild(card); }}); visibleCount.textContent = `${{sorted.length}} Angebote`; }}
  [sourceFilter, trimFilter, sortOrder, hideRisk].forEach(el => el.addEventListener('change', apply));
  document.querySelectorAll('[data-toggle-metric]').forEach(input => input.addEventListener('change', () => {{ const metric = document.querySelector(`[data-metric="${{input.dataset.toggleMetric}}"]`); if (metric) metric.hidden = !input.checked; }}));
  const chart = document.getElementById('source-chart'); if (chart) {{ const data = JSON.parse(chart.dataset.chartJson || '{{}}').sources || []; const max = Math.max(1, ...data.map(row => row.count)); chart.innerHTML = data.map(row => `<div class="bar-row"><span>${{row.label}}</span><div class="bar"><i style="width:${{Math.max(8, row.count / max * 100)}}%"></i></div><strong>${{row.count}}</strong></div>`).join(''); }}
  apply();
}})();
</script></body></html>
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
