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
    assert payload["listings"][0]["score"] == 95


def test_render_markdown_feed_includes_images_and_listing_fields():
    markdown = render_markdown_feed(build_feed_payload([listing()]))

    assert "Neue C6 Corvette-Angebote" in markdown
    assert "Chevrolet Corvette C6 Grand Sport" in markdown
    assert "54.900 €" in markdown
    assert "![Chevrolet Corvette C6 Grand Sport]" in markdown
    assert "https://example.test/listing/123" in markdown


def test_render_html_site_contains_cards_filters_and_image():
    html = render_html_site(build_feed_payload([listing()]))

    assert "Corvette Tracker" in html
    assert "data-listing-card" in html
    assert "https://example.test/corvette.jpg" in html
    assert "Grand Sport" in html
    assert "filter-pill" in html


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


def test_render_html_site_shows_source_warnings():
    payload = build_feed_payload([listing()])
    payload["warnings"] = ["mobile.de: HTTP Error 403: Forbidden"]

    html = render_html_site(payload)

    assert "Quellen-Hinweise" in html
    assert "mobile.de" in html
    assert "HTTP Error 403" in html


def test_write_exports_creates_json_markdown_csv_and_html(tmp_path: Path):
    payload = build_feed_payload([listing()])
    write_exports(payload, tmp_path)

    assert (tmp_path / "feed" / "latest.md").exists()
    assert (tmp_path / "data" / "exports" / "latest.json").exists()
    assert (tmp_path / "data" / "exports" / "latest.csv").exists()
    assert (tmp_path / "site" / "index.html").exists()
    data = json.loads((tmp_path / "data" / "exports" / "latest.json").read_text())
    assert data["listings"][0]["image_urls"]
