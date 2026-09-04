import json

from corvette_tracker.enums import BodyStyleType, TransmissionType, TrimType
from corvette_tracker.models import Listing
from corvette_tracker.normalize import (
    detect_c6_candidate,
    extract_body_style,
    extract_c6_options,
    extract_condition,
    extract_displacement_cc,
    extract_engine,
    extract_first_registration,
    extract_mileage_km,
    extract_model_year,
    extract_owners_count,
    extract_power_hp,
    extract_power_kw,
    extract_price_eur,
    extract_price_label,
    extract_probable_engine_from_power,
    extract_risk_flags,
    extract_service_history,
    extract_trim,
    normalize_listing,
)


def test_extract_price_eur_handles_german_format():
    assert extract_price_eur("Chevrolet Corvette C6 - 54.900 € VB") == 54900


def test_extract_price_eur_avoids_partial_date_match():
    assert extract_price_eur("Erstzulassung 08.2010") is None
    assert extract_price_eur("EZ 12/2008") is None
    assert extract_price_eur("Bj.2005") is None


def test_extract_price_eur_prefers_explicit_currency_over_earlier_bare_number():
    # "123.000" (mileage) appears before "35.000 €" (price) — should return 35000
    text = "Km-Stand 123.000, TÜV 09.2027, 35.000 € VB 123.000 km EZ 08/2010"
    assert extract_price_eur(text) == 35000


def test_extract_price_eur_skips_bare_number_next_to_km():
    # "5000 km" is mileage context, not a price
    assert extract_price_eur("ca 5000 km gefahren in der Zeit") is None
    assert extract_price_eur("Verkaufe, 5000 km gelaufen, VB") is None
    # But a €-marked price in the same text still works
    assert extract_price_eur("ca 5000 km gefahren, 35000 € VB") == 35000


def test_extract_price_eur_skips_bare_number_with_km_before():
    # "Km-Stand 123.000" — km context before the number
    assert extract_price_eur("Km-Stand 123.000") is None
    assert extract_price_eur("km 123000") is None


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


def test_extract_mileage_km_avoids_year_like_numbers():
    assert extract_mileage_km("2011 km") is None
    assert extract_mileage_km("EZ 09.2008 km") is None
    # But real mileage values (5+ digits) still work
    assert extract_mileage_km("10000 km") == 10000


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
    assert extract_body_style(text) == "Coupé"
    assert extract_first_registration(text) == "2008-05"


def test_extract_trim_handles_zo6_letter_o():
    assert extract_trim("Chevrolet Corvette C6 ZO6") == "Z06"
    assert extract_trim("C6 ZO6 KW V3 NPP") == "Z06"


def test_extract_trim_handles_zr1_with_space():
    assert extract_trim("Corvette C6 ZR 1") == "ZR1"
    assert extract_trim("C6 ZR1 LS9 Kompressor") == "ZR1"


def test_extract_trim_handles_grand_sport_hyphen():
    assert extract_trim("Corvette C6 Grand-Sport 6.2 V8") == "Grand Sport"
    assert extract_trim("Corvette C6 Grand Sport LS3") == "Grand Sport"


def test_extract_body_style_detects_c6_body_variants():
    assert extract_body_style("Corvette C6 Cabrio Convertible") == "Cabrio"
    assert extract_body_style("Corvette C6 Coupe Targa removable roof") == "Targa"
    assert extract_body_style("Corvette C6 Coupé") == "Coupé"


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
    assert listing.body_style == "Coupé"
    assert "LS7 → Z06" in listing.inference_notes
    assert "Z06 → Schalter" in listing.inference_notes
    assert "Z06 → Coupé" in listing.inference_notes


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
    assert listing.body_style == "Coupé"
    assert "conflict_z06_transmission_automatic" in listing.conflict_flags
    assert "conflict_z06_body_cabrio" in listing.conflict_flags


def test_normalize_listing_infers_zr1_as_coupe_not_targa():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="zr1-coupe",
        url="https://example.test/c6-zr1",
        title="Chevrolet Corvette C6 ZR1 LS9",
        description="Kompressor, 647 PS",
        price_text="109.900 €",
        location_raw="Hamburg",
        image_urls=[],
    )

    assert listing is not None
    assert listing.trim == "ZR1"
    assert listing.transmission == "manual"
    assert listing.body_style == "Coupé"
    assert "ZR1 → Coupé" in listing.inference_notes


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


def test_price_decimal_separator_does_not_infer_ls7_engine():
    listing = normalize_listing(
        source="AutoScout24",
        source_listing_id="base-coupe",
        url="https://example.test/base-coupe",
        title="Corvette C6 Coupe Automatik",
        description="C6 Coupe Automatik 404 PS Automatik 5.967 cm³ 5967",
        price_text="€ 47.000",
        location_raw="Bierum",
        image_urls=[],
    )

    assert listing is not None
    assert listing.engine is None
    assert listing.probable_engine == "LS2"
    assert listing.transmission == "automatic"
    assert listing.trim == "Base"


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
    assert listing.body_style == "Coupé"
    assert listing.power_hp == 512
    assert listing.image_urls == ["https://example.test/image.jpg"]
    assert listing.score > 0


