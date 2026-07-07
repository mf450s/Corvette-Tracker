from corvette_tracker.dedupe import assign_clusters
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
