from corvette_tracker.dedupe import assign_clusters, enrich_clusters
from corvette_tracker.models import Listing


def make_listing(**overrides):
    base = dict(
        id="src_1",
        source="fixture",
        source_listing_id="1",
        url="https://example.test/1",
        title="Chevrolet Corvette C6 Z06",
        generation="C6",
        price_eur=59900,
        mileage_km=72000,
        location_raw="München",
        trim="Z06",
        engine="LS7",
        image_urls=[],
        risk_flags=[],
        score=80,
        change_type="new",
    )
    base.update(overrides)
    return Listing(**base)


def test_assign_clusters_uses_vin_as_hard_match():
    a = make_listing(id="a", vin="1G1YY26E965100001", url="https://a.test")
    b = make_listing(id="b", vin="1G1YY26E965100001", url="https://b.test")

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id == clustered[1].cluster_id
    assert clustered[0].cluster_id.startswith("vin_")


def test_assign_clusters_uses_soft_match_for_same_vehicle_without_vin():
    a = make_listing(id="a", url="https://a.test", source="autoscout24")
    b = make_listing(id="b", url="https://b.test", source="kleinanzeigen")

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id == clustered[1].cluster_id


def test_assign_clusters_keeps_different_price_mileage_apart():
    a = make_listing(id="a", url="https://example.test/a", price_eur=59900, mileage_km=72000)
    b = make_listing(id="b", url="https://example.test/b", price_eur=73000, mileage_km=22000)

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id != clustered[1].cluster_id


def test_assign_clusters_removes_exact_url_duplicates():
    a = make_listing(id="a", source_listing_id="ka-0", url="https://example.test/same")
    b = make_listing(id="b", source_listing_id="344", url="https://example.test/same")

    clustered = assign_clusters([a, b])

    assert len(clustered) == 1
    assert clustered[0].source_listing_id == "344"


# ── Soft-match with extended fields ──────────────────────────────────────────

def test_assign_clusters_uses_transmission_year_power_fields():
    """Listings matching on legacy fields but with different transmission/year/power
    are still clustered (legacy fallback preserves backward compat).
    But when price & mileage also differ, new fields help keep them apart."""
    # Same legacy fields → same cluster (backward compat)
    a = make_listing(id="a", url="https://a.test", transmission="manual", first_registration="2005-06", power_hp=404)
    b = make_listing(id="b", url="https://b.test", transmission="automatic", first_registration="2008-03", power_hp=437)

    clustered = assign_clusters([a, b])
    assert clustered[0].cluster_id == clustered[1].cluster_id  # legacy fallback matches

    # Different price + different mileage + different fields → different cluster
    c = make_listing(id="c", url="https://c.test", transmission="manual", first_registration="2005-06", power_hp=404,
                     price_eur=74900, mileage_km=22000)
    d = make_listing(id="d", url="https://d.test", transmission="automatic", first_registration="2008-03", power_hp=437,
                     price_eur=59900, mileage_km=72000)

    clustered2 = assign_clusters([c, d])
    assert clustered2[0].cluster_id != clustered2[1].cluster_id


def test_assign_clusters_matches_different_trim_via_relaxed_key():
    """Listings with the same engine/location/price/mileage but different trim
    should still be clustered (via the no_trim fallback key)."""
    a = make_listing(id="a", url="https://a.test", trim="Z06", engine="LS7", price_eur=59900, mileage_km=72000)
    b = make_listing(id="b", url="https://b.test", trim="C6 Z06", engine="LS7", price_eur=59500, mileage_km=71000)

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id == clustered[1].cluster_id


def test_assign_clusters_matches_different_location_via_relaxed_key():
    """Listings differing only on location should still match via no_loc key."""
    a = make_listing(id="a", url="https://a.test", location_raw="München", engine="LS7", trim="Z06", price_eur=59900, mileage_km=72000)
    b = make_listing(id="b", url="https://b.test", location_raw="Berlin", engine="LS7", trim="Z06", price_eur=59500, mileage_km=71000)

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id == clustered[1].cluster_id


def test_assign_clusters_matches_different_engine_via_relaxed_key():
    """Listings differing only on engine (one inferred, one explicit) match via no_eng key."""
    a = make_listing(id="a", url="https://a.test", engine="LS7", trim="Z06", price_eur=59900, mileage_km=72000)
    b = make_listing(id="b", url="https://b.test", engine=None, trim="Z06", price_eur=59000, mileage_km=71000)

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id == clustered[1].cluster_id


def test_assign_clusters_does_not_overmatch():
    """Listings that share engine+location but not price+mileage should NOT match
    even via the legacy fallback."""
    a = make_listing(id="a", url="https://a.test", engine="LS7", trim="Z06", price_eur=59900, mileage_km=72000, location_raw="München")
    b = make_listing(id="b", url="https://b.test", engine="LS7", trim="Z51", price_eur=74900, mileage_km=22000, location_raw="München")

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id != clustered[1].cluster_id


# ── enrich_clusters ──────────────────────────────────────────────────────────

