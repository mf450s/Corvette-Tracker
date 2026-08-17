from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import fetch_html
from ..models import Listing
from ..normalize import normalize_listing

SOURCE = "Classic Trader"
DEFAULT_URL = "https://www.classic-trader.com/de/automobile/suche/chevrolet/corvette"


def _iter_json_ld_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_json_ld_objects(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_ld_objects(item)


def _extract_price(item: dict[str, Any]) -> str:
    offers = item.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = offers.get("price") if isinstance(offers, dict) else None
    return str(price or "")


def _extract_images(item: dict[str, Any]) -> list[str]:
    raw = item.get("image") or item.get("images") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(url) for url in raw if url]


def parse_classic_trader_search(html: str, base_url: str = DEFAULT_URL) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []
    seen_urls: set[str] = set()
    for script in soup.select('script[type="application/ld+json"]'):
        text = script.get_text(strip=True)
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        for obj in _iter_json_ld_objects(data):
            if obj.get("@type") not in {"Vehicle", "Car", "Product"}:
                continue
            title = str(obj.get("name") or obj.get("headline") or "")
            description = str(obj.get("description") or "")
            url = urljoin(base_url, str(obj.get("url") or ""))
            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            listing = normalize_listing(
                source=SOURCE,
                source_listing_id=url.rstrip("/").split("/")[-1],
                url=url,
                title=title,
                description=description,
                price_text=_extract_price(obj),
                location_raw="",
                image_urls=_extract_images(obj),
            )
            if listing:
                listings.append(listing)
    return listings


def fetch_classic_trader(url: str = DEFAULT_URL) -> list[Listing]:
    return parse_classic_trader_search(fetch_html(url), url)
