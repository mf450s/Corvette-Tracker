from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

from .dedupe import assign_clusters
from .feed import build_feed_payload, write_exports
from .models import Listing
from .sources.autoscout24 import DEFAULT_URL as AS24_URL, fetch_autoscout24, parse_autoscout24_search
from .sources.kleinanzeigen import DEFAULT_URL as KA_URL, fetch_kleinanzeigen
from .sources.mobile_de import DEFAULT_URL as MOBILE_URL, fetch_mobile_de
from .storage import TrackerStore

DEFAULT_CONFIG = {
    "sources": {
        "autoscout24": {"enabled": True, "url": AS24_URL},
        "kleinanzeigen": {"enabled": True, "url": KA_URL},
        "mobile_de": {"enabled": True, "url": MOBILE_URL},
    },
    "output_dir": ".",
    "database_path": "data/corvette_tracker.sqlite",
}


def load_config(path: str | None) -> dict:
    if not path:
        return DEFAULT_CONFIG
    with Path(path).open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    merged = DEFAULT_CONFIG | loaded
    merged["sources"] = DEFAULT_CONFIG["sources"] | loaded.get("sources", {})
    return merged


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
    if sources.get("mobile_de", {}).get("enabled", True):
        try:
            listings.extend(fetch_mobile_de(sources.get("mobile_de", {}).get("url", MOBILE_URL)))
        except Exception as exc:
            warnings.append(f"mobile.de: {exc}")
    return listings, warnings


def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    output_dir = Path(args.output_dir or config.get("output_dir", ".")).resolve()
    db_path = Path(args.database or config.get("database_path", "data/corvette_tracker.sqlite"))
    if not db_path.is_absolute():
        db_path = output_dir / db_path

    warnings: list[str] = []
    if args.fixture:
        html = Path(args.fixture).read_text(encoding="utf-8")
        listings = parse_autoscout24_search(html, "https://fixture.local/search")
    else:
        listings, warnings = collect_live(config)

    listings = assign_clusters(listings)
    store = TrackerStore(db_path)
    changed = store.upsert_listings(listings)
    payload = build_feed_payload(changed)
    if warnings:
        payload["warnings"] = warnings
    write_exports(payload, output_dir)
    _copy_site_to_root(output_dir)
    for warning in warnings:
        print(f"WARN {warning}", file=sys.stderr)
    print(f"Wrote {len(changed)} listings to {output_dir / 'site' / 'index.html'}")
    return 0 if changed else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="corvette-tracker")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="crawl sources, update sqlite, export website/feed")
    run_parser.add_argument("--config")
    run_parser.add_argument("--fixture", help="parse a local AutoScout24-like fixture instead of live crawling")
    run_parser.add_argument("--output-dir")
    run_parser.add_argument("--database")
    run_parser.set_defaults(func=run)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
