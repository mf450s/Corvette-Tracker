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
    extract_body_style,
    extract_price_label,
    normalize_listing,
)


def test_extract_price_eur_handles_german_format():
    assert extract_price_eur("Chevrolet Corvette C6 - 54.900 € VB") == 54900


def test_extract_price_label_detects_vb_without_numeric_price():
    assert extract_price_label("VB") == "VB"
    assert extract_price_label("Preis VB") == "VB"
    assert extract_price_label("Verhandlungsbasis") == "VB"
    assert extract_price_label("Zu verschenken") == "zu verschenken"


def test_normalize_listing_keeps_vb_price_label_without_fake_price():
    listing = normalize_listing(
        source="Kleinanzeigen",
        source_listing_id="vb-1",
        url="https://example.test/corvette-c6-vb",
        title="Chevrolet Corvette C6 LS3",
        description="68.000 km EZ 05/2011 437 PS",
        price_text="VB",
        location_raw="Hamburg",
        image_urls=[],
    )

    assert listing is not None
    assert listing.price_eur is None
    assert listing.price_label == "VB"


def test_extract_mileage_km_handles_dots_and_units():
    assert extract_mileage_km("68.000 km, gepflegt") == 68000


def test_detect_c6_candidate_accepts_corvette_year_range_and_rejects_c7():
    assert detect_c6_candidate("Chevrolet Corvette Z06", "EZ 06/2008 LS7") is True
    assert detect_c6_candidate("Chevrolet Corvette C7 Stingray", "LT1 2015") is False


def test_normalize_listing_rejects_search_requests_by_title():
    listing = normalize_listing(
        source="Kleinanzeigen",
        source_listing_id="search-request",
        url="https://example.test/suche-corvette-c6",
        title="Suche Corvette C6 Z06 LS7",
        description="Budget vorhanden, bitte alles anbieten",
        price_text="VB",
        location_raw="Hamburg",
        image_urls=[],
    )

    assert listing is None


def test_detect_c6_candidate_rejects_c7_z06_without_c6_evidence():
    assert detect_c6_candidate("Corvette Z06 Coupe 3LZ 5.5 V8", "08/2025 Benzin 646 PS") is False
    assert detect_c6_candidate("Corvette Z06 Coupe 3LZ Werksgarantie", "2025 LT4 659 PS") is False
    assert detect_c6_candidate("Corvette C 7 Z06", "2016 LT4") is False
    assert detect_c6_candidate("Corvette Z06 deutsches Modell", "EZ 06/2008 LS7 512 PS") is True
    assert detect_c6_candidate("Corvette C 6 Competition", "EZ 2010") is True


def test_extract_trim_engine_power_body_style_and_registration():
    text = "Corvette C6 Z06 LS7 7.0 V8 512 PS Coupé Erstzulassung 05/2008"
    assert extract_trim(text) == "Z06"
    assert extract_engine(text) == "LS7"
    assert extract_power_hp(text) == 512
    assert extract_body_style(text) == "Targa"
    assert extract_first_registration(text) == "2008-05"


def test_extract_body_style_detects_c6_body_variants():
    assert extract_body_style("Corvette C6 Cabrio Convertible") == "Cabrio"
    assert extract_body_style("Corvette C6 Coupe Targa removable roof") == "Targa"
    assert extract_body_style("Corvette C6 Coupé") == "Targa"


def test_normalize_listing_applies_c6_inferences_from_engine_and_trim():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="ls7-inference",
        url="https://example.test/c6-ls7",
        title="Chevrolet Corvette C6 LS7",
        description="7.0 V8, gepflegt",
        price_text="59.900 €",
        location_raw="München",
        image_urls=[],
    )

    assert listing is not None
    assert listing.engine == "LS7"
    assert listing.trim == "Z06"
    assert listing.transmission == "manual"
    assert listing.body_style == "Targa"
    assert "LS7 → Z06" in listing.inference_notes
    assert "Z06 → Schalter" in listing.inference_notes
    assert "Z06 → Targa" in listing.inference_notes


def test_normalize_listing_converts_coupe_to_targa_assumption():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="coupe-to-targa",
        url="https://example.test/c6-coupe",
        title="Chevrolet Corvette C6 Coupé 6.0 V8",
        description="Automatik, gepflegt",
        price_text="29.900 €",
        location_raw="Erftstadt",
        image_urls=[],
    )

    assert listing is not None
    assert listing.body_style == "Targa"
    assert "Coupé/Coupe → Targa" in listing.inference_notes


def test_normalize_listing_flags_conflicts_against_c6_assumptions():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="conflict-z06",
        url="https://example.test/c6-z06-auto-cabrio",
        title="Chevrolet Corvette C6 Z06 LS7 Cabrio Automatik",
        description="7.0 V8",
        price_text="59.900 €",
        location_raw="Berlin",
        image_urls=[],
    )

    assert listing is not None
    assert listing.trim == "Z06"
    assert listing.transmission == "manual"
    assert listing.body_style == "Targa"
    assert "conflict_z06_transmission_automatic" in listing.conflict_flags
    assert "conflict_z06_body_cabrio" in listing.conflict_flags


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
        description="sehr gepflegt, keine PS-Angabe im Inserat",
        price_text="41.900 €",
        location_raw="München",
        image_urls=[],
    )

    assert listing is not None
    assert listing.engine == "LS3"
    assert listing.probable_engine is None
    assert listing.engine_confidence == 1.0
    assert listing.engine_note == "Motorcode explizit im Inserat erkannt"
    assert listing.power_hp is None
    assert listing.estimated_power_hp == 437
    assert "LS3" in listing.power_note


def test_normalize_listing_estimates_power_from_probable_engine_when_ps_missing():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="probable-no-ps",
        url="https://example.test/c6-ls2",
        title="Chevrolet Corvette C6 6.0 V8 Coupé",
        description="Automatik, gepflegt, keine Leistungsangabe",
        price_text="29.900 €",
        location_raw="Erftstadt",
        image_urls=[],
    )

    assert listing is not None
    assert listing.engine == "LS2"
    assert listing.power_hp is None
    assert listing.estimated_power_hp == 404
    assert "geschätzt" in listing.power_note


def test_extract_trim_does_not_turn_base_coupe_into_z06_from_unrelated_text():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="base-coupe",
        url="https://example.test/c6-coupe",
        title="Corvette C6 Coupé 6.0 V8 – 404 PS – Automatik",
        description="Zum Verkauf steht eine gepflegte Chevrolet Corvette C6. Ähnliche Anzeige: Corvette C6 Z06.",
        price_text="29.900 €",
        location_raw="Erftstadt",
        image_urls=[],
    )

    assert listing is not None
    assert listing.trim == "Base"
    assert listing.body_style == "Targa"
    assert listing.model == "Chevrolet Corvette C6 Targa"


def test_normalize_listing_returns_structured_c6_listing_with_score():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="abc123",
        url="https://example.test/c6-z06",
        title="Chevrolet Corvette C6 Z06 LS7",
        description="EZ 05/2008, 72.000 km, 512 PS, Coupé, unfallfrei, HU 06/2027, Schalter",
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
    assert listing.body_style == "Targa"
    assert listing.power_hp == 512
    assert listing.image_urls == ["https://example.test/image.jpg"]
    assert listing.score > 0
