from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..http import fetch_html
from ..models import Listing
from ..normalize import extract_transmission, normalize_listing
from ..scoring import apply_score

SOURCE = "Kleinanzeigen"
DEFAULT_URL = "https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216"
DETAIL_IMAGE_RULE = "$_59.AUTO"


def _text(node) -> str:
    return " ".join(str(node.get_text(" ", strip=True)).split()) if node else ""


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
            candidates.extend(
                re.findall(
                    r"https://img\.kleinanzeigen\.de/api/v1/prod-ads/images/[^\s,\"'<>;)]+",
                    str(value),
                )
            )

    for script in soup.select("script"):
        candidates.extend(
            re.findall(
                r"https://img\.kleinanzeigen\.de/api/v1/prod-ads/images/[^\s,\"'<>;)]+",
                script.get_text(" ", strip=False),
            )
        )

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


def parse_kleinanzeigen_detail_text(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    return _text(soup)


def _detail_price_text(soup: BeautifulSoup) -> str:
    price_node = soup.select_one("#viewad-price, [id*=viewad-price]")
    if price_node:
        return _text(price_node)
    for node in soup.select('[class*="price"]'):
        text = _text(node)
        if re.search(r"(?:\d[\d.\s]*\s*€|\bVB\b|Verhandlungsbasis|auf Anfrage)", text, re.I):
            return text
    return ""


def _split_detail_label_value(node) -> tuple[str, str] | None:
    parts = [_text(child) for child in node.find_all(recursive=False)]
    parts = [part for part in parts if part]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])

    text = _text(node)
    for label in (
        "Kilometerstand",
        "Fahrzeugzustand",
        "Erstzulassung",
        "Kraftstoffart",
        "Leistung",
        "Getriebe",
        "Fahrzeugtyp",
        "HU bis",
        "Marke",
        "Modell",
    ):
        if text.lower().startswith(label.lower()):
            value = text[len(label) :].strip()
            if value:
                return label, value
    return None


def _detail_facts_text(soup: BeautifulSoup) -> str:
    facts: list[str] = []
    seen: set[tuple[str, str]] = set()

    for detail in soup.select(".addetailslist--detail"):
        split = _split_detail_label_value(detail)
        if not split:
            continue
        label, value = split
        key = (label.lower(), value.lower())
        if key not in seen:
            seen.add(key)
            facts.append(f"{label} {value}")

    for term in soup.select("dt"):
        value_node = term.find_next_sibling("dd")
        if not value_node:
            continue
        label = _text(term)
        value = _text(value_node)
        if not label or not value:
            continue
        key = (label.lower(), value.lower())
        if key not in seen:
            seen.add(key)
            facts.append(f"{label} {value}")

    return " ".join(facts)


def _merge_detail_facts(listing: Listing, detail_html: str) -> Listing:
    soup = BeautifulSoup(detail_html, "html.parser")
    price_text = _detail_price_text(soup)
    facts_text = _detail_facts_text(soup)
    if not price_text and not facts_text:
        return listing

    detail_listing = normalize_listing(
        source=listing.source,
        source_listing_id=listing.source_listing_id,
        url=listing.url,
        title=listing.title,
        description=facts_text,
        price_text=price_text,
        location_raw=listing.location_raw,
        image_urls=listing.image_urls,
    )
    if detail_listing is None:
        return listing

    for field in (
        "price_eur",
        "price_label",
        "mileage_km",
        "engine",
        "probable_engine",
        "engine_confidence",
        "engine_note",
        "power_hp",
        "estimated_power_hp",
        "power_note",
        "trim",
        "first_registration",
        "tuv_until",
        "transmission",
        "body_style",
        "accident_status",
        "damage",
        "has_damage",
        "origin_country",
        "origin_confidence",
        "vin",
    ):
        value = getattr(detail_listing, field)
        if value is not None:
            setattr(listing, field, value)

    listing.model = detail_listing.model or listing.model
    listing.risk_flags = list(dict.fromkeys([*listing.risk_flags, *detail_listing.risk_flags]))
    listing.inference_notes = list(
        dict.fromkeys([*listing.inference_notes, *detail_listing.inference_notes])
    )
    listing.conflict_flags = list(
        dict.fromkeys([*listing.conflict_flags, *detail_listing.conflict_flags])
    )
    return apply_score(listing)


def _listing_id_from_url(url: str, fallback: str) -> str:
    match = re.search(r"/(\d+)-216-", url)
    return str(match.group(1)) if match else fallback


