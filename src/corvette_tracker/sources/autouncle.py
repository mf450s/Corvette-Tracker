from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import fetch_html
from ..models import Listing
from ..normalize import normalize_listing

SOURCE = "AutoUncle"
DEFAULT_URL = "https://www.autouncle.de/de/gebrauchtwagen/Chevrolet/Corvette"


def _text(node) -> str:
    return " ".join(str(node.get_text(" ", strip=True)).split()) if node else ""


def _price_text(text: str) -> str:
    match = re.search(r"(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})\s*€", text)
    return match.group(0) if match else text


def parse_autouncle_search(html: str, base_url: str = DEFAULT_URL) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []
    seen_urls: set[str] = set()

    for article in soup.select("article"):
        link = article.select_one('a[href*="/de/d/"]')
        if not link:
            continue
        href = link.get("href")
        if not href:
            continue
        url = urljoin(base_url, str(href))
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Title + specs from the <a> tag
        text = _text(link)
        if "corvette" not in text.lower():
            continue
        title = text.split("|")[0].replace("Gebraucht", "").strip(' ()"') or "Chevrolet Corvette"

        # Price from the dedicated price element outside the <a> tag
        price_el = article.select_one("._i2QOc")
        price_text = _text(price_el) if price_el else ""

        # Image from the dedicated image area outside the <a> tag
        image_urls: list[str] = []
        img = article.select_one("._v1SHB img")
        if img:
            src = img.get("src") or img.get("data-src")
            src_text = str(src or "")
            if src_text and not src_text.startswith("data:"):
                image_urls.append(urljoin(base_url, src_text))

        listing = normalize_listing(
            source=SOURCE,
            source_listing_id=str(href).rstrip("/").split("/")[-1],
            url=url,
            title=title,
            description=text,
            price_text=price_text,
            location_raw="",
            image_urls=image_urls,
        )
        if listing:
            listings.append(listing)
    return listings


def fetch_autouncle(url: str = DEFAULT_URL) -> list[Listing]:
    return parse_autouncle_search(fetch_html(url, retries=4), url)
