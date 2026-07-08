from __future__ import annotations

import argparse
import importlib
import shutil
import sys
from collections import Counter
from pathlib import Path

import yaml

from .ai_enrichment import AIEnrichmentProvider, enrich_listings
from .dedupe import assign_clusters
from .feed import build_feed_payload, write_exports
from .models import Listing
from .sources.autouncle import DEFAULT_URL as AUTOUNCLE_URL, fetch_autouncle
from .sources.autoscout24 import DEFAULT_URL as AS24_URL, fetch_autoscout24, parse_autoscout24_search
from .sources.classic_trader import DEFAULT_URL as CLASSIC_TRADER_URL, fetch_classic_trader
from .sources.kleinanzeigen import DEFAULT_URL as KA_URL, fetch_kleinanzeigen
from .sources.mobile_de import DEFAULT_URL as MOBILE_URL, fetch_mobile_de
from .storage import TrackerStore

DEFAULT_CONFIG = {
    "sources": {
        "autoscout24": {"enabled": True, "url": AS24_URL},
        "kleinanzeigen": {"enabled": True, "url": KA_URL},
        "autouncle": {"enabled": True, "url": AUTOUNCLE_URL},
        "classic_trader": {"enabled": True, "url": CLASSIC_TRADER_URL},
        "mobile_de": {"enabled": True, "url": MOBILE_URL},
    },
    "output_dir": ".",
    "database_path": "data/corvette_tracker.sqlite",
    "ai_enrichment": {"enabled": False, "provider": None, "max_images": 8},
    "quality": {
        "enabled": True,
        "min_total": 10,
        "min_by_source": {"AutoScout24": 5, "Kleinanzeigen": 10},
    },
}


def load_config(path: str | None) -> dict:
    if not path:
        return DEFAULT_CONFIG
    with Path(path).open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    merged = DEFAULT_CONFIG | loaded
    merged["sources"] = DEFAULT_CONFIG["sources"] | loaded.get("sources", {})
    merged["ai_enrichment"] = DEFAULT_CONFIG["ai_enrichment"] | loaded.get("ai_enrichment", {})
    merged["quality"] = DEFAULT_CONFIG["quality"] | loaded.get("quality", {})
    return merged


def validate_crawl_quality(payload: dict, *, min_total: int, min_by_source: dict[str, int]) -> list[str]:
    listings = payload.get("listings") or []
    source_counts = Counter(str(item.get("source") or "unknown") for item in listings)
    warnings: list[str] = []
    if len(listings) < min_total:
        warnings.append(f"Crawler quality: only {len(listings)} total listings parsed; expected at least {min_total}")
    for source, expected in min_by_source.items():
        actual = source_counts.get(source, 0)
        if actual < expected:
            warnings.append(f"Crawler quality: only {actual} {source} listings parsed; expected at least {expected}")
    return warnings


def load_ai_provider(dotted_path: str) -> AIEnrichmentProvider:
    if ":" not in dotted_path:
        raise ValueError("AI provider must use 'module:ClassName' format")
    module_name, class_name = dotted_path.split(":", 1)
    module = importlib.import_module(module_name)
    provider_class = getattr(module, class_name)
    return provider_class()


def _copy_site_to_root(output_dir: Path) -> None:
    source = output_dir / "site" / "index.html"
    if source.exists():
        shutil.copyfile(source, output_dir / "index.html")


