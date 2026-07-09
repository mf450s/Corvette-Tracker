from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
from pathlib import Path
from typing import Any

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  price_eur INTEGER,
  mileage_km INTEGER,
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
"""

LISTING_FIELDS = {field.name for field in fields(Listing)}
PROTECTED_OVERRIDE_FIELDS = {"id", "source", "source_listing_id", "url", "change_type", "previous_price_eur", "cluster_id"}
EDITABLE_FIELDS = LISTING_FIELDS - PROTECTED_OVERRIDE_FIELDS


class TrackerStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
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
        result: list[Listing] = []
        for source_listing in listings:
            listing = self._apply_overrides(source_listing)
            previous = self.conn.execute("SELECT payload_json, price_eur, mileage_km FROM listings WHERE id = ?", (listing.id,)).fetchone()
            if previous is None:
                listing.change_type = "new"
            elif previous["price_eur"] != listing.price_eur:
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
        self.conn.commit()
        return result

    def get_listing(self, listing_id: str) -> Listing | None:
        row = self.conn.execute("SELECT payload_json FROM listings WHERE id = ?", (listing_id,)).fetchone()
        if row is None:
            return None
        return Listing(**json.loads(row["payload_json"]))

    def list_active(self) -> list[Listing]:
        rows = self.conn.execute("SELECT payload_json FROM listings ORDER BY COALESCE(price_eur, 999999999), id").fetchall()
        return [Listing(**json.loads(row["payload_json"])) for row in rows]

    def listing_history(self, listing_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT captured_at, price_eur, mileage_km, change_type, payload_json
            FROM snapshots
            WHERE listing_id = ?
            ORDER BY captured_at DESC, id DESC
            LIMIT ?
            """,
            (listing_id, limit),
        ).fetchall()
        return [
            {
                "captured_at": row["captured_at"],
                "price_eur": row["price_eur"],
                "mileage_km": row["mileage_km"],
                "change_type": row["change_type"],
                "listing": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

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
