from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from .models import Listing
from .scoring import apply_score
from .validation import apply_validation_flags

C6_YEAR_RE = re.compile(r"\b(200[5-9]|201[0-3])\b")
# Dotted prices (e.g. "54.900") with optional €/EUR/VB suffix.
# (?!\d) prevents matching partial dates like "08.201" from "08.2010".
PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+|\d{4,6})\s*(?:€|EUR|VB)?(?!\d)", re.I)
# \d{5,6} avoids matching years like "2011 km" as mileage (min realistic ~10000 km).
KM_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+|\d{5,6})\s*km\b", re.I)
HP_RE = re.compile(r"\b(\d{3,4})\s*(?:PS|HP)\b", re.I)
MONTH_YEAR_RE = re.compile(r"(?:EZ|Erstzulassung|HU|TÜV|TUV)?\s*(0?[1-9]|1[0-2])[./-](20\d{2}|19\d{2})", re.I)
VIN_RE = re.compile(r"\b[1-9A-HJ-NPR-Z]{17}\b", re.I)
SEARCH_REQUEST_TITLE_RE = re.compile(r"\bsuche\b", re.I)


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
    if not text:
        return None
    first_bare: int | None = None
    for match in PRICE_RE.finditer(text):
        value = _to_int(match.group(1))
        if not value or not (5_000 <= value <= 500_000):
            continue
        # Check if this match has an explicit currency marker (€/EUR) right after the number
        after_group1 = text[match.end(1):match.end(0)].strip()
        if after_group1:
            return value  # Explicit €/EUR/VB → unambiguous price
        # Bare number: skip if "km" appears nearby (mileage context, not price)
        before = text[max(0, match.start() - 20):match.start()].lower()
        after = text[match.end():match.end() + 15].lower()
        if re.search(r'\bkm\b', before) or re.search(r'\bkm\b', after):
            continue
        if first_bare is None:
            first_bare = value
    return first_bare


def extract_price_label(text: str) -> str | None:
    lower = (text or "").strip().lower()
    if not lower:
        return None
    if "zu verschenken" in lower or "verschenken" in lower:
        return "zu verschenken"
    if re.search(r"\bvb\b", lower) or "verhandlungsbasis" in lower:
        return "VB"
    if "auf anfrage" in lower or "preis auf anfrage" in lower:
        return "auf Anfrage"
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
    if re.search(r"(?<!\d)7[,.]0\s*(?:L|V8|V\s*8|$)", upper):
        return "LS7"
    if "KOMPRESSOR" in upper or "ZR1" in upper:
        return "LS9"
    if re.search(r"(?<!\d)6[,.]2\s*(?:L|V8|V\s*8|$)", upper):
        return "LS3"
    if re.search(r"(?<!\d)6[,.]0\s*(?:L|V8|V\s*8|$)", upper):
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


def estimate_power_from_engine(engine: str | None) -> int | None:
    if engine is None:
        return None
    return {"LS2": 404, "LS3": 437, "LS7": 512, "LS9": 647}.get(engine)


def _extract_specific_trim(text: str) -> str | None:
    upper = (text or "").upper()
    if "ZR1" in upper or "ZR 1" in upper:
        return "ZR1"
    if "Z06" in upper or "Z 06" in upper or "ZO6" in upper:
        return "Z06"
    if "GRAND SPORT" in upper or "GRAND-SPORT" in upper:
        return "Grand Sport"
    if "427" in upper or "CENTENNIAL" in upper:
        return "Special Edition"
    return None


def extract_trim(text: str) -> str | None:
    return _extract_specific_trim(text) or ("Base" if "CORVETTE" in (text or "").upper() else None)


def extract_transmission(text: str) -> str | None:
    lower = (text or "").lower()
    if any(x in lower for x in ("schalter", "schaltgetriebe", "handschaltung", "manual", "6-gang")):
        return "manual"
    if re.search(r"\bgetriebe\s*:?\s*manuell\b", lower) or re.search(r"\bmanuell\b", lower):
        return "manual"
    if any(x in lower for x in ("automatik", "automatic", "a6", "aut.")):
        return "automatic"
    return None


def extract_body_style(text: str) -> str | None:
    lower = (text or "").lower()
    if any(x in lower for x in ("cabrio", "convertible", "roadster")):
        return "Cabrio"
    if any(x in lower for x in ("targa", "t-top", "t top", "removable roof", "hardtop")):
        return "Targa"
    if any(x in lower for x in ("coupé", "coupe", "coup")):
        return "Coupé"
    return None


def extract_vin(text: str) -> str | None:
    match = VIN_RE.search(text or "")
    return match.group(0).upper() if match else None


C6_TOKEN_RE = re.compile(r"\bC\s*6\b", re.I)
C7_C8_TOKEN_RE = re.compile(r"\bC\s*[78]\b|STINGRAY C\s*7|MID ENGINE", re.I)
C7_C8_ENGINE_RE = re.compile(r"\b(LT1|LT2|LT4|LT5)\b|\b5[,.]5\s*V8\b", re.I)


def is_search_request_title(title: str) -> bool:
    return bool(SEARCH_REQUEST_TITLE_RE.search(title or ""))


