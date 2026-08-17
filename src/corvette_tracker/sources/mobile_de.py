from __future__ import annotations

from bs4 import BeautifulSoup

from ..http import FetchError, fetch_html
from ..models import Listing
from ..normalize import normalize_listing
from .autoscout24 import _images, _text

SOURCE = "mobile.de"
DEFAULT_URL = "https://suchen.mobile.de/fahrzeuge/search.html?dam=false&fr=2005%3A2013&isSearchRequest=true&ms=5600%3B36%3B%3B&ref=quickSearch&s=Car&sb=rel&vc=Car"


def parse_mobile_de_search(html: str, base_url: str = DEFAULT_URL) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.select('article, div[data-testid*="result"], div[class*="vehicle-data"]')
    listings: list[Listing] = []
    for index, article in enumerate(articles):
        text = _text(article)
        if "corvette" not in text.lower() and "c6" not in text.lower():
            continue
        link = article.select_one(
            'a[href*="/fahrzeuge/details.html"], a[href*="/auto-inserat/"], a[href]'
        )
        if not link:
            continue
        from urllib.parse import urljoin

        url = urljoin(base_url, str(link.get("href") or ""))
        title_node = article.select_one("h2, h3, a")
        title = _text(title_node) or text[:120]
        source_id = article.get("data-testid") or article.get("id") or f"mobile-{index}"
        listing = normalize_listing(
            source=SOURCE,
            source_listing_id=str(source_id),
            url=url,
            title=title,
            description=text,
            price_text=text,
            location_raw="",
            image_urls=_images(article, base_url),
        )
        if listing:
            listings.append(listing)
    return listings


def fetch_mobile_de(url: str = DEFAULT_URL) -> list[Listing]:
    try:
        return parse_mobile_de_search(fetch_html(url), url)
    except FetchError:
        raise