def collect_live(config: dict) -> tuple[list[Listing], list[str]]:
    listings: list[Listing] = []
    warnings: list[str] = []
    sources = config.get("sources", {})
    if sources.get("autoscout24", {}).get("enabled", True):
        try:
            listings.extend(fetch_autoscout24(sources.get("autoscout24", {}).get("url", AS24_URL)))
        except Exception as exc:  # keep one blocked source from killing all exports
            warnings.append(f"AutoScout24: {exc}")
    if sources.get("kleinanzeigen", {}).get("enabled", True):
        try:
            listings.extend(fetch_kleinanzeigen(sources.get("kleinanzeigen", {}).get("url", KA_URL)))
        except Exception as exc:
            warnings.append(f"Kleinanzeigen: {exc}")
    if sources.get("autouncle", {}).get("enabled", True):
        try:
            listings.extend(fetch_autouncle(sources.get("autouncle", {}).get("url", AUTOUNCLE_URL)))
        except Exception as exc:
            warnings.append(f"AutoUncle: {exc}")
    if sources.get("classic_trader", {}).get("enabled", True):
        try:
            listings.extend(fetch_classic_trader(sources.get("classic_trader", {}).get("url", CLASSIC_TRADER_URL)))
        except Exception as exc:
            warnings.append(f"Classic Trader: {exc}")
    if sources.get("mobile_de", {}).get("enabled", True):
        try:
            listings.extend(fetch_mobile_de(sources.get("mobile_de", {}).get("url", MOBILE_URL)))
        except Exception as exc:
            warnings.append(f"mobile.de: {exc}")
    return listings, warnings


def run_tracker(
    config_path: str | None = None,
    *,
    fixture: str | None = None,
    output_dir: str | Path | None = None,
    database: str | Path | None = None,
    ai_provider: str | None = None,
    ai_max_images: int | None = None,
) -> tuple[int, dict]:
    config = load_config(config_path)
    resolved_output_dir = Path(output_dir or config.get("output_dir", ".")).resolve()
    db_path = Path(database or config.get("database_path", "data/corvette_tracker.sqlite"))
    if not db_path.is_absolute():
        db_path = resolved_output_dir / db_path

    warnings: list[str] = []
    if fixture:
        html = Path(fixture).read_text(encoding="utf-8")
        listings = parse_autoscout24_search(html, "https://fixture.local/search")
    else:
        listings, warnings = collect_live(config)

    listings = assign_clusters(listings)
    quality_warnings: list[str] = []
    quality_config = config.get("quality", {})
    if not fixture and quality_config.get("enabled", True):
        quality_warnings = validate_crawl_quality(
            {"listings": [listing.to_dict() for listing in listings]},
            min_total=int(quality_config.get("min_total", 10)),
            min_by_source={str(source): int(minimum) for source, minimum in (quality_config.get("min_by_source") or {}).items()},
        )
        warnings.extend(quality_warnings)

    ai_config = config.get("ai_enrichment", {})
    provider_path = ai_provider or ai_config.get("provider")
    ai_enabled = bool(ai_provider or ai_config.get("enabled"))
    if ai_enabled and provider_path:
        try:
            listings = enrich_listings(listings, load_ai_provider(provider_path), max_images=int(ai_max_images or ai_config.get("max_images", 8)))
        except Exception as exc:
            warnings.append(f"AI enrichment: {exc}")
    store = TrackerStore(db_path)
    changed = store.upsert_listings(listings)
    payload = build_feed_payload(store.list_active())
    if warnings:
        payload["warnings"] = warnings
    write_exports(payload, resolved_output_dir)
    _copy_site_to_root(resolved_output_dir)
    if quality_warnings:
        return 3, payload
    return (0 if changed else 2), payload


def run(args: argparse.Namespace) -> int:
    exit_code, payload = run_tracker(
        args.config,
        fixture=args.fixture,
        output_dir=args.output_dir,
        database=args.database,
        ai_provider=args.ai_provider,
        ai_max_images=args.ai_max_images,
    )
    for warning in payload.get("warnings", []):
        print(f"WARN {warning}", file=sys.stderr)
    output_dir = Path(args.output_dir or load_config(args.config).get("output_dir", ".")).resolve()
    print(f"Wrote {payload['summary']['total_active']} listings to {output_dir / 'site' / 'index.html'}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="corvette-tracker")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="crawl sources, update sqlite, export website/feed")
    run_parser.add_argument("--config")
    run_parser.add_argument("--fixture", help="parse a local AutoScout24-like fixture instead of live crawling")
    run_parser.add_argument("--output-dir")
    run_parser.add_argument("--database")
    run_parser.add_argument("--ai-provider", help="AI enrichment provider as module:ClassName")
    run_parser.add_argument("--ai-max-images", type=int, help="Maximum images per listing sent to AI enrichment")
    run_parser.set_defaults(func=run)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