def test_enrich_clusters_fills_missing_scalar_fields():
    """enrich_clusters fills missing fields from cluster mates."""
    a = make_listing(id="a", url="https://a.test", transmission=None, mileage_km=72000)
    b = make_listing(id="b", url="https://b.test", transmission="manual", mileage_km=71000)

    clustered = assign_clusters([a, b])
    assert clustered[0].cluster_id == clustered[1].cluster_id  # same bucket price/mileage

    enriched = enrich_clusters(clustered)

    for listing in enriched:
        assert listing.transmission == "manual", f"{listing.id} should have transmission filled"
        assert listing.mileage_km in (72000, 71000), f"{listing.id} should have mileage filled"


def test_enrich_clusters_merges_list_fields():
    """enrich_clusters merges list fields (equipment, risk_flags) across cluster."""
    a = make_listing(id="a", url="https://a.test", equipment=["ABS", "ESP"], risk_flags=["accident_reported"])
    b = make_listing(id="b", url="https://b.test", equipment=["ABS", "Schiebedach"], risk_flags=["damage_reported"])

    clustered = assign_clusters([a, b])
    enriched = enrich_clusters(clustered)

    for listing in enriched:
        assert "ABS" in listing.equipment
        assert "ESP" in listing.equipment
        assert "Schiebedach" in listing.equipment
        assert "accident_reported" in listing.risk_flags
        assert "damage_reported" in listing.risk_flags


def test_enrich_clusters_picks_best_score():
    """enrich_clusters propagates the highest score to all cluster members."""
    a = make_listing(id="a", url="https://a.test", score=50)
    b = make_listing(id="b", url="https://b.test", score=85)

    clustered = assign_clusters([a, b])
    enriched = enrich_clusters(clustered)

    for listing in enriched:
        assert listing.score == 85, f"{listing.id} should have score 85, got {listing.score}"


def test_enrich_clusters_merges_image_urls():
    """enrich_clusters merges image URLs deduplicated across cluster."""
    a = make_listing(id="a", url="https://a.test", image_urls=["https://img.test/1.jpg", "https://img.test/2.jpg"])
    b = make_listing(id="b", url="https://b.test", image_urls=["https://img.test/2.jpg", "https://img.test/3.jpg"])

    clustered = assign_clusters([a, b])
    enriched = enrich_clusters(clustered)

    for listing in enriched:
        assert len(listing.image_urls) == 3
        assert "https://img.test/1.jpg" in listing.image_urls
        assert "https://img.test/2.jpg" in listing.image_urls
        assert "https://img.test/3.jpg" in listing.image_urls


def test_enrich_clusters_preserves_singletons():
    """enrich_clusters does not modify listings that are not in a cluster."""
    a = make_listing(id="a", url="https://a.test", score=50)
    b = make_listing(id="b", url="https://b.test", score=85, trim="ZR1", engine="LS9", price_eur=120000, mileage_km=30000)

    clustered = assign_clusters([a, b])
    assert clustered[0].cluster_id != clustered[1].cluster_id

    enriched = enrich_clusters(clustered)
    assert len(enriched) == 2
    # Each keeps its own score
    assert enriched[0].score in (50, 85)
    assert enriched[1].score in (50, 85)


# ── Color-based matching ──────────────────────────────────────────────────────


def test_assign_clusters_same_color_matches():
    """Listings with same exterior_color should match (via color-augmented keys)."""
    a = make_listing(id="a", url="https://a.test", engine="LS7", trim="Z06",
                     price_eur=59900, mileage_km=72000, exterior_color="Schwarz")
    b = make_listing(id="b", url="https://b.test", engine="LS7", trim="C6 Z06",
                     price_eur=59500, mileage_km=71000, exterior_color="schwarz")

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id == clustered[1].cluster_id


def test_assign_clusters_different_color_keeps_apart():
    """Listings with clearly different exterior colors and different price/mileage
    should NOT match (color augments separation through more specific keys,
    and legacy fallback can't bridge different price+mileage)."""
    a = make_listing(id="a", url="https://a.test", engine="LS7", trim="Z06",
                     price_eur=59900, mileage_km=72000, exterior_color="Schwarz")
    b = make_listing(id="b", url="https://b.test", engine="LS7", trim="Z06",
                     price_eur=74900, mileage_km=22000, exterior_color="Rot")

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id != clustered[1].cluster_id


def test_assign_clusters_color_normalization():
    """German and English color names for the same color should match."""
    a = make_listing(id="a", url="https://a.test", engine="LS7", trim="Z06",
                     price_eur=59900, mileage_km=72000, exterior_color="Schwarz")
    b = make_listing(id="b", url="https://b.test", engine="LS7", trim="Z06",
                     price_eur=59500, mileage_km=71000, exterior_color="Black")

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id == clustered[1].cluster_id


def test_assign_clusters_color_missing_fallback():
    """When one listing has no color, matching should still work via fallback keys."""
    a = make_listing(id="a", url="https://a.test", engine="LS7", trim="Z06",
                     price_eur=59900, mileage_km=72000, exterior_color="Schwarz")
    b = make_listing(id="b", url="https://b.test", engine="LS7", trim="Z06",
                     price_eur=59500, mileage_km=71000, exterior_color=None)

    clustered = assign_clusters([a, b])

    assert clustered[0].cluster_id == clustered[1].cluster_id


