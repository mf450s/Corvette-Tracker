from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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
"""


class TrackerStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_listings(self, listings: list[Listing]) -> list[Listing]:
        result: list[Listing] = []
        for listing in listings:
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

    def list_active(self) -> list[Listing]:
        rows = self.conn.execute("SELECT payload_json FROM listings ORDER BY COALESCE(price_eur, 999999999), id").fetchall()
        return [Listing(**json.loads(row["payload_json"])) for row in rows]