def test_extract_trim_returns_trim_type():
    assert extract_trim("Chevrolet Corvette C6 Z06") == TrimType.Z06
    assert extract_trim("Chevrolet Corvette C6 Grand Sport LS3") == TrimType.GRAND_SPORT
    assert extract_trim("Chevrolet Corvette C6") == TrimType.BASE
    assert extract_trim("Chevrolet Corvette C6 ZR1 ZR 1") == TrimType.ZR1


def test_listing_trim_enum_roundtrip_via_json():
    listing = Listing(
        id="roundtrip",
        source="test",
        source_listing_id=None,
        url="https://example.test/c6",
        title="Test",
        trim=TrimType.Z06,
    )
    payload = json.loads(json.dumps(listing.to_dict()))
    assert payload["trim"] == "Z06"
    restored = Listing(**payload)
    assert restored.trim == TrimType.Z06


def test_extract_model_year():
    assert extract_model_year("MJ 2008") == 2008
    assert extract_model_year("Modelljahr 2010") == 2010
    assert extract_model_year("Baujahr 2005") == 2005
    assert extract_model_year("Kein Baujahr hier") is None


def test_extract_power_kw():
    assert extract_power_kw("377 kW") == 377
    assert extract_power_kw("512 PS") is None
    assert extract_power_kw("80 kW") is None


def test_extract_displacement_cc():
    assert extract_displacement_cc("7.0L") == 7008
    assert extract_displacement_cc("6.2 L") == 6162
    assert extract_displacement_cc("6.0L") == 5967
    assert extract_displacement_cc("Hubraum: 5967 cm³") == 5967
    assert extract_displacement_cc("V8") is None


def test_extract_owners_count():
    assert extract_owners_count("Anzahl Vorbesitzer: 2") == 2
    assert extract_owners_count("Anzahl der Fahrzeughalter: 3") == 3
    assert extract_owners_count("3. Hand") == 3
    assert extract_owners_count("1 Hand") == 1
    assert extract_owners_count("keine Angabe") is None


def test_extract_condition():
    assert extract_condition("Fahrzeugzustand: Sehr gut") == "Sehr gut"
    assert extract_condition("Zustand: Gebraucht") == "Gebraucht"
    assert extract_condition("Unfallfrei") is None


def test_extract_service_history():
    assert extract_service_history("Scheckheft gepflegt") is True
    assert extract_service_history("ohne Scheckheft") is False
    assert extract_service_history("kein Scheckheft") is False


def test_extract_c6_options():
    text = "Magnetic Ride, Klappenauspuff NPP, Head-Up-Display, Bose, Ledersitze, Sitzheizung"
    options = extract_c6_options(text)
    assert options["magnetic_ride"] is True
    assert options["active_exhaust"] is True
    assert options["head_up_display"] is True
    assert options["bose_audio"] is True
    assert options["leather_interior"] is True
    assert options["heated_seats"] is True
    assert "bose_audio" not in extract_c6_options("BOSCH")


def test_normalize_listing_c6_fields():
    listing = normalize_listing(
        source="fixture",
        source_listing_id="c6-fields",
        url="https://example.test/c6-fields",
        title="Corvette C6 Z06 MJ 2008",
        description=(
            "Fahrzeugzustand: Sehr gut, Anzahl Vorbesitzer: 2, Scheckheft gepflegt, "
            "Garantie, Magnetic Ride, Klappenauspuff NPP, Head-Up-Display, Bose, "
            "Ledersitze, Sitzheizung, 377 kW, 7.0 L, Heckantrieb"
        ),
        price_text="59.900 €",
        location_raw="Hamburg",
        image_urls=[],
    )
    assert listing is not None
    assert listing.model_year == 2008
    assert listing.power_kw == 377
    assert listing.displacement_cc == 7008
    assert listing.drivetrain == "Heckantrieb"
    assert listing.condition == "Sehr gut"
    assert listing.owners_count == 2
    assert listing.service_history is True
    assert listing.warranty is True
    assert listing.magnetic_ride is True
    assert listing.active_exhaust is True
    assert listing.head_up_display is True
    assert listing.bose_audio is True
    assert listing.leather_interior is True
    assert listing.heated_seats is True


def test_normalize_transmission_body_enum():
    listing_auto = normalize_listing(
        source="fixture",
        source_listing_id="auto-enum",
        url="https://example.test/auto-enum",
        title="Chevrolet Corvette C6",
        description="Automatik",
        price_text="25.000 €",
        location_raw="Hamburg",
        image_urls=[],
    )
    assert listing_auto is not None
    assert listing_auto.transmission == TransmissionType.AUTOMATIC

    listing_cab = normalize_listing(
        source="fixture",
        source_listing_id="cab-enum",
        url="https://example.test/cab-enum",
        title="Chevrolet Corvette C6",
        description="Cabrio",
        price_text="30.000 €",
        location_raw="Hamburg",
        image_urls=[],
    )
    assert listing_cab is not None
    assert listing_cab.body_style == BodyStyleType.CABRIO
