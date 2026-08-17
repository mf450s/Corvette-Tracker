from corvette_tracker.models import Listing
from corvette_tracker.storage import filter_listings


def make_listing(
    id="a",
    source="Kleinanzeigen",
    transmission="manual",
    trim="Z06",
    engine="LS7",
    body_style="Coupé",
    price_eur=35000,
    mileage_km=50000,
    change_type="new",
    score=70,
    first_registration="2008-06",
    accident_status="unbekannt",
    tuv_until="2026-05",
    eu_spec=None,
    risk_flags=None,
):
    return Listing(
        id=id,
        source=source,
        source_listing_id=id,
        url=f"https://example.test/{id}",
        title=f"Corvette C6 {trim}",
        generation="C6",
        transmission=transmission,
        trim=trim,
        engine=engine,
        body_style=body_style,
        price_eur=price_eur,
        mileage_km=mileage_km,
        score=score,
        change_type=change_type,
        first_registration=first_registration,
        accident_status=accident_status,
        tuv_until=tuv_until,
        eu_spec=eu_spec,
        risk_flags=risk_flags or [],
    )


LISTINGS = [
    make_listing(
        "a",
        source="Kleinanzeigen",
        transmission="manual",
        trim="Z06",
        engine="LS7",
        body_style="Coupé",
        price_eur=35000,
        mileage_km=50000,
        score=70,
    ),
    make_listing(
        "b",
        source="AutoScout24",
        transmission="automatic",
        trim="Base",
        engine="LS2",
        body_style="Cabrio",
        price_eur=25000,
        mileage_km=100000,
        score=35,
    ),
    make_listing(
        "c",
        source="AutoUncle",
        transmission="manual",
        trim="Grand Sport",
        engine="LS3",
        body_style="Targa",
        price_eur=45000,
        mileage_km=30000,
        score=85,
    ),
    make_listing(
        "d",
        source="Kleinanzeigen",
        transmission="automatic",
        trim="ZR1",
        engine="LS9",
        body_style="Coupé",
        price_eur=95000,
        mileage_km=15000,
        score=95,
    ),
    make_listing(
        "e",
        source="AutoScout24",
        transmission="manual",
        trim="Z06",
        engine="LS7",
        body_style="Coupé",
        price_eur=38000,
        mileage_km=45000,
        score=72,
        change_type="price_change",
    ),
    make_listing(
        "f",
        source="Kleinanzeigen",
        transmission="manual",
        trim="Base",
        engine="LS2",
        body_style="Convertible",
        price_eur=18000,
        mileage_km=120000,
        score=40,
        risk_flags=["damage_reported"],
    ),
    make_listing(
        "g",
        source="AutoUncle",
        transmission="manual",
        trim="Z06",
        engine="LS7",
        body_style="Coupé",
        price_eur=42000,
        mileage_km=60000,
        score=78,
        first_registration="2010-03",
        eu_spec=True,
    ),
    make_listing(
        "h",
        source="Kleinanzeigen",
        transmission="automatic",
        trim="Base",
        engine="LS2",
        body_style="Cabrio",
        price_eur=15000,
        mileage_km=180000,
        score=25,
        change_type="unchanged",
    ),
]


# --- No filter = no change ---


def test_no_filters_returns_all():
    result = filter_listings(LISTINGS, {})
    assert len(result) == 8
    assert result == LISTINGS


def test_empty_filters_returns_all():
    result = filter_listings(LISTINGS, {"": ""})
    assert len(result) == 8


# --- Categorical filters (P0) ---


def test_filter_by_source():
    result = filter_listings(LISTINGS, {"source": "Kleinanzeigen"})
    ids = {l.id for l in result}
    assert ids == {"a", "d", "f", "h"}


def test_filter_by_transmission_manual():
    result = filter_listings(LISTINGS, {"transmission": "manual"})
    assert all(l.transmission == "manual" for l in result)
    assert len(result) == 5  # a, c, e, f, g


def test_filter_by_transmission_automatic():
    result = filter_listings(LISTINGS, {"transmission": "automatic"})
    assert all(l.transmission == "automatic" for l in result)
    assert len(result) == 3  # b, d, h


def test_filter_by_trim():
    result = filter_listings(LISTINGS, {"trim": "Z06"})
    assert all(l.trim == "Z06" for l in result)
    assert len(result) == 3  # a, e, g


