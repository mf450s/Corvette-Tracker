from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import fetch_html
from ..models import Listing
from ..normalize import normalize_listing

SOURCE = "AutoUncle"
DEFAULT_URL = "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette?freetext=C6"


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _page_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    for img in soup.select("img"):
        src = img.get("src") or img.get("data-src")
        if src and not src.startswith("data:") and ("car_images" in src or "autouncle" in src):
            urls.append(urljoin(base_url, src))
    return list(dict.fromkeys(urls))


def _listing_images(node, base_url: str) -> list[str]:
    urls: list[str] = []
    for img in node.select("img"):
        src = img.get("src") or img.get("data-src")
        if src and not src.startswith("data:") and "car_images" in src:
            urls.append(urljoin(base_url, src))
    return list(dict.fromkeys(urls))


def _price_text(text: str) -> str:
    match = re.search(r"(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})\s*€", text)
    return match.group(0) if match else text


def parse_autouncle_search(html: str, base_url: str = DEFAULT_URL) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    page_images = _page_images(soup, base_url)
    listings: list[Listing] = []
    seen_urls: set[str] = set()
    for index, link in enumerate(soup.select('a[href*="/de/d/"]')):
        href = link.get("href")
        if not href:
            continue
        url = urljoin(base_url, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        text = _text(link)
        if "corvette" not in text.lower():
            continue
        title = text.split("|")[0].replace("Gebraucht", "").strip(" ()") or "Chevrolet Corvette"
        listing = normalize_listing(
            source=SOURCE,
            source_listing_id=href.rstrip("/").split("/")[-1],
            url=url,
            title=title,
            description=text,
            price_text=_price_text(text),
            location_raw="",
            image_urls=_listing_images(link, base_url) or page_images[index:index + 1] or page_images[:1],
        )
        if listing:
            listings.append(listing)
    return listings


def fetch_autouncle(url: str = DEFAULT_URL) -> list[Listing]:
    return parse_autouncle_search(fetch_html(url, retries=4), url)
