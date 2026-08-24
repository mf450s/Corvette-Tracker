"""Re-scrape a single offer by ID or URL using existing source-specific parsing."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from .http import FetchError, fetch_html
from .models import Listing
from .normalize import (
    canonical_url,
    extract_transmission,
    normalize_listing,
    stable_id,
)
from .storage import TrackerStore

log = logging.getLogger(__name__)


SOURCE_DOMAINS: tuple[tuple[str, str], ...] = (
    ("kleinanzeigen", "Kleinanzeigen"),
    ("autoscout24", "AutoScout24"),
    ("autouncle", "AutoUncle"),
    ("classic-trader", "Classic Trader"),
    ("mobile", "mobile.de"),
)


def _identify_source(url: str) -> str | None:
    """Identify a source using the same ordered domain adapter table everywhere."""
    domain = urlparse(url).netloc.lower()
    return next((source for marker, source in SOURCE_DOMAINS if marker in domain), None)


def _re_scrape_kleinanzeigen(
    store: TrackerStore,
    existing_listing: Listing | None,
    url: str,
    html: str,
    *,
    caller_hint_id: str | None = None,
) -> dict[str, Any]:
    """Re-scrape a single Kleinanzeigen detail page.

    Uses the same detail-page logic as ``fetch_kleinanzeigen()``:
    - parses images from the detail page (higher resolution)
    - extracts price, mileage, and other facts via ``_merge_detail_facts``
    - merges everything into the existing listing and upserts to the store
    """
    # Lazy imports to avoid circular deps at module load
    from .sources.kleinanzeigen import (
        _merge_detail_facts,
        parse_kleinanzeigen_detail_images,
        parse_kleinanzeigen_detail_text,
    )

    listing = existing_listing

    # If no listing was found by ID, try to build one from the detail page HTML
    if listing is None:
        c_url = canonical_url(url)
        listing_id = stable_id("Kleinanzeigen", None, c_url)
        listing = store.get_listing(listing_id)

    if listing is None:
        # Still not found — create a fresh listing from the raw HTML
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.select_one("h1")
        title = " ".join(title_tag.get_text(" ", strip=True).split()) if title_tag else ""

        import re

        id_match = re.search(r"/(\d+)-216-", url)
        source_listing_id = id_match.group(1) if id_match else None

        raw = normalize_listing(
            source="Kleinanzeigen",
            source_listing_id=source_listing_id,
            url=url,
            title=title or "Unbekannt",
            description="",
            price_text="",
            location_raw=None,
            image_urls=[],
        )
        if raw is None:
            return {
                "success": False,
                "listing_id": caller_hint_id,
                "source": "Kleinanzeigen",
                "action": "parse_failed",
                "message": f"Konnte kein Listing aus {url} parsen (title={title!r})",
            }
        listing = raw

    # Parse detail page content
    detail_images = parse_kleinanzeigen_detail_images(html, url)
    detail_text = parse_kleinanzeigen_detail_text(html)

    # Merge detail facts into the listing (price, mileage, specs, etc.)
    updated = _merge_detail_facts(listing, html)
    if detail_images:
        updated.image_urls = detail_images
    if not updated.transmission:
        updated.transmission = extract_transmission(detail_text)

    # Save to database — upsert_listings handles change detection + snapshot
    saved = store.upsert_listings([updated])
    store.update_online_status(updated.id, is_online=True, http_status=200)

    change = saved[0].change_type if saved else "unknown"
    return {
        "success": True,
        "listing_id": updated.id,
        "source": "Kleinanzeigen",
        "action": "re_scraped",
        "change_type": change,
        "message": (
            f"Angebot {updated.id} ({updated.title}) neu gescraped: "
            f"{change}, {updated.price_eur} €, {updated.mileage_km} km"
        ),
    }


def _re_scrape_autoscout24(
    store: TrackerStore,
    existing_listing: Listing | None,
    url: str,
    html: str,
    *,
    caller_hint_id: str | None = None,
) -> dict[str, Any]:
    """Re-scrape a single AutoScout24 detail page.

    AutoScout24 detail pages embed listing data including full-resolution
    image URLs in a ``__NEXT_DATA__`` script tag.  This function parses
    the HTML via ``_parse_next_data`` and merges fresh images and other
    fields into the existing listing.
    """
    from .sources.autoscout24 import normalize_autoscout24_image_url, parse_autoscout24_search

    listing = existing_listing

    # If no existing listing, try to build one from the detail page HTML
    if listing is None:
        from .normalize import canonical_url, stable_id

        c_url = canonical_url(url)
        listing_id = stable_id("AutoScout24", None, c_url)
        listing = store.get_listing(listing_id)

    # Parse the detail page — parse_autoscout24_search uses __NEXT_DATA__
    parsed_listings = parse_autoscout24_search(html, url)
    if parsed_listings:
        fresh = parsed_listings[0]
        if listing is None:
            listing = fresh
        else:
            # Merge fresh detail-page fields into the existing listing
            if fresh.image_urls:
                listing.image_urls = [normalize_autoscout24_image_url(u) for u in fresh.image_urls]
            # AutoScout24 rewrites offer URL slugs (taxonomy migrations).
            # Adopt the canonical URL/title so later checks and re-scrapes
            # resolve directly and stale title prices are dropped.
            if fresh.url and fresh.url != listing.url:
                listing.url = fresh.url
            if fresh.title and fresh.title != listing.title:
                listing.title = fresh.title
            # The description is derived from title/details — refresh it too,
            # otherwise a stale title price (e.g. "EXP € 109.480,-") lingers.
            if fresh.description_text and fresh.description_text != listing.description_text:
                listing.description_text = fresh.description_text
            # Update price/mileage if the detail page shows different values
            if fresh.price_eur is not None:
                listing.price_eur = fresh.price_eur
            if fresh.mileage_km is not None:
                listing.mileage_km = fresh.mileage_km

    if listing is None:
        return {
            "success": False,
            "listing_id": caller_hint_id,
            "source": "AutoScout24",
            "action": "parse_failed",
            "message": f"Konnte kein Listing aus {url} parsen",
        }

    saved = store.upsert_listings([listing])
    store.update_online_status(listing.id, is_online=True, http_status=200)

    change = saved[0].change_type if saved else "unknown"
    return {
        "success": True,
        "listing_id": listing.id,
        "source": "AutoScout24",
        "action": "re_scraped",
        "change_type": change,
        "message": (
            f"Angebot {listing.id} ({listing.title}) neu gescraped: "
            f"{change}, {listing.price_eur} €, {listing.mileage_km} km, "
            f"{len(listing.image_urls)} Bilder"
        ),
    }


def _re_verify_generic(
    store: TrackerStore,
    existing_listing: Listing,
    url: str,
    *,
    caller_hint_id: str | None = None,
) -> dict[str, Any]:
    """Re-verify a listing for sources without detail-page parsing.

    Re-upserts the existing data so ``last_seen_at`` and the online status
    are refreshed.  This counts as a successful re-scrape — the offer is
    confirmed online even though no new detail fields are extracted.
    """
    store.upsert_listings([existing_listing])
    store.update_online_status(existing_listing.id, is_online=True, http_status=200)

    return {
        "success": True,
        "listing_id": existing_listing.id,
        "source": existing_listing.source,
        "action": "verified",
        "message": (
            f"Angebot {existing_listing.id} ({existing_listing.title}) "
            f"bestätigt online — keine Detail-Parsing für {existing_listing.source}"
        ),
    }


def re_scrape_offer(
    store: TrackerStore,
    *,
    offer_id: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """Re-scrape a single offer by its listing ID (database primary key) or URL.

    The function identifies which source the URL belongs to and uses the
    existing scraping logic for that source.  Currently **full detail-page
    re-scraping** (price, mileage, specs, images) is implemented for:

    - **Kleinanzeigen** — fetches and parses the detail page using the same
      logic as ``fetch_kleinanzeigen()``.
    - **AutoScout24** — parses the detail page's ``__NEXT_DATA__`` JSON to
      extract full-resolution images and current price/mileage.

    Other sources are **re-verified**: the URL is confirmed reachable,
    ``last_seen_at`` is bumped, and the online status is refreshed, but no
    new detail fields are re-extracted (the existing stored data is preserved).

    Parameters
    ----------
    store
        A connected ``TrackerStore`` instance.
    offer_id
        The listing's database ID (``Listing.id``).  Looked up in the store.
        Either this or *url* must be provided.
    url
        Direct URL of the offer.  Used when *offer_id* is not given.  Also
        used if *offer_id* is supplied but the listing's data is stale and
        the caller wants a fresh parse from the raw URL.

    Returns
    -------
    dict with keys:
        success (bool)      — whether the operation completed
        listing_id (str|None)
        source (str|None)
        action (str)        — ``re_scraped``, ``verified``, ``fetch_failed``,
                              ``parse_failed``, ``not_found``, or ``error``
        change_type (str|None)
        message (str)
    """
    # ── 1. Resolve listing ──────────────────────────────────────────────
    listing: Listing | None = None
    resolved_url: str | None = url
    caller_hint = offer_id or url

    if offer_id:
        listing = store.get_listing(offer_id)
        if listing is None:
            return {
                "success": False,
                "listing_id": offer_id,
                "action": "not_found",
                "message": f"Kein Listing mit ID {offer_id} in der Datenbank",
            }
        resolved_url = listing.url
    elif not url:
        return {
            "success": False,
            "listing_id": None,
            "action": "error",
            "message": "Es muss offer_id oder url angegeben werden",
        }

    # ── 2. Determine source ─────────────────────────────────────────────
    source = listing.source if listing else _identify_source(resolved_url or "")
    if not source:
        return {
            "success": False,
            "listing_id": offer_id,
            "action": "error",
            "message": f"Konnte keine Quelle für {resolved_url} identifizieren",
        }

    # ── 3. Fetch the detail page ────────────────────────────────────────
    assert resolved_url is not None  # guarded above
    fetch_target: str = resolved_url
    try:
        html = fetch_html(fetch_target, retries=1)
    except FetchError as exc:
        if listing:
            store.update_online_status(listing.id, is_online=False, error_message=str(exc))
        return {
            "success": False,
            "listing_id": listing.id if listing else None,
            "source": source,
            "action": "fetch_failed",
            "message": f"Fehler beim Abrufen: {exc}",
        }

    # ── 4. Source-specific re-scrape ────────────────────────────────────
    if source == "Kleinanzeigen":
        return _re_scrape_kleinanzeigen(
            store,
            listing,
            fetch_target,
            html,
            caller_hint_id=caller_hint,
        )

    if source == "AutoScout24":
        return _re_scrape_autoscout24(
            store,
            listing,
            fetch_target,
            html,
            caller_hint_id=caller_hint,
        )

    # ── 5. Fallback: re-verify for sources without detail parsing ───────
    if listing:
        return _re_verify_generic(store, listing, fetch_target, caller_hint_id=caller_hint)

    return {
        "success": False,
        "listing_id": offer_id,
        "source": source,
        "action": "no_listing",
        "message": f"Kein bestehendes Listing für {resolved_url} gefunden",
    }
