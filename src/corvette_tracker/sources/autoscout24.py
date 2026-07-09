from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import fetch_html
from ..models import Listing
from ..normalize import normalize_listing

SOURCE = "AutoScout24"
DEFAULT_URL = "https://www.autoscout24.de/lst/chevrolet/corvette?atype=C&cy=D%2CA%2CB%2CE%2CF%2CI%2CL%2CNL&damaged_listing=exclude&desc=0&fregfrom=2005&fregto=2013&ocs_listing=include&powertype=kw&sort=standard&ustate=N%2CU"
HIGH_RES_IMAGE_VARIANT = "1920x1080.webp"


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def normalize_autoscout24_image_url(url: str) -> str:
    """Prefer a large AutoScout24 CDN rendition over the search thumbnail.

    AutoScout24 image URLs are commonly shaped like:
    `.../listing-image.jpg/250x188.webp`. The CDN accepts larger rendition
    suffixes for the same source image. Keep unrelated URLs unchanged.
    """
    if "prod.pictures.autoscout24.net/listing-images/" not in url:
        return url
    return re.sub(r"/\d+x\d+\.(?:webp|jpg)$", f"/{HIGH_RES_IMAGE_VARIANT}", url)


def _first_href(article, base_url: str) -> str | None:
    for link in article.select("a[href]"):
        href = link.get("href")
        if href and ("/angebote/" in href or "corvette" in href.lower()):
            return urljoin(base_url, href)
    link = article.select_one("a[href]")
    return urljoin(base_url, link.get("href")) if link else None


def _images(article, base_url: str) -> list[str]:
    urls: list[str] = []
    for img in article.select("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if src and not src.startswith("data:"):
            urls.append(normalize_autoscout24_image_url(urljoin(base_url, src)))
    return list(dict.fromkeys(urls))


def _parse_next_data(soup: BeautifulSoup, base_url: str) -> list[Listing]:
    script = soup.select_one("script#__NEXT_DATA__")
    if not script or not script.get_text(strip=True):
        return []
    try:
        data = json.loads(script.get_text())
    except json.JSONDecodeError:
        return []
    page_props = data.get("props", {}).get("pageProps", {})
    detail_listing = page_props.get("listingDetails")
    raw_listings = [detail_listing] if isinstance(detail_listing, dict) else page_props.get("listings", []) or []
    listings: list[Listing] = []
    for raw in raw_listings:
        vehicle = raw.get("vehicle") or {}
        details = " ".join(
            " ".join(str(value).strip() for value in ((item or {}).get("label"), (item or {}).get("data")) if str(value or "").strip())
            for item in raw.get("vehicleDetails", []) or []
        )
        title_parts = [vehicle.get("make") or "Chevrolet", vehicle.get("model") or "Corvette", vehicle.get("modelVersionInput") or ""]
        title = " ".join(str(part).strip() for part in title_parts if str(part or "").strip())
        price = raw.get("price") or {}
        location = raw.get("location") or {}
        location_raw = " ".join(str(x).strip() for x in [location.get("zip"), location.get("city")] if str(x or "").strip())
        url = urljoin(base_url, raw.get("url") or "")
        vehicle_values = " ".join(str(value) for value in vehicle.values() if isinstance(value, str | int | float))
        description = " ".join([title, details, vehicle_values, location_raw])
        listing = normalize_listing(
            source=SOURCE,
            source_listing_id=str(raw.get("id") or raw.get("identifier") or url),
            url=url,
            title=title,
            description=description,
            price_text=str(price.get("priceFormatted") or price.get("priceRaw") or ""),
            location_raw=location_raw,
            image_urls=[normalize_autoscout24_image_url(str(image)) for image in (raw.get("images") or []) if image],
        )
        if listing:
            if price.get("priceRaw"):
                listing.price_eur = int(price["priceRaw"])
            if vehicle.get("mileageInKmRaw") and listing.mileage_km is None:
                listing.mileage_km = int(vehicle["mileageInKmRaw"])
            listings.append(listing)
    return listings


def parse_autoscout24_search(html: str, base_url: str = DEFAULT_URL) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    next_data_listings = _parse_next_data(soup, base_url)
    if next_data_listings:
        return next_data_listings
    articles = soup.select('article[data-testid="list-item"], article[class*="ListItem"], article')
    listings: list[Listing] = []
    for index, article in enumerate(articles):
        text = _text(article)
        if "corvette" not in text.lower() and "c6" not in text.lower():
            continue
        url = _first_href(article, base_url)
        if not url:
            continue
        title_node = article.select_one("h2, a")
        title = _text(title_node) or text[:120]
        source_id = article.get("id") or article.get("data-guid") or article.get("data-id") or f"as24-{index}"
        price_node = article.find(string=lambda s: bool(s and "€" in s))
        price_text = str(price_node or text)
        location = ""
        for token in ("München", "Hamburg", "Berlin", "Köln", "Düsseldorf", "Stuttgart", "Frankfurt"):
            if token.lower() in text.lower():
                location = token
                break
        listing = normalize_listing(
            source=SOURCE,
            source_listing_id=str(source_id),
            url=url,
            title=title,
            description=text,
            price_text=price_text,
            location_raw=location,
            image_urls=_images(article, base_url),
        )
        if listing:
            listings.append(listing)
    return listings


def fetch_autoscout24(url: str = DEFAULT_URL) -> list[Listing]:
    return parse_autoscout24_search(fetch_html(url), url)
