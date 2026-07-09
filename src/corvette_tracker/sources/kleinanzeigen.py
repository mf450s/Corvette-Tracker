from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..http import fetch_html
from ..models import Listing
from ..normalize import extract_transmission, normalize_listing

SOURCE = "Kleinanzeigen"
DEFAULT_URL = "https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216"
DETAIL_IMAGE_RULE = "$_59.AUTO"


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def normalize_kleinanzeigen_image_url(url: str) -> str:
    if "img.kleinanzeigen.de/api/v1/prod-ads/images/" not in url:
        return url
    if "?rule=" in url:
        return re.sub(r"\?rule=\$_\d+\.(?:AUTO|JPG)", f"?rule={DETAIL_IMAGE_RULE}", url)
    return f"{url}?rule={DETAIL_IMAGE_RULE}"


def _images(article, base_url: str) -> list[str]:
    urls: list[str] = []
    for img in article.select("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-imgsrc")
        if src and not src.startswith("data:"):
            urls.append(normalize_kleinanzeigen_image_url(urljoin(base_url, src)))
    return list(dict.fromkeys(urls))


def parse_kleinanzeigen_detail_images(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    for img in soup.select("img"):
        for attr in ("src", "data-src", "data-imgsrc", "srcset"):
            value = img.get(attr)
            if not value:
                continue
            candidates.extend(re.findall(r"https://img\.kleinanzeigen\.de/api/v1/prod-ads/images/[^\s,\"'<>;)]+", value))

    for script in soup.select("script"):
        candidates.extend(re.findall(r"https://img\.kleinanzeigen\.de/api/v1/prod-ads/images/[^\s,\"'<>;)]+", script.get_text(" ", strip=False)))

    normalized: list[str] = []
    seen_base_ids: set[str] = set()
    for candidate in candidates:
        url = normalize_kleinanzeigen_image_url(urljoin(base_url, candidate))
        image_id = url.split("?", 1)[0]
        if image_id in seen_base_ids:
            continue
        seen_base_ids.add(image_id)
        normalized.append(url)
    return normalized


def parse_kleinanzeigen_detail_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return _text(soup)


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


def parse_kleinanzeigen_pagination_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc
    urls: list[str] = []
    for link in soup.select('a[href*="/s-autos/"][href*="seite:"]'):
        href = link.get("href")
        if not href:
            continue
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.netloc == base_host and "/s-anzeige/" not in parsed.path:
            urls.append(url)
    return list(dict.fromkeys(urls))


def _dedupe_listings(listings: list[Listing]) -> list[Listing]:
    deduped: list[Listing] = []
    seen: set[tuple[str, str]] = set()
    for listing in listings:
        key = (listing.source, listing.source_listing_id or listing.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(listing)
    return deduped


def fetch_kleinanzeigen(url: str = DEFAULT_URL) -> list[Listing]:
    html_by_url: dict[str, str] = {url: fetch_html(url)}
    for page_url in parse_kleinanzeigen_pagination_urls(html_by_url[url], url):
        try:
            html_by_url[page_url] = fetch_html(page_url)
        except Exception:
            continue

    listings = _dedupe_listings([
        listing
        for page_url, html in html_by_url.items()
        for listing in parse_kleinanzeigen_search(html, page_url)
    ])
    for listing in listings:
        try:
            detail_html = fetch_html(listing.url)
            detail_images = parse_kleinanzeigen_detail_images(detail_html, listing.url)
            detail_text = parse_kleinanzeigen_detail_text(detail_html)
        except Exception:
            detail_images = []
            detail_text = ""
        if detail_images:
            listing.image_urls = detail_images
        if not listing.transmission:
            listing.transmission = extract_transmission(detail_text)
    return listings