# ── Improved enrichment ───────────────────────────────────────────────────────


def test_enrich_clusters_prefers_lower_mileage():
    """enrich_clusters prefers the lower mileage across a cluster."""
    a = make_listing(id="a", url="https://a.test", mileage_km=72000, engine="LS7", trim="Z06")
    b = make_listing(id="b", url="https://b.test", mileage_km=71000, engine="LS7", trim="Z06")

    clustered = assign_clusters([a, b])
    enriched = enrich_clusters(clustered)

    for listing in enriched:
        assert listing.mileage_km == 71000, f"{listing.id} should have mileage 71000"


def test_enrich_clusters_mileage_no_change_when_both_equal():
    """enrich_clusters keeps mileage when both listings report the same."""
    a = make_listing(id="a", url="https://a.test", mileage_km=72000, engine="LS7", trim="Z06")
    b = make_listing(id="b", url="https://b.test", mileage_km=72000, engine="LS7", trim="Z06")

    clustered = assign_clusters([a, b])
    enriched = enrich_clusters(clustered)

    for listing in enriched:
        assert listing.mileage_km == 72000


def test_enrich_clusters_color_prefers_more_descriptive():
    """enrich_clusters picks the longer/more descriptive color name
    when both normalize to the same base color."""
    a = make_listing(id="a", url="https://a.test", engine="LS7", trim="Z06",
                     price_eur=59900, mileage_km=72000, exterior_color="Black")
    b = make_listing(id="b", url="https://b.test", engine="LS7", trim="Z06",
                     price_eur=59500, mileage_km=71000, exterior_color="schwarz")

    clustered = assign_clusters([a, b])
    enriched = enrich_clusters(clustered)

    for listing in enriched:
        # "schwarz" (7 chars) > "Black" (5 chars), both normalize to "black"
        assert listing.exterior_color == "schwarz", (
            f"{listing.id} should have 'schwarz' got {listing.exterior_color!r}"
        )


def test_enrich_clusters_merges_multi_source_details():
    """Three listings of the same car from different sources merge into complete records.
    Each source has partial details — the merge fills gaps from all sources."""
    a = make_listing(id="a", url="https://a.test", source="autoscout24",
                     price_eur=59900, mileage_km=72000,
                     exterior_color="Schwarz", engine="LS7", trim="Z06",
                     transmission=None, power_hp=505,
                     equipment=["ABS", "ESP"])
    b = make_listing(id="b", url="https://b.test", source="kleinanzeigen",
                     price_eur=59500, mileage_km=71000,
                     exterior_color=None, engine="LS7", trim="C6 Z06",
                     transmission="manual", power_hp=None,
                     equipment=["ABS", "Schiebedach"])
    c = make_listing(id="c", url="https://c.test", source="mobile.de",
                     price_eur=59000, mileage_km=71500,
                     exterior_color="Black", engine="LS7", trim="Z06",
                     transmission="manual", power_hp=505,
                     equipment=["Schiebedach", "Tempomat"],
                     interior_color="Schwarz")

    clustered = assign_clusters([a, b, c])
    assert clustered[0].cluster_id == clustered[1].cluster_id == clustered[2].cluster_id

    enriched = enrich_clusters(clustered)

    for listing in enriched:
        # Color merged: "Schwarz" (7) vs "Black" (5), both → "black", longer wins
        assert listing.exterior_color == "Schwarz", (
            f"{listing.id} exterior_color={listing.exterior_color!r}"
        )
        # Transmission filled from sources that have it
        assert listing.transmission == "manual", f"{listing.id} transmission={listing.transmission}"
        # Power filled from sources that have it
        assert listing.power_hp == 505, f"{listing.id} power_hp={listing.power_hp}"
        # Lower price propagated (c: 59000 < a: 59900, b: 59500)
        assert listing.price_eur == 59000, f"{listing.id} price_eur={listing.price_eur}"
        # Lower mileage propagated across all members via third pass
        assert listing.mileage_km == 71000, f"{listing.id} mileage_km={listing.mileage_km}"
        # All equipment merged (deduplicated)
        assert "ABS" in listing.equipment
        assert "ESP" in listing.equipment
        assert "Schiebedach" in listing.equipment
        assert "Tempomat" in listing.equipment
        # Interior color from mobile.de propagated
        assert listing.interior_color == "Schwarz"


def test_enrich_clusters_merges_eu_spec():
    """eu_spec boolean is propagated across cluster."""
    a = make_listing(id="a", url="https://a.test", engine="LS7", trim="Z06",
                     price_eur=59900, mileage_km=72000, eu_spec=True)
    b = make_listing(id="b", url="https://b.test", engine="LS7", trim="Z06",
                     price_eur=59500, mileage_km=71000, eu_spec=None)

    clustered = assign_clusters([a, b])
    enriched = enrich_clusters(clustered)

    for listing in enriched:
        assert listing.eu_spec is True