def test_filter_by_engine():
    result = filter_listings(LISTINGS, {"engine": "LS7"})
    assert len(result) == 3  # a, e, g
    for l in result:
        assert l.engine == "LS7" or l.probable_engine == "LS7"


def test_filter_by_engine_case_insensitive():
    result = filter_listings(LISTINGS, {"engine": "ls7"})
    assert len(result) == 3


def test_filter_by_body_style():
    result = filter_listings(LISTINGS, {"body_style": "Coupé"})
    assert all(l.body_style == "Coupé" for l in result)
    assert len(result) == 4  # a, d, e, g


def test_filter_by_body_style_cabrio():
    result = filter_listings(LISTINGS, {"body_style": "Cabrio"})
    assert len(result) == 2  # b, h


# --- Numeric range filters (P1) ---


def test_filter_price_min():
    result = filter_listings(LISTINGS, {"price_min": "40000"})
    assert all((l.price_eur or 0) >= 40000 for l in result)
    assert len(result) == 3  # c, d, g


def test_filter_price_max():
    result = filter_listings(LISTINGS, {"price_max": "25000"})
    assert all((l.price_eur or 0) <= 25000 for l in result)
    assert len(result) == 3  # b, f, h


def test_filter_price_range():
    result = filter_listings(LISTINGS, {"price_min": "20000", "price_max": "40000"})
    assert len(result) == 3  # a, e, f


def test_filter_mileage_min():
    result = filter_listings(LISTINGS, {"mileage_min": "100000"})
    assert all((l.mileage_km or 0) >= 100000 for l in result)
    assert len(result) == 3  # b, f, h


def test_filter_mileage_max():
    result = filter_listings(LISTINGS, {"mileage_max": "20000"})
    assert all((l.mileage_km or 0) <= 20000 for l in result)
    assert len(result) == 1  # d


# --- Change type filter ---


def test_filter_change_type():
    result = filter_listings(LISTINGS, {"change_type": "price_change"})
    assert len(result) == 1
    assert result[0].id == "e"


# --- Risk-free toggle ---


def test_filter_risk_free():
    result = filter_listings(LISTINGS, {"risk_free": "true"})
    assert all(len(l.risk_flags) == 0 for l in result)
    assert len(result) == 7  # all except f


def test_filter_risk_free_ignores_listings_with_risk():
    risky_ids = {"f"}
    result = filter_listings(LISTINGS, {"risk_free": "true"})
    assert not any(l.id in risky_ids for l in result)


# --- Score minimum ---


def test_filter_score_min():
    result = filter_listings(LISTINGS, {"score_min": "70"})
    assert all(l.score >= 70 for l in result)
    assert len(result) == 5  # a, c, d, e, g


# --- EZ year range ---


def test_filter_ez_min():
    result = filter_listings(LISTINGS, {"ez_min": "2010"})
    for l in result:
        yr = (l.first_registration or "")[:4]
        assert yr >= "2010"
    assert len(result) == 1  # g


def test_filter_ez_range():
    result = filter_listings(LISTINGS, {"ez_min": "2005", "ez_max": "2008"})
    for l in result:
        yr = (l.first_registration or "")[:4]
        assert "2005" <= yr <= "2008"


# --- Accident status ---


def test_filter_accident_status():
    result = filter_listings(LISTINGS, {"accident_status": "unbekannt"})
    assert all(l.accident_status == "unbekannt" for l in result)
    assert len(result) == 8  # all have "unbekannt"


# --- TÜV minimum year ---


def test_filter_tuv_min():
    # All test listings have tuv_until "2026-05"
    result = filter_listings(LISTINGS, {"tuv_min": "2025"})
    assert len(result) == 8

    result2 = filter_listings(LISTINGS, {"tuv_min": "2027"})
    assert len(result2) == 0


# --- EU spec ---


def test_filter_eu_spec_true():
    result = filter_listings(LISTINGS, {"eu_spec": "true"})
    assert all(l.eu_spec is True for l in result)
    assert len(result) == 1  # g


def test_filter_eu_spec_false():
    result = filter_listings(LISTINGS, {"eu_spec": "false"})
    assert all(l.eu_spec is False for l in result)
    # none have eu_spec=False explicitly, so it should be empty
    assert len(result) == 0


# --- Combined filters ---


def test_combined_source_and_transmission():
    result = filter_listings(LISTINGS, {"source": "Kleinanzeigen", "transmission": "manual"})
    assert len(result) == 2  # a, f
    assert {l.id for l in result} == {"a", "f"}


