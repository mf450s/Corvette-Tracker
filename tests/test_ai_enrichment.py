from corvette_tracker.ai_enrichment import (
    AIEnrichmentProvider,
    EnrichmentResult,
    build_enrichment_input,
    enrich_listings,
    merge_enrichment_result,
)
from corvette_tracker.models import Listing


def make_listing(**overrides):
    base = dict(
        id="listing-1",
        source="fixture",
        source_listing_id="1",
        url="https://example.test/listing/1",
        title="Chevrolet Corvette C6",
        generation="C6",
        price_eur=41900,
        mileage_km=61000,
        engine=None,
        probable_engine="LS2",
        engine_confidence=0.86,
        engine_note="Leistung 404 PS → wahrscheinlich LS2",
        trim="Base",
        description_text="EU Modell, schwarze Lederausstattung, Automatik, Head-Up Display, NPP Auspuff.",
        image_urls=["https://example.test/1.jpg", "https://example.test/2.jpg"],
        risk_flags=[],
        score=65,
    )
    base.update(overrides)
    return Listing(**base)


class FakeProvider(AIEnrichmentProvider):
    def analyze_listing(self, enrichment_input):
        return EnrichmentResult(
            provider="fake-ai",
            confidence=0.82,
            exterior_color="Schwarz",
            interior_color="Schwarz Leder",
            transmission="automatic",
            eu_spec=True,
            equipment=["Head-Up Display", "NPP Klappenauspuff"],
            visual_flags=["aftermarket_wheels"],
            risk_flags=["modified_heavily"],
            notes="Bilder zeigen schwarze C6 mit Zubehörfelgen.",
        )


def test_build_enrichment_input_contains_description_images_and_existing_fields():
    listing = make_listing()

    enrichment_input = build_enrichment_input(listing, max_images=1)

    assert enrichment_input.listing_id == "listing-1"
    assert enrichment_input.title == "Chevrolet Corvette C6"
    assert enrichment_input.description == listing.description_text
    assert enrichment_input.image_urls == ["https://example.test/1.jpg"]
    assert enrichment_input.known_fields["probable_engine"] == "LS2"
    assert enrichment_input.known_fields["price_eur"] == 41900


def test_merge_enrichment_result_fills_missing_fields_and_preserves_existing_explicit_values():
    listing = make_listing(transmission="manual", risk_flags=["mileage_unclear"])
    result = EnrichmentResult(
        provider="fake-ai",
        confidence=0.9,
        exterior_color="Schwarz",
        interior_color="Schwarz Leder",
        transmission="automatic",
        eu_spec=True,
        equipment=["Head-Up Display"],
        risk_flags=["modified_heavily", "mileage_unclear"],
        notes="AI notes",
    )

    enriched = merge_enrichment_result(listing, result)

    assert enriched.exterior_color == "Schwarz"
    assert enriched.interior_color == "Schwarz Leder"
    assert enriched.transmission == "manual"
    assert enriched.eu_spec is True
    assert enriched.equipment == ["Head-Up Display"]
    assert enriched.risk_flags == ["mileage_unclear", "modified_heavily"]
    assert enriched.ai_enrichment["provider"] == "fake-ai"
    assert enriched.ai_enrichment["confidence"] == 0.9


def test_enrich_listings_runs_provider_for_each_listing():
    listings = [make_listing(id="a"), make_listing(id="b", source_listing_id="2")]

    enriched = enrich_listings(listings, FakeProvider(), max_images=2)

    assert [listing.ai_enrichment["provider"] for listing in enriched] == ["fake-ai", "fake-ai"]
    assert all(listing.equipment for listing in enriched)
    assert all("modified_heavily" in listing.risk_flags for listing in enriched)


def test_load_provider_from_dotted_path_instantiates_class():
    from corvette_tracker.cli import load_ai_provider

    provider = load_ai_provider("tests.test_ai_enrichment:FakeProvider")

    assert provider.__class__.__name__ == "FakeProvider"
    assert provider.analyze_listing(build_enrichment_input(make_listing())).provider == "fake-ai"
