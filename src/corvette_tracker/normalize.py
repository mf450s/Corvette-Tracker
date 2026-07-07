from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from .models import Listing

C6_YEAR_RE = re.compile(r"\b(200[5-9]|201[0-3])\b")
PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})\s*(?:€|EUR|VB)?", re.I)
KM_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})\s*km\b", re.I)
HP_RE = re.compile(r"\b(\d{3,4})\s*(?:PS|HP)\b", re.I)
MONTH_YEAR_RE = re.compile(r"(?:EZ|Erstzulassung|HU|TÜV|TUV)?\s*(0?[1-9]|1[0-2])[./-](20\d{2}|19\d{2})", re.I)
VIN_RE = re.compile(r"\b[1-9A-HJ-NPR-Z]{17}\b", re.I)


def stable_id(source: str, source_listing_id: str | None, url: str) -> str:
    raw = source_listing_id or canonical_url(url)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{source.lower().replace(' ', '_')}_{digest}"


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _to_int(value: str) -> int | None:
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def extract_price_eur(text: str) -> int | None:
    for match in PRICE_RE.finditer(text or ""):
        value = _to_int(match.group(1))
        if value and 5_000 <= value <= 500_000:
            return value
    return None


def extract_mileage_km(text: str) -> int | None:
    match = KM_RE.search(text or "")
    value = _to_int(match.group(1)) if match else None
    if value is not None and value <= 500_000:
        return value
    return None


def extract_power_hp(text: str) -> int | None:
    match = HP_RE.search(text or "")
    if not match:
        return None
    hp = int(match.group(1))
    return hp if 250 <= hp <= 1000 else None


def extract_first_registration(text: str) -> str | None:
    for match in MONTH_YEAR_RE.finditer(text or ""):
        prefix = (text[max(0, match.start() - 18):match.start()] or "").lower()
        if "hu" in prefix or "tüv" in prefix or "tuv" in prefix:
            continue
        month = int(match.group(1))
        year = int(match.group(2))
        if 2005 <= year <= 2013:
            return f"{year:04d}-{month:02d}"
    year_match = C6_YEAR_RE.search(text or "")
    return f"{int(year_match.group(1)):04d}-01" if year_match else None


def extract_tuv_until(text: str) -> str | None:
    text = text or ""
    for match in re.finditer(r"(?:HU|TÜV|TUV)\s*(?:bis)?\s*(0?[1-9]|1[0-2])[./-](20\d{2})", text, re.I):
        return f"{int(match.group(2)):04d}-{int(match.group(1)):02d}"
    return None


def extract_engine(text: str) -> str | None:
    upper = (text or "").upper()
    for code in ("LS9", "LS7", "LS3", "LS2"):
        if code in upper:
            return code
    if "7.0" in upper or "7,0" in upper:
        return "LS7"
    if "KOMPRESSOR" in upper or "ZR1" in upper:
        return "LS9"
    if "6.2" in upper or "6,2" in upper:
        return "LS3"
    if "6.0" in upper or "6,0" in upper:
        return "LS2"
    return None


def extract_probable_engine_from_power(power_hp: int | None) -> tuple[str, float] | None:
    if power_hp is None:
        return None
    # C6 EU/US power figures overlap a bit by market/model year. Keep this as
    # an explicit confidence-bearing inference, never as a certain engine code.
    ranges: tuple[tuple[int, int, str, float], ...] = (
        (395, 410, "LS2", 0.86),
        (425, 445, "LS3", 0.86),
        (500, 520, "LS7", 0.90),
        (630, 660, "LS9", 0.92),
    )
    for lower, upper, engine, confidence in ranges:
        if lower <= power_hp <= upper:
            return engine, confidence
    return None


def extract_trim(text: str) -> str | None:
    upper = (text or "").upper()
    if "ZR1" in upper:
        return "ZR1"
    if "Z06" in upper or "Z 06" in upper:
        return "Z06"
    if "GRAND SPORT" in upper:
        return "Grand Sport"
    if "427" in upper or "CENTENNIAL" in upper:
        return "Special Edition"
    return "Base" if "CORVETTE" in upper else None


def extract_transmission(text: str) -> str | None:
    lower = (text or "").lower()
    if any(x in lower for x in ("schalter", "schaltgetriebe", "manual", "6-gang")):
        return "manual"
    if any(x in lower for x in ("automatik", "automatic", "a6", "aut.")):
        return "automatic"
    return None


def extract_vin(text: str) -> str | None:
    match = VIN_RE.search(text or "")
    return match.group(0).upper() if match else None


def detect_c6_candidate(title: str, description: str = "") -> bool:
    text = f"{title} {description}".upper()
    if any(token in text for token in ("C7", "C8", "LT1", "LT2", "STINGRAY C7", "MID ENGINE")):
        return False
    if "CORVETTE" not in text and "C6" not in text:
        return False
    if "C6" in text:
        return True
    if C6_YEAR_RE.search(text):
        return True
    if any(token in text for token in ("LS2", "LS3", "LS7", "LS9", "Z06", "ZR1", "GRAND SPORT")):
        return True
    return False