def test_combined_source_and_price_range():
    result = filter_listings(LISTINGS, {"source": "AutoScout24", "price_min": "30000"})
    assert len(result) == 1  # e
    assert result[0].id == "e"


def test_combined_trim_engine_score():
    result = filter_listings(LISTINGS, {"trim": "Z06", "engine": "LS7", "score_min": "70"})
    assert len(result) == 3  # a, e, g


def test_combined_many_filters():
    result = filter_listings(
        LISTINGS,
        {
            "source": "Kleinanzeigen",
            "transmission": "manual",
            "body_style": "Coupé",
            "price_min": "30000",
            "score_min": "60",
        },
    )
    assert len(result) == 1  # a
    assert result[0].id == "a"


# --- Unknown filter keys are silently ignored ---


def test_unknown_filter_key():
    result = filter_listings(LISTINGS, {"unknown_filter": "value"})
    assert len(result) == 8


def test_invalid_numeric_filter_does_not_crash():
    result = filter_listings(LISTINGS, {"price_min": "not-a-number"})
    assert len(result) == 8  # silently skipped


# --- Edge cases: empty list, None fields ---


def test_empty_listings_returns_empty():
    result = filter_listings([], {"source": "Kleinanzeigen"})
    assert result == []


def test_empty_listings_no_filter():
    result = filter_listings([], {})
    assert result == []


def test_score_min_with_none_score_does_not_crash():
    listings = [
        make_listing("a"),
        Listing(
            id="none_score",
            source="Kleinanzeigen",
            source_listing_id="none_score",
            url="https://example.test/none_score",
            title="No Score",
            score=None,
        ),
    ]
    result = filter_listings(listings, {"score_min": "60"})
    assert len(result) == 1
    assert result[0].id == "a"


def test_score_min_none_score_filtered_out():
    listings = [
        Listing(
            id="none_score",
            source="Kleinanzeigen",
            source_listing_id="none_score",
            url="https://example.test/none_score",
            title="No Score",
            score=None,
        ),
    ]
    result = filter_listings(listings, {"score_min": "0"})
    assert len(result) == 0  # None is not >= 0


def test_ez_min_none_registration_filtered_out():
    listings = [
        Listing(
            id="no_ez",
            source="Kleinanzeigen",
            source_listing_id="no_ez",
            url="https://example.test/no_ez",
            title="No EZ",
            first_registration=None,
        ),
        make_listing("g"),
    ]
    result = filter_listings(listings, {"ez_min": "2000"})
    assert len(result) == 1
    assert result[0].id == "g"


def test_tuv_min_none_tuv_filtered_out():
    listings = [
        Listing(
            id="no_tuv",
            source="Kleinanzeigen",
            source_listing_id="no_tuv",
            url="https://example.test/no_tuv",
            title="No TUV",
            tuv_until=None,
        ),
        make_listing("a"),
    ]
    result = filter_listings(listings, {"tuv_min": "2020"})
    assert len(result) == 1
    assert result[0].id == "a"


# --- Case sensitivity on non-engine fields ---


def test_source_filter_case_sensitive():
    listings = [
        make_listing("a", source="Kleinanzeigen"),
        make_listing("b", source="kleinanzeigen"),
    ]
    result = filter_listings(listings, {"source": "Kleinanzeigen"})
    assert {l.id for l in result} == {"a"}


# --- Combined: score_min with price AND mileage None ---


def test_price_mileage_none_not_crash():
    listings = [
        Listing(
            id="no_pm",
            source="Kleinanzeigen",
            source_listing_id="no_pm",
            url="https://example.test/no_pm",
            title="No Price/Mileage",
            price_eur=None,
            mileage_km=None,
            score=50,
        ),
    ]
    result = filter_listings(listings, {"price_min": "10000", "mileage_max": "50000"})
    assert len(result) == 0  # None excluded


# --- Combined: all available filters simultaneously ---


def test_all_filters_combined():
    result = filter_listings(
        LISTINGS,
        {
            "source": "Kleinanzeigen",
            "transmission": "manual",
            "trim": "Z06",
            "engine": "LS7",
            "body_style": "Coupé",
            "price_min": "30000",
            "price_max": "40000",
            "mileage_min": "40000",
            "mileage_max": "60000",
            "change_type": "new",
            "risk_free": "true",
            "score_min": "60",
            "ez_min": "2005",
            "ez_max": "2010",
            "accident_status": "unbekannt",
            "tuv_min": "2020",
        },
    )
    assert len(result) == 1
    assert result[0].id == "a"
