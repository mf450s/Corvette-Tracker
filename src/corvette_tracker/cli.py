from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

from .ai_enrichment import enrich_listings
from .config import (
    DEFAULT_CONFIG,
    load_ai_provider,
    load_config,
    validate_crawl_quality,
)
from .dedupe import assign_clusters, enrich_clusters
from .feed import build_feed_payload, write_exports
from .health import check_stale_offers
from .models import Listing
from .re_scrape import re_scrape_offer
from .scoring import apply_scores
from .sources.autouncle import DEFAULT_URL as AUTOUNCLE_URL, fetch_autouncle
from .sources.autoscout24 import DEFAULT_URL as AS24_URL, fetch_autoscout24, parse_autoscout24_search
from .sources.classic_trader import DEFAULT_URL as CLASSIC_TRADER_URL, fetch_classic_trader
from .sources.kleinanzeigen import DEFAULT_URL as KA_URL, fetch_kleinanzeigen
from .sources.mobile_de import DEFAULT_URL as MOBILE_URL, fetch_mobile_de
from .storage import TrackerStore


def _copy_site_to_root(output_dir: Path) -> None:
    source = output_dir / "site" / "index.html"
    if source.exists():
        shutil.copyfile(source, output_dir / "index.html")


def _source_urls(source_config: dict, default_url: str) -> list[str]:
    raw_urls = source_config.get("urls")
    if isinstance(raw_urls, list):
        urls = [str(url).strip() for url in raw_urls if str(url or "").strip()]
    else:
        urls = []
    primary = str(source_config.get("url") or "").strip()
    if primary:
        urls.insert(0, primary)
    return list(dict.fromkeys(urls or [default_url]))


def _fetch_source(fetcher, source_name: str, source_config: dict, default_url: str) -> tuple[list[Listing], list[str]]:
    listings: list[Listing] = []
    warnings: list[str] = []
    for url in _source_urls(source_config, default_url):
        try:
            listings.extend(fetcher(url))
        except Exception as exc:
            warnings.append(f"{source_name} ({url}): {exc}")
    return listings, warnings


def collect_live(config: dict) -> tuple[list[Listing], list[str]]:
    listings: list[Listing] = []
    warnings: list[str] = []
    sources = config.get("sources", {})
    if sources.get("autoscout24", {}).get("enabled", True):
        fetched, source_warnings = _fetch_source(fetch_autoscout24, "AutoScout24", sources.get("autoscout24", {}), AS24_URL)
        listings.extend(fetched)
        warnings.extend(source_warnings)
    if sources.get("kleinanzeigen", {}).get("enabled", True):
        fetched, source_warnings = _fetch_source(fetch_kleinanzeigen, "Kleinanzeigen", sources.get("kleinanzeigen", {}), KA_URL)
        listings.extend(fetched)
        warnings.extend(source_warnings)
    if sources.get("autouncle", {}).get("enabled", True):
        fetched, source_warnings = _fetch_source(fetch_autouncle, "AutoUncle", sources.get("autouncle", {}), AUTOUNCLE_URL)
        listings.extend(fetched)
        warnings.extend(source_warnings)
    if sources.get("classic_trader", {}).get("enabled", True):
        fetched, source_warnings = _fetch_source(fetch_classic_trader, "Classic Trader", sources.get("classic_trader", {}), CLASSIC_TRADER_URL)
        listings.extend(fetched)
        warnings.extend(source_warnings)
    if sources.get("mobile_de", {}).get("enabled", True):
        fetched, source_warnings = _fetch_source(fetch_mobile_de, "mobile.de", sources.get("mobile_de", {}), MOBILE_URL)
        listings.extend(fetched)
        warnings.extend(source_warnings)
    return listings, warnings


def run_tracker(
    config_path: str | None = None,
    *,
    fixture: str | None = None,
    output_dir: str | Path | None = None,
    database: str | Path | None = None,
    ai_provider: str | None = None,
    ai_max_images: int | None = None,
    show_hidden: bool = False,
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
    listings = enrich_clusters(listings)
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
    scoring_config = config.get("scoring")
    listings = apply_scores(listings, scoring_config)
    store = TrackerStore(db_path)
    changed = store.upsert_listings(listings)
    payload = build_feed_payload(
        apply_scores(store.list_active(), scoring_config),
        show_hidden=show_hidden,
    )
    if warnings:
        payload["warnings"] = warnings
    if len(changed) != len(listings):
        payload.setdefault("warnings", []).append(
            f"upsert: {len(listings) - len(changed)} von {len(listings)} "
            "Listings konnten nicht gespeichert werden"
        )
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
        show_hidden=args.show_hidden,
    )
    for warning in payload.get("warnings", []):
        print(f"WARN {warning}", file=sys.stderr)
    output_dir = Path(args.output_dir or load_config(args.config).get("output_dir", ".")).resolve()
    print(f"Wrote {payload['summary']['total_active']} listings to {output_dir / 'site' / 'index.html'}")
    return exit_code


