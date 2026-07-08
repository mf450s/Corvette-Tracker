"""Template for wiring a real image+text AI provider into Corvette Tracker.

Copy this file, rename the class, add your SDK/API call, then configure:

ai_enrichment:
  enabled: true
  provider: "your_module:YourProvider"
  max_images: 8

The tracker intentionally does not ship with a hardcoded paid provider or API key.
"""

from __future__ import annotations

from corvette_tracker.ai_enrichment import EnrichmentInput, EnrichmentResult


class ExampleVisionProvider:
    def analyze_listing(self, enrichment_input: EnrichmentInput) -> EnrichmentResult:
        """Replace this stub with a real multimodal model call.

        Send `enrichment_input.description`, `enrichment_input.image_urls`, and
        `enrichment_input.known_fields` to your provider. Return only fields the
        model can support with reasonable confidence; parser/source values are
        preserved by merge_enrichment_result and won't be overwritten.
        """
        # Example shape only. Do not use this as real analysis.
        return EnrichmentResult(
            provider="example-vision-provider",
            confidence=0.0,
            notes="Template provider; no real AI analysis performed.",
            evidence={
                "listing_id": enrichment_input.listing_id,
                "image_count": len(enrichment_input.image_urls),
            },
        )
