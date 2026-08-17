from pathlib import Path

from corvette_tracker.cli import run_tracker, validate_crawl_quality
from corvette_tracker.models import Listing
from corvette_tracker.storage import TrackerStore


def payload_with_sources(*sources: str):
    return {"listings": [{"source": source, "title": f"{source} listing"} for source in sources]}


def test_crawl_quality_accepts_reasonable_autoscout_and_kleinanzeigen_counts():
    payload = payload_with_sources(*(["AutoScout24"] * 5), *(["Kleinanzeigen"] * 10))

    assert (
        validate_crawl_quality(
            payload, min_total=10, min_by_source={"AutoScout24": 5, "Kleinanzeigen": 10}
        )
        == []
    )


def test_crawl_quality_warns_when_live_sources_return_too_few_listings():
    payload = payload_with_sources(*(["AutoScout24"] * 2), *(["Kleinanzeigen"] * 3))

    warnings = validate_crawl_quality(
        payload, min_total=10, min_by_source={"AutoScout24": 5, "Kleinanzeigen": 10}
    )

    assert any("only 5 total listings" in warning for warning in warnings)
    assert any("only 2 AutoScout24 listings" in warning for warning in warnings)
    assert any("only 3 Kleinanzeigen listings" in warning for warning in warnings)


def test_run_tracker_validates_fresh_crawl_not_stale_database(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "tracker.sqlite"
    store = TrackerStore(db_path)
    store.upsert_listings(
        [
            Listing(
                id=f"kleinanzeigen_seed_{index}",
                source="Kleinanzeigen",
                source_listing_id=str(index),
                url=f"https://example.test/{index}",
                title=f"Chevrolet Corvette C6 seed {index}",
            )
            for index in range(10)
        ]
        + [
            Listing(
                id=f"autoscout24_seed_{index}",
                source="AutoScout24",
                source_listing_id=str(index),
                url=f"https://example.test/as24/{index}",
                title=f"Chevrolet Corvette C6 AS24 seed {index}",
            )
            for index in range(5)
        ]
    )
    monkeypatch.setattr("corvette_tracker.cli.collect_live", lambda config: ([], []))

    exit_code, payload = run_tracker(output_dir=tmp_path, database=db_path)

    assert exit_code == 3
    assert any("only 0 total listings" in warning for warning in payload.get("warnings", []))
    assert any("only 0 AutoScout24 listings" in warning for warning in payload.get("warnings", []))
    assert any(
        "only 0 Kleinanzeigen listings" in warning for warning in payload.get("warnings", [])
    )
