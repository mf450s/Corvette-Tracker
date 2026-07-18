from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .storage import TrackerStore

log = logging.getLogger(__name__)

# How long cached status results are considered fresh (seconds)
CACHE_TTL_SECONDS = 300

# HTTP request timeout per URL check
CHECK_TIMEOUT = 10

# Max redirects to follow (0 = don't follow any, just report the redirect status)
FOLLOW_REDIRECTS = True


def _check_single_url(url: str) -> tuple[int | None, str | None]:
    """Check whether a single URL is reachable.

    Tries HEAD first, falls back to GET if the server rejects HEAD.
    Returns (http_status, error_message).
    - (200, None) on success
    - (status_code, None) on non-2xx
    - (None, "error message") on connection failure / timeout
    """
    if not url:
        return None, "empty URL"

    def _do_request(method: str):
        req = urllib.request.Request(url, method=method)
        opener = urllib.request.build_opener(_RedirectHandler())
        return opener.open(req, timeout=CHECK_TIMEOUT)

    for method in ("HEAD", "GET"):
        try:
            with _do_request(method) as response:
                status = response.status
                if 200 <= status < 300:
                    return status, None
                return status, None
        except urllib.error.HTTPError as exc:
            # HEAD method rejected (405) → try GET
            if exc.code == 405 and method == "HEAD":
                continue
            # Other HTTP errors: report the status code
            return exc.code, None
        except urllib.error.URLError:
            if method == "HEAD":
                continue
            return None, "connection failed"
        except TimeoutError:
            return None, "timeout"
        except OSError as exc:
            return None, str(exc)

    return None, "all methods failed"


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    """Custom redirect handler that follows up to 5 redirects, then returns the final status."""

    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Follow redirects, log the redirect."""
        log.debug("Redirect %s -> %s (status %s)", req.full_url, newurl, code)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_stale_offers(
    store: TrackerStore,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Check all listings that haven't been checked in CACHE_TTL_SECONDS.

    Args:
        store: TrackerStore instance.
        force: If True, re-check all listings regardless of cache age.

    Returns:
        Summary dict with counts of online/offline/failed checks.
    """
    listings = store.list_active()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    checked = 0
    skipped = 0
    online_count = 0
    offline_count = 0
    failed_count = 0
    results: list[dict] = []

    for listing in listings:
        # Check cache freshness
        cached = store.get_online_status(listing.id)
        if not force and cached is not None:
            try:
                checked_at = datetime.fromisoformat(cached["last_checked_at"])
                # Naive vs aware: SQLite stores naive timestamps
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                age = (now - checked_at).total_seconds()
                if age < CACHE_TTL_SECONDS:
                    skipped += 1
                    if cached["is_online"]:
                        online_count += 1
                    else:
                        offline_count += 1
                    continue
            except (ValueError, TypeError):
                pass  # parse failure = re-check

        # Perform health check
        http_status, error = _check_single_url(listing.url)
        is_online = http_status is not None and 200 <= http_status < 300

        store.update_online_status(
            listing.id,
            is_online=is_online,
            http_status=http_status,
            error_message=error,
        )

        checked += 1
        if is_online:
            online_count += 1
        elif error:
            failed_count += 1
        else:
            offline_count += 1

        results.append({
            "listing_id": listing.id,
            "url": listing.url,
            "is_online": is_online,
            "http_status": http_status,
            "error": error,
        })

    return {
        "checked": checked,
        "skipped": skipped,
        "online": online_count,
        "offline": offline_count,
        "failed": failed_count,
        "total": len(listings),
        "checked_at": now_iso,
        "results": results,
    }


def get_cached_status(store: TrackerStore) -> dict[str, Any]:
    """Return the current cached online status for all listings.

    Does NOT trigger any HTTP checks — only returns what's in the DB.
    """
    listings = store.list_active()
    active_ids = {l.id for l in listings}
    listing_map = {l.id: l for l in listings}
    statuses = store.list_online_statuses(limit=len(listings) + 1)

    offers: list[dict] = []
    for row in statuses:
        lid = row["listing_id"]
        listing = listing_map.get(lid)
        offers.append({
            "listing_id": lid,
            "url": listing.url if listing else None,
            "title": listing.title if listing else None,
            "source": listing.source if listing else None,
            "is_online": bool(row["is_online"]),
            "last_checked_at": row["last_checked_at"],
            "http_status": row["http_status"],
            "error_message": row["error_message"],
        })

    # Add listings with no status record
    known_ids = {r["listing_id"] for r in statuses}
    for lid in active_ids - known_ids:
        listing = listing_map[lid]
        offers.append({
            "listing_id": lid,
            "url": listing.url,
            "title": listing.title,
            "source": listing.source,
            "is_online": True,  # assume online until checked
            "last_checked_at": None,
            "http_status": None,
            "error_message": None,
        })

    # Calculate earliest expiry
    now = datetime.now(timezone.utc)
    min_remaining = CACHE_TTL_SECONDS
    for row in statuses:
        try:
            checked_at = datetime.fromisoformat(row["last_checked_at"])
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=timezone.utc)
            elapsed = (now - checked_at).total_seconds()
            remaining = CACHE_TTL_SECONDS - elapsed
            min_remaining = min(min_remaining, remaining)
        except (ValueError, TypeError):
            pass

    return {
        "offers": offers,
        "total": len(offers),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "cache_remaining_seconds": max(0, round(min_remaining)),
    }
