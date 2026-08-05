from __future__ import annotations

from corvette_tracker.favicon import favicon_data_uri
from corvette_tracker.web import render_app_shell
from corvette_tracker.feed import render_html_site


def test_favicon_data_uri_returns_svg_data_uri() -> None:
    uri = favicon_data_uri()
    assert uri.startswith("data:image/svg+xml,")
    assert "%3Csvg" in uri


def test_app_shell_contains_favicon_link() -> None:
    html = render_app_shell()
    assert 'rel="icon"' in html
    assert "image/svg+xml" in html


def test_html_site_contains_favicon_link() -> None:
    # Minimal‑Payload, das render_html_site ohne Exception verarbeitet.
    payload = {
        "generated_at": "2025-01-01T00:00:00+00:00",
        "summary": {
            "total_active": 0,
            "new_listings": 0,
            "changed_listings": 0,
            "price_changes": 0,
            "risk_warnings": 0,
            "avg_price_eur": None,
            "median_price_eur": None,
            "min_price_eur": None,
            "max_price_eur": None,
            "avg_mileage_km": None,
            "sources": [],
            "trims": [],
        },
        "listings": [],
        "warnings": [],
    }
    html = render_html_site(payload)
    assert 'rel="icon"' in html
    assert "image/svg+xml" in html