def detect_c6_candidate(title: str, description: str = "") -> bool:
    title_text = title or ""
    if is_search_request_title(title_text):
        return False
    text = f"{title_text} {description}"
    upper = text.upper()
    if "CORVETTE" not in upper and not C6_TOKEN_RE.search(text):
        return False
    if C7_C8_TOKEN_RE.search(text) or C7_C8_ENGINE_RE.search(text):
        return False
    if C6_TOKEN_RE.search(text):
        return True
    if C6_YEAR_RE.search(upper):
        return True
    if any(token in upper for token in ("LS2", "LS3", "LS7", "LS9")):
        return True
    # Z06, ZR1 and Grand Sport exist across generations. Without C6 year/engine
    # evidence they are too broad, especially when searches include C7/C8.
    if any(token in upper for token in ("Z06", "ZR1", "GRAND SPORT")):
        return False
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


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def apply_c6_inferences(
    *,
    engine: str | None,
    trim: str | None,
    transmission: str | None,
    body_style: str | None,
) -> tuple[str | None, str | None, str | None, list[str], list[str]]:
    inference_notes: list[str] = []
    conflict_flags: list[str] = []

    inferred_trim = trim
    if engine == "LS7":
        if inferred_trim and inferred_trim != "Z06":
            _append_unique(conflict_flags, f"conflict_ls7_trim_{inferred_trim.lower().replace(' ', '_')}")
        if inferred_trim != "Z06":
            _append_unique(inference_notes, "LS7 → Z06")
        inferred_trim = "Z06"
    elif engine == "LS9":
        if inferred_trim and inferred_trim != "ZR1":
            _append_unique(conflict_flags, f"conflict_ls9_trim_{inferred_trim.lower().replace(' ', '_')}")
        if inferred_trim != "ZR1":
            _append_unique(inference_notes, "LS9 → ZR1")
        inferred_trim = "ZR1"

    inferred_transmission = transmission
    if inferred_trim in {"Z06", "ZR1"}:
        if inferred_transmission and inferred_transmission != "manual":
            _append_unique(conflict_flags, f"conflict_{inferred_trim.lower()}_transmission_{inferred_transmission}")
        if inferred_transmission != "manual":
            _append_unique(inference_notes, f"{inferred_trim} → Schalter")
        inferred_transmission = "manual"

    inferred_body_style = body_style
    if inferred_trim in {"Z06", "ZR1"}:
        if inferred_body_style and inferred_body_style != "Coupé":
            _append_unique(conflict_flags, f"conflict_{inferred_trim.lower()}_body_{inferred_body_style.lower()}")
        if inferred_body_style != "Coupé":
            _append_unique(inference_notes, f"{inferred_trim} → Coupé")
        inferred_body_style = "Coupé"
    else:
        if inferred_body_style == "Coupé":
            _append_unique(inference_notes, "Coupé/Coupe → Targa")
            inferred_body_style = "Targa"
        if inferred_body_style == "Targa" and body_style in {"Targa", "Coupé"}:
            _append_unique(inference_notes, "Coupé/Coupe → Targa")

    return inferred_trim, inferred_transmission, inferred_body_style, inference_notes, conflict_flags


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
    price = extract_price_eur(price_text)
    price_label = extract_price_label(price_text)
    if price is None and price_label is None:
        price = extract_price_eur(combined)
        price_label = extract_price_label(combined) if price is None else None
    mileage = extract_mileage_km(combined)
    accident = extract_accident_status(combined)
    risks = extract_risk_flags(combined)
    engine = extract_engine(combined)
    power_hp = extract_power_hp(combined)
    probable_engine_match = extract_probable_engine_from_power(power_hp) if engine is None else None
    probable_engine = probable_engine_match[0] if probable_engine_match else None
    display_engine_for_power = engine or probable_engine
    estimated_power_hp = estimate_power_from_engine(display_engine_for_power) if power_hp is None else None
    power_note = (
        f"Motor {display_engine_for_power} → Leistung ca. {estimated_power_hp} PS geschätzt"
        if estimated_power_hp and display_engine_for_power
        else None
    )
    engine_confidence = 1.0 if engine else probable_engine_match[1] if probable_engine_match else None
    engine_note = (
        "Motorcode explizit im Inserat erkannt"
        if engine
        else f"Leistung {power_hp} PS → wahrscheinlich {probable_engine}" if probable_engine and power_hp else None
    )
    title_upper = title.upper()
    trim = (
        _extract_specific_trim(title)
        or ("Base" if "CORVETTE" in title_upper or "C6" in title_upper else None)
        or _extract_specific_trim(combined)
        or ("Base" if "CORVETTE" in combined.upper() else None)
    )
    transmission = extract_transmission(combined)
    body_style = extract_body_style(title) or extract_body_style(combined)
    trim, transmission, body_style, inference_notes, conflict_flags = apply_c6_inferences(
        engine=engine,
        trim=trim,
        transmission=transmission,
        body_style=body_style,
    )
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
        model=f"Chevrolet Corvette C6 {body_style}" if trim == "Base" and body_style else f"Chevrolet Corvette C6 {trim}" if trim else "Chevrolet Corvette C6",
        price_eur=price,
        price_label=price_label,
        mileage_km=mileage,
        engine=engine,
        probable_engine=probable_engine,
        engine_confidence=engine_confidence,
        engine_note=engine_note,
        power_hp=power_hp,
        estimated_power_hp=estimated_power_hp,
        power_note=power_note,
        trim=trim,
        first_registration=extract_first_registration(combined),
        tuv_until=extract_tuv_until(combined),
        transmission=transmission,
        body_style=body_style,
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
        inference_notes=inference_notes,
        conflict_flags=conflict_flags,
    )
    listing = apply_validation_flags(listing)
    return apply_score(listing)