def run_health(args: argparse.Namespace) -> int:
    database_path = Path(args.database or load_config(args.config).get("database_path", "data/corvette_tracker.sqlite"))
    if not database_path.is_absolute():
        output_dir = Path(args.output_dir or load_config(args.config).get("output_dir", ".")).resolve()
        database_path = output_dir / database_path

    store = TrackerStore(database_path)
    summary = check_stale_offers(store, force=True, dry_run=getattr(args, "dry_run", False))

    mode = " (dry-run)" if getattr(args, "dry_run", False) else ""
    print(f"Health check{mode}: {summary['checked']} checked, {summary['skipped']} skipped, "
          f"{summary['online']} online, {summary['offline']} offline, "
          f"{summary['failed']} failed, {summary['total']} total")
    if summary["results"]:
        for r in summary["results"]:
            status_str = "online" if r["is_online"] else "offline"
            extra = f" (HTTP {r['http_status']})" if r["http_status"] else f" ({r['error']})"
            print(f"  {r['listing_id']}: {status_str}{extra}")

    check_file = Path(args.check_file) if getattr(args, "check_file", None) else None
    if check_file:
        check_file.write_text(
            f"checked_at={summary['checked_at']}\n"
            f"checked={summary['checked']}\n"
            f"online={summary['online']}\n"
            f"offline={summary['offline']}\n"
            f"failed={summary['failed']}\n",
        )

    return 0 if summary["failed"] == 0 else 1


def run_scrape(args: argparse.Namespace) -> int:
    database_path = Path(args.database or load_config(getattr(args, "config", None)).get("database_path", "data/corvette_tracker.sqlite"))
    if not database_path.is_absolute():
        output_dir = Path(getattr(args, "output_dir", ".")).resolve()
        database_path = output_dir / database_path

    store = TrackerStore(database_path)
    result = re_scrape_offer(
        store,
        offer_id=args.offer_id,
        url=args.url,
    )

    status = "OK" if result["success"] else "FEHLGESCHLAGEN"
    print(f"[{status}] {result.get('message', '')}")
    if result.get("change_type"):
        print(f"  Änderung: {result['change_type']}")
    return 0 if result["success"] else 1


def run_hide(args: argparse.Namespace) -> int:
    """Mark a listing as hidden."""
    database_path = Path(args.database or load_config(getattr(args, "config", None)).get("database_path", "data/corvette_tracker.sqlite"))
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    store = TrackerStore(database_path)
    store.hide_listing(args.listing_id)
    print(f"Angebot {args.listing_id} wurde versteckt")
    return 0


def run_unhide(args: argparse.Namespace) -> int:
    """Unmark a hidden listing."""
    database_path = Path(args.database or load_config(getattr(args, "config", None)).get("database_path", "data/corvette_tracker.sqlite"))
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    store = TrackerStore(database_path)
    store.unhide_listing(args.listing_id)
    print(f"Angebot {args.listing_id} ist wieder sichtbar")
    return 0


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
    run_parser.add_argument("--show-hidden", action="store_true", help="Include hidden listings in exports")
    run_parser.set_defaults(func=run)

    health_parser = sub.add_parser("health", help="check online status of all known listings")
    health_parser.add_argument("--config")
    health_parser.add_argument("--output-dir")
    health_parser.add_argument("--database")
    health_parser.add_argument("--check-file", help="write check metadata to this file (for cron/scheduler integration)")
    health_parser.add_argument("--dry-run", action="store_true", help="check URLs but do not update the database")
    health_parser.set_defaults(func=run_health)

    scrape_parser = sub.add_parser("scrape", help="re-scrape/re-verify a single offer by ID or URL")
    scrape_parser.add_argument("--offer-id", help="Listing database ID (primary key)")
    scrape_parser.add_argument("--url", help="Direct URL of the offer")
    scrape_parser.add_argument("--database")
    scrape_parser.set_defaults(func=run_scrape)

    hide_parser = sub.add_parser("hide", help="hide a listing from overview/exports")
    hide_parser.add_argument("listing_id", help="Listing database ID (primary key)")
    hide_parser.add_argument("--config")
    hide_parser.add_argument("--output-dir")
    hide_parser.add_argument("--database")
    hide_parser.set_defaults(func=run_hide)

    unhide_parser = sub.add_parser("unhide", help="unhide a listing and show it in overview/exports again")
    unhide_parser.add_argument("listing_id", help="Listing database ID (primary key)")
    unhide_parser.add_argument("--config")
    unhide_parser.add_argument("--output-dir")
    unhide_parser.add_argument("--database")
    unhide_parser.set_defaults(func=run_unhide)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
