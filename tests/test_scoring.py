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


def test_default_scoring_prefers_manual_non_cabrio_non_ls2_and_trim_medium():
    preferred = listing(transmission="manual", body_style="Targa", engine="LS3", trim="Grand Sport")
    automatic = listing(id="automatic", transmission="automatic", body_style="Targa", engine="LS3", trim="Grand Sport")
    cabrio = listing(id="cabrio", transmission="manual", body_style="Cabrio", engine="LS3", trim="Grand Sport")
    ls2 = listing(id="ls2", transmission="manual", body_style="Targa", engine="LS2", trim="Grand Sport")
    base_trim = listing(id="base", transmission="manual", body_style="Targa", engine="LS3", trim="Base")

    preferred_score = score_listing(preferred)

    assert preferred_score == 100
    assert preferred_score - score_listing(automatic) == DEFAULT_SCORING_CONFIG["weights"]["manual_transmission"]
    assert preferred_score - score_listing(cabrio) == DEFAULT_SCORING_CONFIG["weights"]["non_convertible"]
    assert preferred_score - score_listing(ls2) == DEFAULT_SCORING_CONFIG["weights"]["non_ls2"]
    assert preferred_score - score_listing(base_trim) == DEFAULT_SCORING_CONFIG["weights"]["preferred_trim"]
    assert DEFAULT_SCORING_CONFIG["weights"]["manual_transmission"] > DEFAULT_SCORING_CONFIG["weights"]["non_convertible"]
    assert DEFAULT_SCORING_CONFIG["weights"]["preferred_trim"] < DEFAULT_SCORING_CONFIG["weights"]["non_ls2"]


def test_scoring_weights_are_configurable():
    config = {
        "base_score": 10,
        "weights": {
            "manual_transmission": 5,
            "non_convertible": 4,
            "non_ls2": 3,
            "preferred_trim": 2,
        },
        "preferred_trims": ["Z06"],
    }

    assert score_listing(listing(transmission="manual", body_style="Targa", engine="LS3", trim="Z06"), config) == 24
    assert score_listing(listing(transmission="automatic", body_style="Cabrio", engine="LS2", trim="Base"), config) == 10


def test_apply_score_updates_listing_score_in_place():
    item = listing(score=0, transmission="manual", body_style="Targa", engine="LS3", trim="Grand Sport")

    result = apply_score(item)

    assert result is item
    assert item.score == 100
