import json
from pathlib import Path

from corvette_tracker.feed import build_feed_payload, render_html_site, render_markdown_feed, write_exports
from corvette_tracker.models import Listing


def listing(**overrides):
    base = dict(
        id="autoscout24_123",
        source="AutoScout24",
        source_listing_id="123",
        url="https://example.test/listing/123",
        title="Chevrolet Corvette C6 Grand Sport",
        generation="C6",
        price_eur=54900,
        mileage_km=68000,
        location_raw="Hamburg",
        trim="Grand Sport",
        engine="LS3",
        power_hp=437,
        transmission="manual",
        body_style="Cabrio",
        first_registration="2011-05",
        tuv_until="2027-06",
        accident_status="unfallfrei",
        image_urls=["https://example.test/corvette.jpg"],
        risk_flags=[],
        score=87,
        change_type="new",
        cluster_id="soft_abc",
    )
    base.update(overrides)
    return Listing(**base)


def test_build_feed_payload_sorts_by_score_and_counts_summary():
    payload = build_feed_payload([listing(score=70), listing(id="b", score=95, risk_flags=["damage_reported"])])

    assert payload["summary"]["total_active"] == 2
    assert payload["summary"]["new_listings"] == 2
    assert payload["summary"]["risk_warnings"] == 1
    assert payload["summary"]["avg_price_eur"] == 54900
    assert payload["summary"]["median_price_eur"] == 54900
    assert payload["summary"]["sources"] == [{"label": "AutoScout24", "count": 2}]
    assert payload["listings"][0]["score"] == 95


def test_render_markdown_feed_includes_images_and_listing_fields():
    markdown = render_markdown_feed(build_feed_payload([listing()]))

    assert "Neue C6 Corvette-Angebote" in markdown
    assert "Chevrolet Corvette C6 Grand Sport" in markdown
    assert "54.900 €" in markdown
    assert "![Chevrolet Corvette C6 Grand Sport]" in markdown
    assert "https://example.test/listing/123" in markdown


def test_render_feeds_show_vb_price_label_instead_of_unknown_price():
    vb_listing = listing(price_eur=None, price_label="VB")
    numeric_vb_listing = listing(id="numeric-vb", price_eur=38900, price_label="VB")
    payload = build_feed_payload([vb_listing, numeric_vb_listing])

    markdown = render_markdown_feed(payload)
    html = render_html_site(payload)

    assert "— VB" in markdown
    assert "38.900 € VB" in markdown
    assert '<p class="price">VB</p>' in html
    assert '<p class="price">38.900 € VB</p>' in html
    assert "k.A." not in html.split('<p class="price">', 1)[1].split("</p>", 1)[0]


def test_render_html_site_contains_cards_filters_and_required_vehicle_fields():
    html = render_html_site(build_feed_payload([listing()]))

    assert "Corvette Tracker" in html
    assert "data-listing-card" in html
    assert "https://example.test/corvette.jpg" in html
    assert "Grand Sport" in html
    assert "data-dashboard-config" in html
    assert "Ansicht konfigurieren" in html
    assert "Details ansehen" in html
    assert "source-filter" in html
    assert "sort-order" in html
    assert '<div class="score-badge">87%</div>' in html
    assert html.index('<div class="score-badge">87%</div>') < html.index('<a class="image"')
    for label, value in [
        ("Motor", "LS3"),
        ("PS", "437 PS"),
        ("km", "68.000 km"),
        ("Variante", "Grand Sport Cabrio"),
        ("Getriebe", "Schalter"),
        ("Karosserie", "Cabrio"),
        ("Ort", "Hamburg"),
        ("EZ", "2011-05"),
    ]:
        assert f"<dt>{label}</dt>" in html
        assert value in html


def test_render_html_site_shows_base_coupe_as_c6_coupe_variant():
    html = render_html_site(build_feed_payload([listing(trim="Base", body_style="Coupé", engine="LS2", power_hp=404)]))

    assert "C6 Coupé" in html
    assert "<dt>Variante</dt>" in html
    assert "<dt>Karosserie</dt>" in html


def test_render_html_site_includes_gallery_thumbnails_for_multiple_images():
    item = listing(
        image_urls=[
            "https://example.test/corvette-1.jpg",
            "https://example.test/corvette-2.jpg",
            "https://example.test/corvette-3.jpg",
        ]
    )

    html = render_html_site(build_feed_payload([item]))

    assert html.count("data-gallery-image") == 3
    assert "3 Bilder" in html
    assert "https://example.test/corvette-2.jpg" in html


def test_render_outputs_probable_engine_note_when_engine_is_inferred():
    inferred = listing(engine=None, probable_engine="LS2", engine_confidence=0.86, engine_note="Leistung 404 PS → wahrscheinlich LS2")
    payload = build_feed_payload([inferred])

    markdown = render_markdown_feed(payload)
    html = render_html_site(payload)

    assert "wahrscheinlich LS2" in markdown
    assert "wahrscheinlich LS2" in html


def test_render_outputs_estimated_power_when_explicit_ps_is_missing():
    item = listing(power_hp=None, estimated_power_hp=437, power_note="Motor LS3 → Leistung ca. 437 PS geschätzt")
    payload = build_feed_payload([item])

    markdown = render_markdown_feed(payload)
    html = render_html_site(payload)

    assert "ca. 437 PS" in markdown
    assert "ca. 437 PS" in html
    assert "Motor LS3" in markdown


def test_render_outputs_inference_notes_and_conflict_flags():
    item = listing(
        inference_notes=["LS7 → Z06", "Z06 → Schalter"],
        conflict_flags=["conflict_z06_body_cabrio"],
    )
    payload = build_feed_payload([item])

    markdown = render_markdown_feed(payload)
    html = render_html_site(payload)

    assert "Vermutungen" in markdown
    assert "LS7 → Z06" in html
    assert "Konflikte" in html
    assert "conflict_z06_body_cabrio" in markdown


def test_render_html_site_shows_source_warnings():
    payload = build_feed_payload([listing()])
    payload["warnings"] = ["mobile.de: HTTP Error 403: Forbidden"]

    html = render_html_site(payload)

    assert "Quellen-Hinweise" in html
    assert "mobile.de" in html
    assert "HTTP Error 403" in html


def test_render_outputs_ai_enrichment_equipment_and_notes():
    enriched = listing(
        equipment=["Head-Up Display", "NPP Klappenauspuff"],
        visual_flags=["aftermarket_wheels"],
        ai_enrichment={"provider": "fake-ai", "confidence": 0.82, "notes": "Bilder zeigen Zubehörfelgen."},
    )
    payload = build_feed_payload([enriched])

    markdown = render_markdown_feed(payload)
    html = render_html_site(payload)

    assert "Head-Up Display" in markdown
    assert "fake-ai" in html
    assert "Bilder zeigen Zubehörfelgen" in html


def test_write_exports_creates_json_markdown_csv_and_html(tmp_path: Path):
    payload = build_feed_payload([listing()])
    write_exports(payload, tmp_path)

    assert (tmp_path / "feed" / "latest.md").exists()
    assert (tmp_path / "data" / "exports" / "latest.json").exists()
    assert (tmp_path / "data" / "exports" / "latest.csv").exists()
    assert (tmp_path / "site" / "index.html").exists()
    data = json.loads((tmp_path / "data" / "exports" / "latest.json").read_text())
    assert data["listings"][0]["image_urls"]
