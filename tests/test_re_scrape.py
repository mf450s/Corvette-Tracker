"""Tests for the re_scrape_offer function."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from corvette_tracker.http import FetchError
from corvette_tracker.models import Listing
from corvette_tracker.re_scrape import SOURCE_DOMAINS, _identify_source, re_scrape_offer
from corvette_tracker.storage import TrackerStore

# ── _identify_source tests ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.kleinanzeigen.de/s-anzeige/foo-123-216-1406", "Kleinanzeigen"),
        ("https://www.autoscout24.de/angebote/corvette-xyz", "AutoScout24"),
        ("https://www.autouncle.de/de/d/chevrolet-corvette-12345", "AutoUncle"),
        ("https://www.classic-trader.com/de/automobile/chevrolet/corvette/42", "Classic Trader"),
        ("https://suchen.mobile.de/fahrzeuge/details.html?id=123", "mobile.de"),
        ("https://example.com/unknown", None),
        ("", None),
    ],
)
def test_identify_source(url: str, expected: str | None) -> None:
    assert _identify_source(url) == expected


def test_source_domain_registry_has_unique_markers_and_names() -> None:
    markers = [marker for marker, _ in SOURCE_DOMAINS]
    names = [name for _, name in SOURCE_DOMAINS]
    assert len(markers) == len(set(markers))
    assert len(names) == len(set(names))
    assert all(_identify_source(f"https://www.{marker}.example/") is not None for marker in markers)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> TrackerStore:
    db = tmp_path / "test_re_scrape.sqlite"
    return TrackerStore(db)


def _make_listing(**overrides: object) -> Listing:
    base = {
        "id": "kleinanzeigen_abc123",
        "source": "Kleinanzeigen",
        "source_listing_id": "12345",
        "url": "https://www.kleinanzeigen.de/s-anzeige/test-corvette-12345-216-1406",
        "title": "Corvette C6 Z06 Test",
        "price_eur": 35000,
        "mileage_km": 80000,
        "score": 50,
    }
    base.update(overrides)
    return Listing(**base)  # type: ignore[arg-type]


# ── re_scrape_offer: validation ──────────────────────────────────────────


def test_no_args(store: TrackerStore) -> None:
    result = re_scrape_offer(store)
    assert result["success"] is False
    assert result["action"] == "error"
    assert "offer_id" in result["message"] or "url" in result["message"]


def test_nonexistent_id(store: TrackerStore) -> None:
    result = re_scrape_offer(store, offer_id="does_not_exist")
    assert result["success"] is False
    assert result["action"] == "not_found"


# ── re_scrape_offer: Kleinanzeigen full re-scrape ────────────────────────


@patch("corvette_tracker.re_scrape.fetch_html")
def test_kleinanzeigen_with_existing_listing(mock_fetch_html, store: TrackerStore) -> None:
    """Full re-scrape via offer_id for a Kleinanzeigen listing."""
    # Arrange: add a listing to the DB
    listing = _make_listing()
    store.upsert_listings([listing])

    # Mock the detail page fetch — return minimal HTML (the parser will extract
    # what it can; most detail fields stay as-is from the existing listing).
    mock_fetch_html.return_value = (
        "<html><body>"
        "<h1>Corvette C6 Z06 Test</h1>"
        '<p id="viewad-price">34.900 €</p>'
        '<div class="addetailslist--detail">Erstzulassung 01/2009</div>'
        "</body></html>"
    )

    # Act
    result = re_scrape_offer(store, offer_id=listing.id)

    # Assert
    assert result["success"] is True, f"re-scrape failed: {result}"
    assert result["action"] == "re_scraped"
    assert result["source"] == "Kleinanzeigen"
    assert "listing_id" in result
    mock_fetch_html.assert_called_once()

    # Verify the DB was updated
    updated = store.get_listing(listing.id)
    assert updated is not None
    # The detail page parsed a new price (34.900 € = 34900)
    assert updated.price_eur == 34900


@patch("corvette_tracker.re_scrape.fetch_html")
def test_kleinanzeigen_with_url_only(mock_fetch_html, store: TrackerStore) -> None:
    """Re-scrape via URL — listing not yet in the DB, built from scratch."""
    url = "https://www.kleinanzeigen.de/s-anzeige/corvette-c6-54321-216-1406"
    mock_fetch_html.return_value = (
        "<html><body>"
        "<h1>Corvette C6 für Bastler</h1>"
        '<p id="viewad-price">12.500 €</p>'
        '<div class="addetailslist--detail">Kilometerstand 150.000 km</div>'
        '<div class="addetailslist--detail">Getriebe Schalter</div>'
        "</body></html>"
    )

    result = re_scrape_offer(store, url=url)

    assert result["success"] is True, f"re-scrape failed: {result}"
    assert result["action"] == "re_scraped"
    assert result["source"] == "Kleinanzeigen"
    mock_fetch_html.assert_called_once()


@patch("corvette_tracker.re_scrape.fetch_html")
def test_kleinanzeigen_fetch_failure(mock_fetch_html, store: TrackerStore) -> None:
    """When the detail page is unreachable, mark as offline."""
    listing = _make_listing()
    store.upsert_listings([listing])
    mock_fetch_html.side_effect = FetchError("connection refused")

    result = re_scrape_offer(store, offer_id=listing.id)

    assert result["success"] is False
    assert result["action"] == "fetch_failed"
    assert "connection refused" in result["message"]

    # Online status should be updated
    status = store.get_online_status(listing.id)
    assert status is not None
    assert status["is_online"] == 0


# ── re_scrape_offer: AutoScout24 full re-scrape ──────────────────────


AS24_DETAIL_HTML = """\
<html><body><script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"listingDetails":{"id":"e65b455d-a2cc-4bb9-adbd-77189c0a0dc4","url":"/angebote/corvette-zr1-benzin-gelb-e65b455d-a2cc-4bb9-adbd-77189c0a0dc4","price":{"priceRaw":119980,"priceFormatted":"€ 119.980"},"images":["https://prod.pictures.autoscout24.net/listing-images/e65b455d-a2cc-4bb9-adbd-77189c0a0dc4_9b8bede3-1558-4705-b93c-45e369c0882e.jpg/1280x960.webp","https://prod.pictures.autoscout24.net/listing-images/e65b455d-a2cc-4bb9-adbd-77189c0a0dc4_fc79520e-612a-4d48-ac3c-883cbd4dc94a.jpg/1280x960.webp","https://prod.pictures.autoscout24.net/listing-images/e65b455d-a2cc-4bb9-adbd-77189c0a0dc4_ca65c50c-e2ce-4af2-bac1-a392f098ebd9.jpg/1280x960.webp"],"location":{"zip":"8301","city":"Kainbach bei Graz"},"vehicle":{"make":"Chevrolet","model":"Corvette","modelVersionInput":"ZR1","mileageInKmRaw":39801,"firstRegistrationDate":"2010-06-01","powerInHp":647,"gearbox":"Manual","bodyType":"Coupe"},"vehicleDetails":[{"label":"Getriebe","data":"Schaltgetriebe"},{"label":"Karosserieform","data":"Coupé"},{"label":"Leistung","data":"476 kW (647 PS)"},{"label":"Kilometerstand","data":"39.801 km"}]}}}}
</script></body></html>
"""


@patch("corvette_tracker.re_scrape.fetch_html")
def test_autoscout24_with_existing_listing(mock_fetch_html, store: TrackerStore) -> None:
    """Re-scrape AutoScout24 via offer_id — parses __NEXT_DATA__ for images."""
    listing = Listing(
        id="autoscout24_e65b455d",
        source="AutoScout24",
        source_listing_id="e65b455d-a2cc-4bb9-adbd-77189c0a0dc4",
        url="https://www.autoscout24.de/angebote/corvette-zr1-benzin-gelb-e65b455d-a2cc-4bb9-adbd-77189c0a0dc4",
        title="Chevrolet Corvette ZR1",
        price_eur=119980,
        mileage_km=39801,
        image_urls=[],
        score=85,
    )
    store.upsert_listings([listing])
    mock_fetch_html.return_value = AS24_DETAIL_HTML

    result = re_scrape_offer(store, offer_id=listing.id)

    assert result["success"] is True, f"re-scrape failed: {result}"
    assert result["action"] == "re_scraped"
    assert result["source"] == "AutoScout24"

    # Verify images were extracted from __NEXT_DATA__
    updated = store.get_listing(listing.id)
    assert updated is not None
    assert len(updated.image_urls) == 3
    assert all("1920x1080.webp" in url for url in updated.image_urls)
    # Fresh detail text replaces the old description (drops stale title prices)
    assert updated.description_text is not None
    assert "EXP € 109.480" not in (updated.description_text or "")
    assert (
        updated.url
        == "https://www.autoscout24.de/angebote/corvette-zr1-benzin-gelb-e65b455d-a2cc-4bb9-adbd-77189c0a0dc4"
    )


@patch("corvette_tracker.re_scrape.fetch_html")
def test_autoscout24_with_url_only(mock_fetch_html, store: TrackerStore) -> None:
    """Re-scrape AutoScout24 via URL — listing not yet in DB, built from scratch."""
    url = "https://www.autoscout24.de/angebote/corvette-zr1-benzin-gelb-e65b455d-a2cc-4bb9-adbd-77189c0a0dc4"
    mock_fetch_html.return_value = AS24_DETAIL_HTML

    result = re_scrape_offer(store, url=url)

    assert result["success"] is True, f"re-scrape failed: {result}"
    assert result["action"] == "re_scraped"
    assert result["source"] == "AutoScout24"
    assert "Bilder" in result["message"]


@patch("corvette_tracker.re_scrape.fetch_html")
def test_autoscout24_empty_next_data(mock_fetch_html, store: TrackerStore) -> None:
    """AutoScout24 detail page without __NEXT_DATA__ falls through gracefully."""
    listing = Listing(
        id="autoscout24_noimg",
        source="AutoScout24",
        source_listing_id="noimg",
        url="https://www.autoscout24.de/angebote/corvette-c6-noimg",
        title="Corvette C6",
        price_eur=20000,
        mileage_km=100000,
        image_urls=[],
        score=40,
    )
    store.upsert_listings([listing])
    mock_fetch_html.return_value = "<html><body><h1>Corvette C6</h1></body></html>"

    result = re_scrape_offer(store, offer_id=listing.id)

    assert result["success"] is True
    assert result["action"] == "re_scraped"


# ── re_scrape_offer: generic re-verify ────────────────────────────────────


@patch("corvette_tracker.re_scrape.fetch_html")
def test_generic_source_verify(mock_fetch_html, store: TrackerStore) -> None:
    """Sources without detail-parsing fall through to re-verify."""
    listing = Listing(
        id="autouncle_abc123",
        source="AutoUncle",
        source_listing_id="abc123",
        url="https://www.autouncle.de/de/d/chevrolet-corvette-xyz",
        title="Chevrolet Corvette",
        price_eur=35000,
        mileage_km=70000,
        score=55,
    )
    store.upsert_listings([listing])
    mock_fetch_html.return_value = "<html><body><h1>Corvette</h1></body></html>"

    result = re_scrape_offer(store, offer_id=listing.id)

    assert result["success"] is True
    assert result["action"] == "verified"
    assert result["source"] == "AutoUncle"


@patch("corvette_tracker.re_scrape.fetch_html")
def test_unknown_source_url(mock_fetch_html, store: TrackerStore) -> None:
    """URL with an unrecognised domain returns error."""
    result = re_scrape_offer(store, url="https://example.com/nope")
    assert result["success"] is False
    assert result["action"] == "error"
    mock_fetch_html.assert_not_called()
