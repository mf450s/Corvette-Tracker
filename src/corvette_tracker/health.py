from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .storage import TrackerStore

log = logging.getLogger(__name__)

# How long cached status results are considered fresh (seconds)
CACHE_TTL_SECONDS = 300

# HTTP request timeout per URL check
CHECK_TIMEOUT = 10

# Minimum delay in seconds between requests to the same domain
DOMAIN_DELAY_SECONDS = 1.0

# Phrases that indicate a listing is no longer available (checked in body text)
NOT_FOUND_PATTERNS: list[re.Pattern] = [
    re.compile(r"anzeige\s+(?:wurde\s+)?(?:leider\s+)?nicht\s+gefunden", re.I),
    re.compile(r"die\s+gesuchte\s+anzeige\s+ist\s+nicht\s+mehr\s+vorhanden", re.I),
    re.compile(r"<title>[^<]*nicht\s+gefunden[^<]*</title>", re.I | re.S),
    re.compile(r"<h1[^>]*>[^<]*nicht\s+gefunden[^<]*</h1>", re.I | re.S),
    re.compile(r"dieses\s+(?:angebot|inserat|objekt)\s+(?:ist\s+)?nicht\s+mehr\s+(?:vorhanden|verfügbar|verfuegbar)", re.I),
    re.compile(r"listing\s+(?:is\s+)?(?:no\s+longer\s+)?not\s+found", re.I),
    re.compile(r"offer\s+(?:is\s+)?(?:no\s+longer\s+)?(?:available|found)", re.I),
    re.compile(r"page\s+not\s+found", re.I),
    re.compile(r"404\s+not\s+found", re.I),
    re.compile(r"dieses\s+objekt\s+wurde\s+entfernt", re.I),
    re.compile(r"this\s+(?:ad|listing)\s+(?:has\s+been\s+)?removed", re.I),
    re.compile(r"gelöscht", re.I),
    re.compile(r"showDeletedVeil\s*:\s*true", re.I),
    re.compile(r"showPausedVeil\s*:\s*true", re.I),
]

# Realistic browser User-Agent to avoid bot blocking/redirects
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that does NOT follow redirects.

    This is intentional for health checks: a deleted Kleinanzeigen listing
    redirects (302 -> homepage -> 200). We catch the initial redirect code
    and report the listing as offline instead of following through.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        log.debug(
            "Redirect detected for %s -> %s (HTTP %s) — not following",
            req.full_url, newurl, code,
        )
        return None  # Don't follow redirects


def _is_not_found_body(body: str) -> bool:
    """Check response body for patterns indicating a listing is gone.

    Some sites return HTTP 200 with a 'not found' message instead of 404.
    """
    for pattern in NOT_FOUND_PATTERNS:
        if pattern.search(body):
            return True
    return False


# Per-domain rate limiting state
_last_request_at: dict[str, float] = {}


def _domain_delay(url: str) -> None:
    """Enforce a minimum delay between requests to the same domain."""
    domain = urlparse(url).netloc
    last = _last_request_at.get(domain)
    if last is not None:
        elapsed = time.time() - last
        if elapsed < DOMAIN_DELAY_SECONDS:
            sleep_time = DOMAIN_DELAY_SECONDS - elapsed
            log.debug("Rate limit: sleeping %.2fs for %s", sleep_time, domain)
            time.sleep(sleep_time)
    _last_request_at[domain] = time.time()


def _check_single_url(url: str) -> tuple[int | None, str | None]:
    """Check whether a single URL is reachable and still points to a listing.

    Tries HEAD first, falls back to GET if the server rejects HEAD.
    Does NOT follow redirects — a redirect (3xx) means the listing is gone.
    Also checks response body for common 'not found' indicators.

    Returns (http_status, error_message).
    - (200, None) on success (listing is online)
    - (status_code, None) on non-2xx, including redirects (listing offline)
    - (None, \"error message\") on connection failure / timeout
    """
    if not url:
        return None, "empty URL"

    _domain_delay(url)

    def _do_request(method: str):
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", BROWSER_USER_AGENT)
        opener = urllib.request.build_opener(_NoRedirectHandler())
        return opener.open(req, timeout=CHECK_TIMEOUT)

    for method in ("HEAD", "GET"):
        try:
            with _do_request(method) as response:
                status = response.status

                # Redirect (3xx) — listing URL no longer points to the listing
                if 300 <= status < 400:
                    log.info(
                        "Listing %s returned HTTP %s (redirect) — marking offline",
                        url, status,
                    )
                    return status, None

                # Non-2xx status — offline
                if status < 200 or status >= 300:
                    return status, None

                # 2xx from HEAD: URL is reachable, but we need GET to
                # check the body for 'not found' content. Fall through.
                if method == "HEAD":
                    continue

                # 2xx from GET: check response body for 'not found' indicators
                raw_body = response.read(262144)  # 256KB max
                try:
                    charset = response.headers.get_content_charset() or "utf-8"
                    body = raw_body.decode(charset, errors="replace")
                except Exception:
                    body = raw_body.decode("utf-8", errors="replace")

                if _is_not_found_body(body):
                    log.info(
                        "Listing %s returned HTTP 200 but body indicates 'not found' — marking offline",
                        url,
                    )
                    return 410, "not found body"  # 410 Gone semantics
                if len(raw_body) >= 262144:
                    log.debug(
                        "Body truncated for %s (>256KB), content check limited",
                        url,
                    )

                return status, None

        except urllib.error.HTTPError as exc:
            # HEAD method rejected (405) -> try GET
            if exc.code == 405 and method == "HEAD":
                continue
            # Other HTTP errors: report the status code
            log.debug("HTTP %s for %s (%s)", exc.code, url, method)
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


def check_stale_offers(
    store: TrackerStore,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Check all listings that haven't been checked in CACHE_TTL_SECONDS.

    Args:
        store: TrackerStore instance.
        force: If True, re-check all listings regardless of cache age.
        dry_run: If True, perform checks but do NOT write results to the DB.

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

        if not dry_run:
            store.update_online_status(
                listing.id,
                is_online=is_online,
                http_status=http_status,
                error_message=error,
            )

        checked += 1
        if is_online:
            online_count += 1
        elif http_status is not None:
            # Got a valid HTTP response that indicates offline (redirect, 4xx,
            # or content-based detection). The error_message is informational,
            # not a network failure.
            offline_count += 1
        else:
            # Connection error, timeout, or other network failure
            failed_count += 1

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
        "dry_run": dry_run,
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
