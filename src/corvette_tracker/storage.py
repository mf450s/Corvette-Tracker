from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import fields
from pathlib import Path
from typing import Any

from .enums import TrimType
from .models import Listing
from .validation import sanity_check_against_previous

# Type alias for a filter dict: key → string value from query params
FilterParams = dict[str, str]


def filter_listings(listings: list[Listing], filters: FilterParams) -> list[Listing]:
    """Apply filter parameters to a list of listings. All filters are AND-combined.

    Supported filter keys match the query-parameter names used in the API:
      source, transmission, trim, engine, body_style       — exact match (categorical)
      price_min, price_max, mileage_min, mileage_max        — numeric range (inclusive)
      change_type                                           — exact match
      risk_free                                             — 'true'/'1' hides listings with risk_flags
      score_min                                             — minimum score (inclusive)
      ez_min, ez_max                                        — year range on first_registration (YYYY)
      accident_status                                       — exact match
      tuv_min                                               — year range on tuv_until
      eu_spec                                               — 'true'/'false' exact match on bool

    Any unknown or empty filter keys are silently ignored.
    """
    result = list(listings)

    for key, value in filters.items():
        if not value or not isinstance(value, str):
            continue
        v = value.strip()
        if not v:
            continue

        if key == "source":
            result = [l for l in result if l.source == v]

        elif key == "transmission":
            result = [l for l in result if l.transmission == v]

        elif key == "trim":
            result = [l for l in result if l.trim == v]

        elif key == "engine":
            # Check both engine and probable_engine
            vl = v.lower()
            result = [
                l for l in result
                if (l.engine or "").lower() == vl or (l.probable_engine or "").lower() == vl
            ]

        elif key == "body_style":
            result = [l for l in result if l.body_style == v]

        elif key == "price_min":
            try:
                min_val = int(v)
            except ValueError:
                continue
            result = [l for l in result if l.price_eur is not None and l.price_eur >= min_val]

        elif key == "price_max":
            try:
                max_val = int(v)
            except ValueError:
                continue
            result = [l for l in result if l.price_eur is not None and l.price_eur <= max_val]

        elif key == "mileage_min":
            try:
                min_val = int(v)
            except ValueError:
                continue
            result = [l for l in result if l.mileage_km is not None and l.mileage_km >= min_val]

        elif key == "mileage_max":
            try:
                max_val = int(v)
            except ValueError:
                continue
            result = [l for l in result if l.mileage_km is not None and l.mileage_km <= max_val]

        elif key == "change_type":
            result = [l for l in result if l.change_type == v]

        elif key == "risk_free":
            if v in ("true", "1"):
                result = [l for l in result if not l.risk_flags]

        elif key == "score_min":
            try:
                min_val = int(v)
            except ValueError:
                continue
            result = [l for l in result if l.score is not None and l.score >= min_val]

        elif key == "ez_min":
            # Year prefix on first_registration (e.g. "2005-01" → "2005")
            result = [
                l for l in result
                if l.first_registration and l.first_registration[:4] >= v
            ]

        elif key == "ez_max":
            result = [
                l for l in result
                if l.first_registration and l.first_registration[:4] <= v
            ]

        elif key == "accident_status":
            result = [l for l in result if l.accident_status == v]

        elif key == "tuv_min":
            result = [
                l for l in result
                if l.tuv_until and l.tuv_until[:4] >= v
            ]

        elif key == "eu_spec":
            if v == "true":
                result = [l for l in result if l.eu_spec is True]
            elif v == "false":
                result = [l for l in result if l.eu_spec is False]

        # Unknown keys are silently ignored (forward-compatible)

    return result

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  price_eur INTEGER,
  mileage_km INTEGER,
  hidden INTEGER NOT NULL DEFAULT 0,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id TEXT NOT NULL,
  captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  price_eur INTEGER,
  mileage_km INTEGER,
  change_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS manual_overrides (
  listing_id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS offer_online_status (
  listing_id TEXT PRIMARY KEY,
  is_online INTEGER NOT NULL DEFAULT 1,
  last_checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  http_status INTEGER,
  error_message TEXT,
  FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS online_status_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id TEXT NOT NULL,
  captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  is_online INTEGER NOT NULL,
  http_status INTEGER,
  error_message TEXT,
  FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE CASCADE
);
"""

LISTING_FIELDS = {field.name for field in fields(Listing)}
PROTECTED_OVERRIDE_FIELDS = {"id", "source", "source_listing_id", "url", "change_type", "previous_price_eur", "cluster_id"}
EDITABLE_FIELDS = LISTING_FIELDS - PROTECTED_OVERRIDE_FIELDS

# Columns added to SCHEMA after the table first shipped. CREATE TABLE IF NOT
# EXISTS only creates missing tables — it never adds columns to existing ones,
# so databases created earlier must be migrated here or upserts break with
# "no such column".
REQUIRED_COLUMNS: dict[str, dict[str, str]] = {
    "listings": {
        "hidden": "INTEGER NOT NULL DEFAULT 0",
    },
}

log = logging.getLogger(__name__)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns that are missing from pre-existing tables."""
    for table, columns in REQUIRED_COLUMNS.items():
        existing = {
            row[1] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        for column, definition in columns.items():
            if column not in existing:
                log.info("Migrating %s: adding column %s", table, column)
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
    conn.commit()


class TrackerStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        _migrate_schema(self.conn)
        self.conn.commit()

    def _overrides_for(self, listing_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT payload_json FROM manual_overrides WHERE listing_id = ?", (listing_id,)).fetchone()
        return dict(json.loads(row["payload_json"])) if row else {}

    def _apply_overrides(self, listing: Listing) -> Listing:
        overrides = self._overrides_for(listing.id)
        if not overrides:
            return listing
        data = listing.to_dict()
        data.update(overrides)
        return Listing(**data)

    def upsert_listings(self, listings: list[Listing]) -> list[Listing]:
        # Pre-load all existing listings for historical comparison
        try:
            existing = self.list_active()
        except Exception:
            existing = []

        result: list[Listing] = []
        failed: list[tuple[str, str]] = []
        for source_listing in listings:
            try:
                listing = self._apply_overrides(source_listing)

                # Historical outlier check against existing data
                historical_flags = sanity_check_against_previous(listing, existing)
                if historical_flags:
                    listing.validation_flags = [
                        *listing.validation_flags,
                        *historical_flags,
                    ]

                previous = self.conn.execute(
                    "SELECT payload_json, price_eur, mileage_km, hidden FROM listings WHERE id = ?",
                    (listing.id,),
                ).fetchone()
                if previous is None:
                    listing.change_type = "new"
                else:
                    # Preserve hidden status across re-scrapes
                    if previous["hidden"]:
                        listing.hidden = True
                    # Sticky manual cluster assignment: only protect user merges (manual_*).
                    # Automatic cluster ids (soft_*/vin_*/singleton_*) may be re-adopted by
                    # assign_clusters() on re-listing.
                    prev_payload = json.loads(previous["payload_json"])
                    stored_cluster = prev_payload.get("cluster_id")
                    if stored_cluster and stored_cluster.startswith("manual_"):
                        listing.cluster_id = stored_cluster
                    if previous["price_eur"] != listing.price_eur:
                        listing.change_type = "price_change"
                        listing.previous_price_eur = previous["price_eur"]
                    elif previous["mileage_km"] != listing.mileage_km:
                        listing.change_type = "metadata_change"
                    else:
                        listing.change_type = "unchanged"

                payload = json.dumps(listing.to_dict(), ensure_ascii=False, sort_keys=True)
                self.conn.execute(
                    """
                    INSERT INTO listings (id, payload_json, price_eur, mileage_km, last_seen_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                      payload_json=excluded.payload_json,
                      price_eur=excluded.price_eur,
                      mileage_km=excluded.mileage_km,
                      last_seen_at=CURRENT_TIMESTAMP
                    """,
                    (listing.id, payload, listing.price_eur, listing.mileage_km),
                )
                self.conn.execute(
                    "INSERT INTO snapshots (listing_id, price_eur, mileage_km, change_type, payload_json) VALUES (?, ?, ?, ?, ?)",
                    (listing.id, listing.price_eur, listing.mileage_km, listing.change_type, payload),
                )
                result.append(listing)
            except Exception as exc:
                url = getattr(source_listing, "url", "?")
                failed.append((url, str(exc)))
                log.warning("listing %s failed to store: %s", url, exc)
        self.conn.commit()

        if failed:
            log.error(
                "upsert: %d/%d listings failed. First %d errors: %s",
                len(failed),
                len(listings),
                min(3, len(failed)),
                "; ".join(f"{url}: {msg}" for url, msg in failed[:3]),
            )
        return result

    def get_listing(self, listing_id: str) -> Listing | None:
        row = self.conn.execute("SELECT payload_json FROM listings WHERE id = ?", (listing_id,)).fetchone()
        if row is None:
            return None
        return self._deserialize_listing(row["payload_json"])

    @staticmethod
    def _deserialize_listing(payload: str) -> Listing:
        """Deserialize a listing from JSON, normalizing None list/dict fields."""
        data = json.loads(payload)
        # Ensure list/dict fields that were stored as null become empty defaults
        if data.get("risk_flags") is None:
            data["risk_flags"] = []
        if data.get("equipment") is None:
            data["equipment"] = []
        if data.get("image_urls") is None:
            data["image_urls"] = []
        if data.get("visual_flags") is None:
            data["visual_flags"] = []
        if data.get("inference_notes") is None:
            data["inference_notes"] = []
        if data.get("conflict_flags") is None:
            data["conflict_flags"] = []
        if data.get("validation_flags") is None:
            data["validation_flags"] = []
        if data.get("ai_enrichment") is None:
            data["ai_enrichment"] = {}
        if data.get("trim") is not None:
            try:
                data["trim"] = TrimType(data["trim"])
            except ValueError:
                data["trim"] = None
        return Listing(**data)

    def list_active(self) -> list[Listing]:
        rows = self.conn.execute("SELECT payload_json FROM listings ORDER BY COALESCE(price_eur, 999999999), id").fetchall()
        return [self._deserialize_listing(row["payload_json"]) for row in rows]

    def created_at_map(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT id, created_at FROM listings").fetchall()
        return {row["id"]: row["created_at"] for row in rows}

    def listing_history(self, listing_id: str, limit: int = 500) -> dict[str, Any]:
        # Fetch all snapshots ordered by captured_at ascending regardless of limit for
        # series and summary computations.
        all_rows = self.conn.execute(
            """
            SELECT captured_at, price_eur, mileage_km, change_type, payload_json
            FROM snapshots
            WHERE listing_id = ?
            ORDER BY captured_at ASC, id ASC
            """,
            (listing_id,),
        ).fetchall()

        if not all_rows:
            return {
                "history": [],
                "series": [],
                "summary": {
                    "first_seen_at": None,
                    "last_seen_at": None,
                    "price_changes": 0,
                    "metadata_changes": 0,
                    "manual_overrides": 0,
                    "first_price_eur": None,
                    "current_price_eur": None,
                    "price_min_eur": None,
                    "price_max_eur": None,
                    "snapshot_count": 0,
                },
            }

        # Build chronological history entries
        entries: list[dict[str, Any]] = []
        i = 0
        n = len(all_rows)
        while i < n:
            row = all_rows[i]
            ct = row["change_type"]
            if ct == "unchanged":
                # start a consecutive run of unchanged snapshots
                start_row = row
                first_captured = row["captured_at"]
                last_captured = row["captured_at"]
                first_price = row["price_eur"]
                first_mileage = row["mileage_km"]
                count = 1
                j = i + 1
                while j < n and all_rows[j]["change_type"] == "unchanged":
                    last_captured = all_rows[j]["captured_at"]
                    count += 1
                    j += 1
                entry = {
                    "captured_at": first_captured,
                    "until_at": last_captured,
                    "change_type": "unchanged",
                    "price_eur": first_price,
                    "mileage_km": first_mileage,
                    "is_collapsed": count > 1,
                    "count": count,
                }
                entries.append(entry)
                i = j
            else:
                # non-unchanged snapshot
                entry = {
                    "captured_at": row["captured_at"],
                    "price_eur": row["price_eur"],
                    "mileage_km": row["mileage_km"],
                    "change_type": ct,
                    "listing": json.loads(row["payload_json"]),
                }
                entries.append(entry)
                i += 1

        # Cap history to last `limit` entries (most recent)
        if len(entries) > limit:
            entries = entries[-limit:]

        # Series: emit {captured_at, price_eur} for snapshots with price, dedupe consecutive
        series: list[dict[str, Any]] = []
        prev_price = None
        max_points = 200
        for row in all_rows:
            price = row["price_eur"]
            if price is None:
                continue
            if price != prev_price:
                series.append({"captured_at": row["captured_at"], "price_eur": price})
                prev_price = price
                if len(series) >= max_points:
                    break
        if len(series) < 2:
            series = []

        # Summary computations
        first_seen_at = all_rows[0]["captured_at"]
        last_seen_at = all_rows[-1]["captured_at"]
        price_changes = sum(1 for r in all_rows if r["change_type"] == "price_change")
        metadata_changes = sum(1 for r in all_rows if r["change_type"] == "metadata_change")
        manual_overrides = sum(1 for r in all_rows if r["change_type"] == "manual_override")

        priced = [r for r in all_rows if r["price_eur"] is not None]
        if priced:
            first_price_eur = priced[0]["price_eur"]
            current_price_eur = priced[-1]["price_eur"]
            price_min_eur = min(r["price_eur"] for r in priced)
            price_max_eur = max(r["price_eur"] for r in priced)
        else:
            first_price_eur = None
            current_price_eur = None
            price_min_eur = None
            price_max_eur = None

        summary = {
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
            "price_changes": price_changes,
            "metadata_changes": metadata_changes,
            "manual_overrides": manual_overrides,
            "first_price_eur": first_price_eur,
            "current_price_eur": current_price_eur,
            "price_min_eur": price_min_eur,
            "price_max_eur": price_max_eur,
            "snapshot_count": n,
        }

        return {
            "history": entries,
            "series": series,
            "summary": summary,
        }

    def update_overrides(self, listing_id: str, updates: dict[str, Any]) -> Listing:
        current = self.get_listing(listing_id)
        if current is None:
            raise KeyError(listing_id)
        unknown = sorted(set(updates) - EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"Unsupported override fields: {', '.join(unknown)}")

        overrides = self._overrides_for(listing_id)
        for key, value in updates.items():
            if value == "":
                value = None
            overrides[key] = value
        override_payload = json.dumps(overrides, ensure_ascii=False, sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO manual_overrides (listing_id, payload_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(listing_id) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=CURRENT_TIMESTAMP
            """,
            (listing_id, override_payload),
        )

        data = current.to_dict()
        data.update(overrides)
        updated = Listing(**data)
        payload = json.dumps(updated.to_dict(), ensure_ascii=False, sort_keys=True)
        self.conn.execute(
            "UPDATE listings SET payload_json = ?, price_eur = ?, mileage_km = ? WHERE id = ?",
            (payload, updated.price_eur, updated.mileage_km, listing_id),
        )
        self.conn.execute(
            "INSERT INTO snapshots (listing_id, price_eur, mileage_km, change_type, payload_json) VALUES (?, ?, ?, ?, ?)",
            (listing_id, updated.price_eur, updated.mileage_km, "manual_override", payload),
        )
        self.conn.commit()
        return updated

    def hide_listing(self, listing_id: str) -> None:
        """Mark a listing as hidden (excluded from default exports)."""
        self.conn.execute(
            "UPDATE listings SET hidden = 1 WHERE id = ?",
            (listing_id,),
        )
        # Also update payload_json for round-trip consistency
        listing = self.get_listing(listing_id)
        if listing:
            listing.hidden = True
            payload = json.dumps(listing.to_dict(), ensure_ascii=False, sort_keys=True)
            self.conn.execute(
                "UPDATE listings SET payload_json = ? WHERE id = ?",
                (payload, listing_id),
            )
        self.conn.commit()

    def unhide_listing(self, listing_id: str) -> None:
        """Unmark a hidden listing (restored to default visibility)."""
        self.conn.execute(
            "UPDATE listings SET hidden = 0 WHERE id = ?",
            (listing_id,),
        )
        listing = self.get_listing(listing_id)
        if listing:
            listing.hidden = False
            payload = json.dumps(listing.to_dict(), ensure_ascii=False, sort_keys=True)
            self.conn.execute(
                "UPDATE listings SET payload_json = ? WHERE id = ?",
                (payload, listing_id),
            )
        self.conn.commit()

    def update_online_status(
        self,
        listing_id: str,
        is_online: bool,
        http_status: int | None = None,
        error_message: str | None = None,
    ) -> dict:
        """Upsert the online status for a listing.

        Returns the current row as dict: {listing_id, is_online, last_checked_at, http_status, error_message}
        """
        current = self.get_online_status(listing_id)
        new_online = int(is_online)
        should_log_transition = (current is None) or (current["is_online"] != new_online)

        self.conn.execute(
            """INSERT INTO offer_online_status (listing_id, is_online, http_status, error_message, last_checked_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(listing_id) DO UPDATE SET
                 is_online=excluded.is_online,
                 http_status=excluded.http_status,
                 error_message=excluded.error_message,
                 last_checked_at=CURRENT_TIMESTAMP""",
            (listing_id, new_online, http_status, error_message),
        )
        self.conn.commit()
        if should_log_transition:
            self.conn.execute(
                """INSERT INTO online_status_history (listing_id, is_online, http_status, error_message)
                   VALUES (?, ?, ?, ?)""",
                (listing_id, new_online, http_status, error_message),
            )
            self.conn.commit()
        row = self.conn.execute(
            "SELECT listing_id, is_online, last_checked_at, http_status, error_message FROM offer_online_status WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
        return dict(row)

    def online_status_history(self, listing_id: str) -> list[dict[str, Any]]:
        """Chronological ASC list of status transitions: {captured_at, is_online, http_status}"""
        rows = self.conn.execute(
            """SELECT captured_at, is_online, http_status
               FROM online_status_history
               WHERE listing_id = ?
               ORDER BY captured_at ASC, id ASC""",
            (listing_id,),
        ).fetchall()
        return [
            {
                "captured_at": row["captured_at"],
                "is_online": row["is_online"],
                "http_status": row["http_status"],
            }
            for row in rows
        ]

    def get_online_status(self, listing_id: str) -> dict | None:
        """Get current online status for a listing, or None if never checked."""
        row = self.conn.execute(
            "SELECT listing_id, is_online, last_checked_at, http_status, error_message FROM offer_online_status WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
        return dict(row) if row else None

    def update_listing_url(self, listing_id: str, new_url: str) -> bool:
        """Adopt a new canonical URL for an existing listing.

        The URL lives inside ``payload_json`` (there is no dedicated column),
        so only the payload row is rewritten.  The listing id — derived from
        the stable source identifier — stays unchanged.

        Returns True when a change was applied, False when the listing is
        missing or the URL already matches.
        """
        listing = self.get_listing(listing_id)
        if listing is None or listing.url == new_url:
            return False
        listing.url = new_url
        payload = json.dumps(listing.to_dict(), ensure_ascii=False, sort_keys=True)
        self.conn.execute(
            "UPDATE listings SET payload_json = ? WHERE id = ?",
            (payload, listing_id),
        )
        self.conn.commit()
        return True

    def merge_listings(self, listing_ids: list[str]) -> dict:
        """Manually merge two or more listings into the same cluster.

        Assigns the same manual_* cluster_id to all provided listings.
        Does not create snapshots or alter offer data beyond cluster grouping.
        """
        missing = [lid for lid in listing_ids if self.get_listing(lid) is None]
        if missing:
            raise KeyError(f"Unknown listings: {', '.join(missing)}")

        group_id = "manual_" + uuid.uuid4().hex[:12]
        updated_listings: list[Listing] = []
        for lid in listing_ids:
            listing = self.get_listing(lid)
            listing.cluster_id = group_id
            payload = json.dumps(listing.to_dict(), ensure_ascii=False, sort_keys=True)
            self.conn.execute(
                "UPDATE listings SET payload_json = ? WHERE id = ?",
                (payload, lid),
            )
            updated_listings.append(listing)
        self.conn.commit()
        return {
            "group_id": group_id,
            "listing_ids": listing_ids,
            "listings": [l.to_dict() for l in updated_listings],
        }

    def unmerge_listing(self, listing_id: str) -> Listing:
        """Remove a listing from its manual/automatic cluster group."""
        listing = self.get_listing(listing_id)
        if listing is None:
            raise KeyError(f"Unknown listing: {listing_id}")
        listing.cluster_id = None
        payload = json.dumps(listing.to_dict(), ensure_ascii=False, sort_keys=True)
        self.conn.execute(
            "UPDATE listings SET payload_json = ? WHERE id = ?",
            (payload, listing_id),
        )
        self.conn.commit()
        return listing

    def list_online_statuses(
        self,
        *,
        is_online: bool | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List online statuses, optionally filtered by online/offline flag."""
        if is_online is not None:
            rows = self.conn.execute(
                "SELECT listing_id, is_online, last_checked_at, http_status, error_message FROM offer_online_status WHERE is_online = ? ORDER BY last_checked_at DESC LIMIT ?",
                (int(is_online), limit),
            )
        else:
            rows = self.conn.execute(
                "SELECT listing_id, is_online, last_checked_at, http_status, error_message FROM offer_online_status ORDER BY last_checked_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in rows]
