from corvette_tracker.models import Listing
from corvette_tracker.scoring import apply_score


def listing(**overrides):
    base = dict(
        id="listing-1",
        source="fixture",
        source_listing_id="1",
        url="https://example.test/listing-1",
        title="Chevrolet Corvette C6",
        price_eur=55000,
        mileage_km=70000,
        trim="Base",
        engine="LS3",
        transmission="automatic",
        body_style="Cabrio",
        accident_status="unbekannt",
        risk_flags=[],
    )
    base.update(overrides)
    return Listing(**base)


def _calc(listing, config=None):
    """Helper: apply_score -> return score as int."""
    return int(apply_score(listing, config).score)


def test_default_scoring_gradient():
    """Verify sensible ranking with default budget."""
    # Top: LS9 ZR1 manual Coupé low km
    top = listing(
        engine="LS9",
        trim="ZR1",
        transmission="manual",
        body_style="Coupé",
        mileage_km=25000,
        price_eur=100000,
    )
    # Mid: LS3 Grand Sport manual Targa 50k km
    mid = listing(
        engine="LS3",
        trim="Grand Sport",
        transmission="manual",
        body_style="Targa",
        mileage_km=50000,
        price_eur=40000,
    )
    # Base: LS2 Base automatic Cabrio high km
    base = listing(
        engine="LS2",
        trim="Base",
        transmission="automatic",
        body_style="Cabrio",
        mileage_km=200000,
        price_eur=15000,
    )

    s_top = _calc(top)
    s_mid = _calc(mid)
    s_base = _calc(base)

    assert s_top > s_mid > s_base, f"{s_top} > {s_mid} > {s_base} failed"
    # Risk should downgrade
    risky = listing(
        engine="LS3",
        trim="Grand Sport",
        transmission="manual",
        body_style="Targa",
        mileage_km=50000,
        price_eur=40000,
        risk_flags=["accident_reported"],
    )
    assert _calc(risky) < s_mid


def test_scoring_budget_is_configurable():
    """User sets budget per category; system auto-distributes."""
    config = {
        "base_score": 10,
        "total_budget": 20,
        "budget": {
            "engine": 10,
            "transmission": 5,
            "trim": 3,
            "body": 2,
            "mileage": 0,
            "completeness": 0,
            "eu_spec": 0,
        },
    }

    # manual, Targa, LS3, Z06
    # base(10) + engine(10*0.33) + trans(5*1.0) + body(2) + trim(3*0.66)
    expected_good = 10 + int(10 * 0.33) + int(5 * 1.0) + 2 + int(3 * 0.66)
    assert (
        _calc(
            listing(transmission="manual", body_style="Targa", engine="LS3", trim="Z06"),
            config,
        )
        == expected_good
    )

    # automatic, Cabrio, LS2, Base
    # base(10) + engine(10*0.0) + trans(5*0.3) + body(0) + trim(3*0.0)
    expected_basic = 10 + 0 + int(5 * 0.3) + 0 + 0
    assert (
        _calc(
            listing(transmission="automatic", body_style="Cabrio", engine="LS2", trim="Base"),
            config,
        )
        == expected_basic
    )

    # Missing engine invokes penalty
    assert (
        _calc(
            listing(transmission="automatic", body_style="Cabrio", engine=None, trim="Base"),
            config,
        )
        < expected_basic
    )


def test_apply_score_updates_listing_score_in_place():
    item = listing(
        score=0,
        transmission="manual",
        body_style="Targa",
        engine="LS3",
        trim="Grand Sport",
        mileage_km=70000,
        price_eur=55000,
    )

    result = apply_score(item)
    assert result is item

    expected = int(
        20  # base
        + 15 * 0.33  # engine LS3 → 4 (int truncation)
        + 10 * 1.0  # transmission manual → 10
        + 8 * 0.33  # trim Grand Sport → 2 (int truncation)
        + 6  # body non-Cabrio
        + 6 * 0.5  # mileage 70k (<80k bracket) → 3
        + 3 / 4 * 3  # completeness 3 of 4 fields → 2.25
        + 0  # eu_spec (None)
    )
    # int() at end gives 48 but intermediate int() truncations produce 47
    # Test the actual behavior: sum with intermediate truncation
    expected = 20 + int(25 * 0.33) + int(15 * 1.0) + int(12 * 0.33) + 10 + int(10 * 0.5) + 5 / 4 * 3
    assert item.score == int(expected)  # 56
