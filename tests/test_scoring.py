from corvette_tracker.models import Listing
from corvette_tracker.scoring import DEFAULT_SCORING_CONFIG, apply_score, score_listing


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


def test_default_scoring_prefers_manual_non_cabrio_engine_above_ls2_and_nice_trim():
    """Verify the scoring gradient: manual > auto, non-Cabrio > Cabrio,
    higher-tier engine > lower, preferred trim > Base."""
    preferred = listing(
        transmission="manual", body_style="Targa", engine="LS3",
        trim="Grand Sport", mileage_km=70000, price_eur=55000,
    )
    automatic = listing(
        id="auto", transmission="automatic", body_style="Targa",
        engine="LS3", trim="Grand Sport", mileage_km=70000, price_eur=55000,
    )
    cabrio = listing(
        id="cabrio", transmission="manual", body_style="Cabrio",
        engine="LS3", trim="Grand Sport", mileage_km=70000, price_eur=55000,
    )
    ls2 = listing(
        id="ls2", transmission="manual", body_style="Targa",
        engine="LS2", trim="Grand Sport", mileage_km=70000, price_eur=55000,
    )
    ls9 = listing(
        id="ls9", transmission="manual", body_style="Targa",
        engine="LS9", trim="ZR1", mileage_km=70000, price_eur=55000,
    )
    base_trim = listing(
        id="base", transmission="manual", body_style="Targa",
        engine="LS3", trim="Base", mileage_km=70000, price_eur=55000,
    )

    s_preferred = score_listing(preferred)
    s_auto = score_listing(automatic)
    s_cabrio = score_listing(cabrio)
    s_ls2 = score_listing(ls2)
    s_ls9 = score_listing(ls9)
    s_base = score_listing(base_trim)

    # Manual must score higher than automatic
    assert s_preferred > s_auto, f"manual({s_preferred}) should beat auto({s_auto})"
    # Non-Cabrio must score higher than Cabrio
    assert s_preferred > s_cabrio, f"non-cabrio({s_preferred}) should beat cabrio({s_cabrio})"
    # LS3+ should beat LS2
    assert s_preferred > s_ls2, f"LS3({s_preferred}) should beat LS2({s_ls2})"
    # LS9 should be top
    assert s_ls9 > s_preferred, f"LS9/ZR1({s_ls9}) should beat LS3/GS({s_preferred})"
    # Preferred trim should beat Base
    assert s_preferred > s_base, f"GS({s_preferred}) should beat Base({s_base})"
    # Risk-flagged car should score lower than equivalent clean car
    risk = listing(
        id="risk", transmission="manual", body_style="Targa",
        engine="LS3", trim="Grand Sport", mileage_km=70000,
        price_eur=55000, risk_flags=["accident_reported"],
    )
    assert score_listing(risk) < s_preferred


def test_scoring_weights_are_configurable():
    """Override all scoring dimensions and verify exact numbers."""
    config = {
        "base_score": 10,
        "weights": {
            "manual_transmission": 5,
            "automatic_transmission": 2,
            "non_convertible": 4,
        },
        "engine_scores": {"LS2": 0, "LS3": 3},
        "trim_scores": {"Base": 0, "Z06": 2},
        "mileage_bonus": [],
        "completeness": {
            "has_engine": 1,
            "has_mileage": 1,
            "has_price": 1,
            "has_images": 0,
        },
        "eu_spec_bonus": 0,
        "no_engine_penalty": 2,
        "risk_penalties": {},
        "preferred_trims": [],
    }

    # manual, Targa, LS3, Z06: 10 + 3(LS3) + 2(Z06) + 5(manual) + 4(non-cabrio) + 3(completeness)
    expected_preferred = 10 + 3 + 2 + 5 + 4 + 3  # = 27
    assert score_listing(
        listing(transmission="manual", body_style="Targa", engine="LS3", trim="Z06"),
        config,
    ) == expected_preferred

    # automatic, Cabrio, LS2, Base: 10 + 0(LS2) + 0(Base) + 2(automatic) + 0(Cabrio) + 3(completeness)
    expected_basic = 10 + 0 + 0 + 2 + 0 + 3  # = 15
    assert score_listing(
        listing(transmission="automatic", body_style="Cabrio", engine="LS2", trim="Base"),
        config,
    ) == expected_basic

    # Missing engine info invokes penalty
    no_engine = config.copy()
    no_engine["engine_scores"] = {}
    no_engine["no_engine_penalty"] = 10
    assert score_listing(
        listing(transmission="automatic", body_style="Cabrio", engine=None, trim="Base"),
        no_engine,
    ) == 10 + 0 + 0 + 2 + 0 + 0 + 1 + 1 - 10  # base + auto + completeness(mileage+price) - penalty


def test_apply_score_updates_listing_score_in_place():
    item = listing(
        score=0, transmission="manual", body_style="Targa",
        engine="LS3", trim="Grand Sport", mileage_km=70000, price_eur=55000,
    )

    result = apply_score(item)

    assert result is item
    expected = (
        30                      # base
        + 10                    # LS3
        + 5                     # Grand Sport
        + 15                    # manual
        + 10                    # non-Cabrio
        + 5                     # mileage < 80k
        + 3 + 2 + 2             # completeness
    )
    assert item.score == expected