def _fallback_listing_segments(html_text: str, base_url: str) -> list[Listing]:
    matches = list(
        re.finditer(
            r'<h2[^>]*>\s*<a[^>]+href=["\']([^"\']*/s-anzeige/[^"\']+)["\'][^>]*>(.*?)</a>\s*</h2>',
            html_text,
            flags=re.I | re.S,
        )
    )
    listings: list[Listing] = []
    for index, match in enumerate(matches):
        href = html.unescape(match.group(1))
        title = BeautifulSoup(match.group(2), "html.parser").get_text(" ", strip=True)
        if not title:
            continue
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else min(len(html_text), match.end() + 3000)
        )
        segment = html_text[match.start() : end]
        segment_soup = BeautifulSoup(segment, "html.parser")
        text = _text(segment_soup)
        url = urljoin(base_url, str(href))
        listing = normalize_listing(
            source=SOURCE,
            source_listing_id=_listing_id_from_url(url, f"ka-fallback-{index}"),
            url=url,
            title=title,
            description=text,
            price_text=text,
            location_raw=None,
            image_urls=_images(segment_soup, base_url),
        )
        if listing:
            listings.append(listing)
    return listings


def parse_kleinanzeigen_search(html_text: str, base_url: str = DEFAULT_URL) -> list[Listing]:
    soup = BeautifulSoup(html_text, "html.parser")
    articles = (
        soup.select("article.aditem") or soup.select("article") or soup.select("li.ad-listitem")
    )
    listings: list[Listing] = []
    for index, article in enumerate(articles):
        text = _text(article)
        if "corvette" not in text.lower() and "c6" not in text.lower():
            continue
        title_node = article.select_one("h2")
        link = article.select_one('h2 a[href*="/s-anzeige/"]') or article.select_one(
            'a[href*="/s-anzeige/"]'
        )
        href = article.get("data-href") or (link.get("href") if link else None)
        if not href:
            continue
        title = _text(title_node) or _text(link) or text[:120]
        url = urljoin(base_url, str(href))
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
    return _dedupe_listings(listings + _fallback_listing_segments(html_text, base_url))


def parse_kleinanzeigen_pagination_urls(html_text: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    base_host = urlparse(base_url).netloc
    urls: list[str] = []
    for link in soup.select(
        'a[href*="/s-autos/"][href*="seite:"], link[href*="/s-autos/"][href*="seite:"]'
    ):
        href = link.get("href")
        if not href:
            continue
        url = urljoin(base_url, str(href))
        parsed = urlparse(url)
        if parsed.netloc == base_host and "/s-anzeige/" not in parsed.path:
            urls.append(url)
    for href in re.findall(r'href=["\']([^"\']*/s-autos/[^"\']*seite:[^"\']+)["\']', html_text):
        url = urljoin(base_url, html.unescape(href))
        parsed = urlparse(url)
        if parsed.netloc == base_host and "/s-anzeige/" not in parsed.path:
            urls.append(url)
    return list(dict.fromkeys(urls))


def _dedupe_listings(listings: list[Listing]) -> list[Listing]:
    deduped: list[Listing] = []
    seen_ids: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    for listing in listings:
        id_key = (listing.source, listing.source_listing_id or listing.url)
        if id_key in seen_ids or listing.url in seen_urls:
            continue
        seen_ids.add(id_key)
        seen_urls.add(listing.url)
        deduped.append(listing)
    return deduped


def fetch_kleinanzeigen(url: str = DEFAULT_URL) -> list[Listing]:
    html_by_url: dict[str, str] = {url: fetch_html(url)}
    for page_url in parse_kleinanzeigen_pagination_urls(html_by_url[url], url):
        try:
            html_by_url[page_url] = fetch_html(page_url)
        except Exception:
            continue

    listings = _dedupe_listings(
        [
            listing
            for page_url, html in html_by_url.items()
            for listing in parse_kleinanzeigen_search(html, page_url)
        ]
    )
    for listing in listings:
        try:
            detail_html = fetch_html(listing.url)
            detail_images = parse_kleinanzeigen_detail_images(detail_html, listing.url)
            detail_text = parse_kleinanzeigen_detail_text(detail_html)
        except Exception:
            detail_html = ""
            detail_images = []
            detail_text = ""
        if detail_images:
            listing.image_urls = detail_images
        listing = _merge_detail_facts(listing, detail_html) if detail_text else listing
        if not listing.transmission:
            listing.transmission = extract_transmission(detail_text)
    return listings
