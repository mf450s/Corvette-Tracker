from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import fetch_html
from ..models import Listing
from ..normalize import normalize_listing

SOURCE = "Kleinanzeigen"
DEFAULT_URL = "https://www.kleinanzeigen.de/s-autos/chevrolet-corvette-c6/k0c216"


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _images(article, base_url: str) -> list[str]:
    urls: list[str] = []
    for img in article.select("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-imgsrc")
        if src and not src.startswith("data:"):
            urls.append(urljoin(base_url, src))
    return list(dict.fromkeys(urls))


def parse_kleinanzeigen_search(html: str, base_url: str = DEFAULT_URL) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.select("article.aditem") or soup.select("article") or soup.select("li.ad-listitem")
    listings: list[Listing] = []
    for index, article in enumerate(articles):
        text = _text(article)
        if "corvette" not in text.lower() and "c6" not in text.lower():
            continue
        title_node = article.select_one("h2")
        link = article.select_one('h2 a[href*="/s-anzeige/"]') or article.select_one('a[href*="/s-anzeige/"]')
        href = article.get("data-href") or (link.get("href") if link else None)
        if not href:
            continue
        title = _text(title_node) or _text(link) or text[:120]
        url = urljoin(base_url, href)
        source_id = article.get("data-adid") or article.get("id") or f"ka-{index}"
        price_node = article.select_one('[class*="price"]')
        desc_node = article.select_one('[class*="description"]')
        location_node = article.select_one('[class*="top--left"], [class*="location"]')
        location = _text(location_node)
        listing = normalize_listing(
            source=SOURCE,
            source_listing_id=str(source_id),
            url=url,
            title=title,
            description=" ".join([_text(desc_node), text]),
            price_text=_text(price_node) or text,
            location_raw=location,
            image_urls=_images(article, base_url),
        )
        if listing:
            listings.append(listing)
    return listings


def fetch_kleinanzeigen(url: str = DEFAULT_URL) -> list[Listing]:
    return parse_kleinanzeigen_search(fetch_html(url), url)
