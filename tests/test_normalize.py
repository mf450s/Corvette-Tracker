from corvette_tracker.normalize import (
    detect_c6_candidate,
    extract_engine,
    extract_first_registration,
    extract_mileage_km,
    extract_power_hp,
    extract_price_eur,
    extract_probable_engine_from_power,
    extract_risk_flags,
    extract_trim,
    normalize_listing,
)


def test_extract_price_eur_handles_german_format():
    assert extract_price_eur("Chevrolet Corvette C6 - 54.900 € VB") == 54900


def test_extract_mileage_km_handles_dots_and_units():
    assert extract_mileage_km("68.000 km, gepflegt") == 68000


def test_detect_c6_candidate_accepts_corvette_year_range_and_rejects_c7():
    assert detect_c6_candidate("Chevrolet Corvette Z06", "EZ 06/2008 LS7") is True
    assert detect_c6_candidate("Chevrolet Corvette C7 Stingray", "LT1 2015") is False


def test_extract_trim_engine_power_and_registration():
    text = "Corvette C6 Z06 LS7 7.0 V8 512 PS Erstzulassung 05/2008"
    assert extract_trim(text) == "Z06"
    assert extract_engine(text) == "LS7"
    assert extract_power_hp(text) == 512
    assert extract_first_registration(text) == "2008-05"


def test_risk_flags_separate_accident_damage_import_and_no_tuv():
    flags = extract_risk_flags("US Import, reparierter Unfallschaden, Frontschaden, ohne TÜV")
    assert "accident_reported" in flags
    assert "damage_reported" in flags
    assert "salvage_import_possible" in flags
    assert "no_tuv" in flags


def test_extract_probable_engine_from_power_maps_c6_power_ranges():
    assert extract_probable_engine_from_power(404) == ("LS2", 0.86)
    assert extract_probable_engine_from_power(437) == ("LS3", 0.86)
    assert extract_probable_engine_from_power(512) == ("LS7", 0.9)
    assert extract_probable_engine_from_power(647) == ("LS9", 0.92)
    assert extract_probable_engine_from_power(None) is None


def test_normalize_listing_marks_probable_engine_when_engine_missing_but_power_known():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="probable-engine",
        url="https://example.test/c6-404ps",
        title="Chevrolet Corvette C6",
        description="EZ 02/2007, 109.000 km, Benzin 297 kW (404 PS), Privat",
        price_text="28.900 €",
        location_raw="Berlin",
        image_urls=[],
    )

    assert listing is not None
    assert listing.engine is None
    assert listing.probable_engine == "LS2"
    assert listing.engine_confidence == 0.86
    assert "wahrscheinlich LS2" in listing.engine_note


def test_normalize_listing_keeps_explicit_engine_as_certain():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="explicit-engine",
        url="https://example.test/c6-ls3",
        title="Chevrolet Corvette C6 LS3",
        description="437 PS",
        price_text="41.900 €",
        location_raw="München",
        image_urls=[],
    )

    assert listing is not None
    assert listing.engine == "LS3"
    assert listing.probable_engine is None
    assert listing.engine_confidence == 1.0
    assert listing.engine_note == "Motorcode explizit im Inserat erkannt"


def test_normalize_listing_returns_structured_c6_listing_with_score():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="abc123",
        url="https://example.test/c6-z06",
        title="Chevrolet Corvette C6 Z06 LS7",
        description="EZ 05/2008, 72.000 km, 512 PS, unfallfrei, HU 06/2027, Schalter",
        price_text="59.900 €",
        location_raw="München",
        image_urls=["https://example.test/image.jpg"],
    )

    assert listing is not None
    assert listing.generation == "C6"
    assert listing.trim == "Z06"
    assert listing.engine == "LS7"
    assert listing.price_eur == 59900
    assert listing.mileage_km == 72000
    assert listing.accident_status == "unfallfrei"
    assert listing.tuv_until == "2027-06"
    assert listing.transmission == "manual"
    assert listing.image_urls == ["https://example.test/image.jpg"]
    assert listing.score > 0