def extract_accident_status(text: str) -> str:
    lower = (text or "").lower()
    if any(token in lower for token in ("nicht unfallfrei", "unfallwagen", "unfallschaden", "reparierter unfall")):
        return "unfall"
    if "unfallfrei" in lower:
        return "unfallfrei"
    return "unbekannt"


def extract_risk_flags(text: str) -> list[str]:
    lower = (text or "").lower()
    flags: list[str] = []
    if any(x in lower for x in ("unfallwagen", "nicht unfallfrei", "unfallschaden", "reparierter unfall")):
        flags.append("accident_reported")
    if any(x in lower for x in ("frontschaden", "seitenschaden", "motorschaden", "getriebeschaden", "schaden", "beschädigt")):
        flags.append("damage_reported")
    if any(x in lower for x in ("ohne tüv", "ohne tuv", "hu abgelaufen", "nicht fahrbereit")):
        flags.append("no_tuv")
    if any(x in lower for x in ("us import", "usa import", "salvage", "rebuilt", "clean title", "carfax")):
        flags.append("salvage_import_possible")
    if any(x in lower for x in ("meilen", "miles", "abgelesen", "laut vorbesitzer")):
        flags.append("mileage_unclear")
    if any(x in lower for x in ("kompressorumbau", "tracktool", "rennstrecke", "softwareoptimierung")):
        flags.append("modified_heavily")
    if any(x in lower for x in ("verkauft", "reserviert")):
        flags.append("sold_or_reserved")
    return list(dict.fromkeys(flags))


def score_listing(price: int | None, mileage: int | None, trim: str | None, accident_status: str, risk_flags: list[str]) -> int:
    score = 50
    if trim in {"Grand Sport", "Z06", "ZR1"}:
        score += {"Grand Sport": 10, "Z06": 14, "ZR1": 18}[trim]
    if mileage is not None:
        if mileage < 50_000:
            score += 12
        elif mileage < 100_000:
            score += 7
        elif mileage > 160_000:
            score -= 8
    if price is not None:
        if price < 45_000:
            score += 8
        elif price > 90_000:
            score -= 4
    if accident_status == "unfallfrei":
        score += 8
    penalties = {
        "accident_reported": 18,
        "damage_reported": 14,
        "salvage_import_possible": 10,
        "mileage_unclear": 8,
        "no_tuv": 8,
        "modified_heavily": 4,
        "sold_or_reserved": 20,
    }
    score -= sum(penalties.get(flag, 0) for flag in risk_flags)
    return max(0, min(100, score))


def normalize_listing(
    *,
    source: str,
    source_listing_id: str | None,
    url: str,
    title: str,
    description: str = "",
    price_text: str = "",
    location_raw: str | None = None,
    image_urls: list[str] | None = None,
) -> Listing | None:
    combined = " ".join(x for x in [title, description, price_text, location_raw or ""] if x)
    if not detect_c6_candidate(title, combined):
        return None
    c_url = canonical_url(url)
    price = extract_price_eur(price_text) or extract_price_eur(combined)
    mileage = extract_mileage_km(combined)
    accident = extract_accident_status(combined)
    risks = extract_risk_flags(combined)
    engine = extract_engine(combined)
    power_hp = extract_power_hp(combined)
    probable_engine_match = extract_probable_engine_from_power(power_hp) if engine is None else None
    probable_engine = probable_engine_match[0] if probable_engine_match else None
    engine_confidence = 1.0 if engine else probable_engine_match[1] if probable_engine_match else None
    engine_note = (
        "Motorcode explizit im Inserat erkannt"
        if engine
        else f"Leistung {power_hp} PS → wahrscheinlich {probable_engine}" if probable_engine and power_hp else None
    )
    trim = extract_trim(combined)
    damage = None
    if "damage_reported" in risks:
        damage = "; ".join(flag for flag in risks if flag in {"damage_reported", "accident_reported"})
    origin_country = "US" if "salvage_import_possible" in risks and "import" in combined.lower() else None
    listing = Listing(
        id=stable_id(source, source_listing_id, c_url),
        source=source,
        source_listing_id=source_listing_id,
        url=c_url,
        title=" ".join(title.split()),
        generation="C6",
        model=f"Chevrolet Corvette C6 {trim}" if trim else "Chevrolet Corvette C6",
        price_eur=price,
        mileage_km=mileage,
        engine=engine,
        probable_engine=probable_engine,
        engine_confidence=engine_confidence,
        engine_note=engine_note,
        power_hp=power_hp,
        trim=trim,
        first_registration=extract_first_registration(combined),
        tuv_until=extract_tuv_until(combined),
        transmission=extract_transmission(combined),
        accident_status=accident,
        damage=damage,
        has_damage=True if "damage_reported" in risks else False if accident == "unfallfrei" else None,
        location_raw=(location_raw or "").strip() or None,
        location_country="DE" if location_raw else None,
        origin_country=origin_country,
        origin_confidence=0.7 if origin_country else None,
        vin=extract_vin(combined),
        image_urls=list(dict.fromkeys(image_urls or [])),
        description_text=" ".join(description.split()) or None,
        risk_flags=risks,
    )
    listing.score = score_listing(price, mileage, trim, accident, risks)
    return listing
