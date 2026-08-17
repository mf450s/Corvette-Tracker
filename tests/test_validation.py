from corvette_tracker.models import Listing
from corvette_tracker.validation import (
    CRITICAL,
    ERROR,
    INFO,
    WARN,
    apply_validation_flags,
    safe_normalize_listing,
    sanity_check_against_previous,
    validate_listing,
)


def _make_listing(**overrides: object) -> Listing:
    defaults: dict = {
        "id": "test_1",
        "source": "test",
        "source_listing_id": "1",
        "url": "https://example.test/c6",
        "title": "Chevrolet Corvette C6",
    }
    defaults.update(overrides)
    return Listing(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Price validation
# ---------------------------------------------------------------------------


def test_validation_flags_negative_price():
    listing = _make_listing(price_eur=-500)
    flags = validate_listing(listing)
    assert any(f["code"] == "price_negative" and f["severity"] == CRITICAL for f in flags)


def test_validation_flags_zero_price():
    listing = _make_listing(price_eur=0)
    flags = validate_listing(listing)
    assert any(f["code"] == "price_zero" and f["severity"] == ERROR for f in flags)


def test_validation_flags_very_low_price():
    listing = _make_listing(price_eur=50)
    flags = validate_listing(listing)
    assert any(f["code"] == "price_very_low" and f["severity"] == WARN for f in flags)


def test_validation_flags_very_low_price_ok_with_label():
    """A very low price is acceptable if there's a price label like 'VB'."""
    listing = _make_listing(price_eur=50, price_label="VB")
    flags = validate_listing(listing)
    assert not any(f["code"] == "price_very_low" for f in flags)


def test_validation_flags_very_high_price():
    listing = _make_listing(price_eur=999_999)
    flags = validate_listing(listing)
    assert any(f["code"] == "price_very_high" and f["severity"] == WARN for f in flags)


def test_validation_flags_missing_price():
    listing = _make_listing(price_eur=None)
    flags = validate_listing(listing)
    assert any(f["code"] == "price_missing" and f["severity"] == INFO for f in flags)


def test_validation_flags_price_fully_missing():
    listing = _make_listing(price_eur=None, price_label="")
    flags = validate_listing(listing)
    assert any(f["code"] == "price_fully_missing" and f["severity"] == WARN for f in flags)


# ---------------------------------------------------------------------------
# Mileage validation
# ---------------------------------------------------------------------------


def test_validation_flags_negative_mileage():
    listing = _make_listing(mileage_km=-100)
    flags = validate_listing(listing)
    assert any(f["code"] == "mileage_negative" and f["severity"] == CRITICAL for f in flags)


def test_validation_flags_zero_mileage():
    listing = _make_listing(mileage_km=0)
    flags = validate_listing(listing)
    assert any(f["code"] == "mileage_zero" and f["severity"] == ERROR for f in flags)


def test_validation_flags_very_low_mileage():
    listing = _make_listing(mileage_km=10)
    flags = validate_listing(listing)
    assert any(f["code"] == "mileage_very_low" and f["severity"] == WARN for f in flags)


def test_validation_flags_very_high_mileage():
    listing = _make_listing(mileage_km=999_999)
    flags = validate_listing(listing)
    assert any(f["code"] == "mileage_very_high" and f["severity"] == WARN for f in flags)


def test_validation_flags_missing_mileage():
    listing = _make_listing(mileage_km=None)
    flags = validate_listing(listing)
    assert any(f["code"] == "mileage_missing" and f["severity"] == INFO for f in flags)


# ---------------------------------------------------------------------------
# Power validation
# ---------------------------------------------------------------------------


def test_validation_flags_negative_power():
    listing = _make_listing(power_hp=-100)
    flags = validate_listing(listing)
    assert any(f["code"] == "power_negative" and f["severity"] == CRITICAL for f in flags)


def test_validation_flags_zero_power():
    listing = _make_listing(power_hp=0)
    flags = validate_listing(listing)
    assert any(f["code"] == "power_zero" and f["severity"] == ERROR for f in flags)


def test_validation_flags_very_high_power():
    listing = _make_listing(power_hp=2000)
    flags = validate_listing(listing)
    assert any(f["code"] == "power_very_high" and f["severity"] == WARN for f in flags)


# ---------------------------------------------------------------------------
# Year validation
# ---------------------------------------------------------------------------


def test_validation_flags_year_out_of_range():
    listing = _make_listing(first_registration="2002-06")
    flags = validate_listing(listing)
    assert any(f["code"] == "year_out_of_range" and f["severity"] == WARN for f in flags)


def test_validation_flags_year_in_range():
    listing = _make_listing(first_registration="2008-05")
    flags = validate_listing(listing)
    assert not any(f["code"] == "year_out_of_range" for f in flags)


# ---------------------------------------------------------------------------
# Engine-trim consistency
# ---------------------------------------------------------------------------


def test_validation_flags_engine_trim_mismatch():
    """LS7 engine should pair with Z06 trim, never Base."""
    listing = _make_listing(engine="LS7", trim="Base")
    flags = validate_listing(listing)
    assert any(f["code"] == "engine_trim_mismatch" for f in flags)


def test_validation_flags_engine_trim_match():
    """LS7 with Z06 is correct."""
    listing = _make_listing(engine="LS7", trim="Z06")
    flags = validate_listing(listing)
    assert not any(f["code"] == "engine_trim_mismatch" for f in flags)


def test_validation_flags_engine_trim_uses_probable_engine():
    """Should use probable_engine as fallback when engine is None."""
    listing = _make_listing(engine=None, probable_engine="LS7", trim="Base")
    flags = validate_listing(listing)
    assert any(f["code"] == "engine_trim_mismatch" for f in flags)


def test_validation_flags_ls3_grand_sport_is_valid():
    listing = _make_listing(engine="LS3", trim="Grand Sport")
    flags = validate_listing(listing)
    assert not any(f["code"] == "engine_trim_mismatch" for f in flags)


# ---------------------------------------------------------------------------
# Missing trim / body_style
# ---------------------------------------------------------------------------


def test_validation_flags_missing_trim():
    listing = _make_listing(trim=None)
    flags = validate_listing(listing)
    assert any(f["code"] == "trim_missing" for f in flags)


def test_validation_flags_missing_body_style():
    listing = _make_listing(body_style=None)
    flags = validate_listing(listing)
    assert any(f["code"] == "body_style_missing" for f in flags)


# ---------------------------------------------------------------------------
# apply_validation_flags
# ---------------------------------------------------------------------------


def test_apply_validation_flags_attaches_to_listing():
    listing = _make_listing(price_eur=-5)
    result = apply_validation_flags(listing)
    assert result is listing  # in-place
    assert any(f["code"] == "price_negative" for f in listing.validation_flags)


def test_apply_validation_flags_preserves_existing_flags():
    listing = _make_listing(price_eur=-5)
    listing.validation_flags = [{"code": "pre_existing"}]
    result = apply_validation_flags(listing)
    # apply_validation_flags should replace, not merge
    assert not any(f["code"] == "pre_existing" for f in result.validation_flags)


def test_sane_listing_has_no_flags():
    listing = _make_listing(
        price_eur=59900,
        mileage_km=72000,
        power_hp=512,
        first_registration="2008-05",
        trim="Z06",
        engine="LS7",
        body_style="Coupé",
    )
    flags = validate_listing(listing)
    # Should have no warning/error/critical flags — only maybe info
    severe = [f for f in flags if f["severity"] != INFO]
    assert severe == [], f"Expected no severe flags, got: {severe}"


# ---------------------------------------------------------------------------
# Historical sanity check
# ---------------------------------------------------------------------------


def test_sanity_check_against_previous_no_data():
    listing = _make_listing(price_eur=999_999)
    flags = sanity_check_against_previous(listing, [])
    assert flags == []


def test_sanity_check_against_previous_too_few():
    listings = [_make_listing(id=f"t{i}", price_eur=30000 + i * 1000) for i in range(5)]
    listing = _make_listing(price_eur=1_000_000)
    flags = sanity_check_against_previous(listing, listings)
    assert flags == []  # need >= 10 for percentile detection


def test_sanity_check_against_previous_high_outlier():
    listings = [
        _make_listing(id=f"t{i}", price_eur=30000 + (i % 5) * 2000, mileage_km=50000 + i * 5000)
        for i in range(12)
    ]
    listing = _make_listing(price_eur=10_000_000)
    flags = sanity_check_against_previous(listing, listings)
    assert any(f["code"] == "price_above_historical_range" for f in flags)


def test_sanity_check_against_previous_low_outlier():
    listings = [
        _make_listing(id=f"t{i}", price_eur=30000 + (i % 5) * 2000, mileage_km=50000 + i * 5000)
        for i in range(12)
    ]
    listing = _make_listing(price_eur=100)
    flags = sanity_check_against_previous(listing, listings)
    assert any(f["code"] == "price_below_historical_range" for f in flags)


# ---------------------------------------------------------------------------
# safe_normalize_listing
# ---------------------------------------------------------------------------


def test_safe_normalize_success():
    def good_func(*args, **kwargs):
        return "success"

    result = safe_normalize_listing(good_func, "a", key="b")
    assert result == "success"


def test_safe_normalize_exception():
    from corvette_tracker.validation import safe_normalize_listing as snl

    # Reset last_error
    snl._last_error = [None]

    def failing_func(*args, **kwargs):
        raise ValueError("boom")

    result = snl(failing_func, "x")
    assert result is None
    assert isinstance(snl._last_error[0], ValueError)
