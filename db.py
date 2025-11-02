# db.py
import sqlite3, json, datetime as dt
from pathlib import Path

DB_PATH = Path("ebay_tracker.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
  offer_id TEXT PRIMARY KEY,
  sku TEXT,
  listing_id TEXT,
  marketplace_id TEXT,
  format TEXT,
  listing_status TEXT,
  available_quantity INTEGER,
  sold_quantity INTEGER,
  price_value REAL,
  price_currency TEXT,
  last_seen_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_offers_sku ON offers(sku);

CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT,
  ended_at TEXT,
  source TEXT,
  items_seen INTEGER,
  offers_seen INTEGER,
  notes TEXT
);
"""

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    # Ensure tables exist
    for stmt in SCHEMA.strip().split(";\n"):
        if stmt.strip():
            conn.execute(stmt)
    return conn

def begin_sync_run(source: str):
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO sync_runs(started_at, source, items_seen, offers_seen) VALUES(?,?,0,0)",
            (dt.datetime.now().isoformat(timespec="seconds"), source),
        )
        conn.commit()
        return cur.lastrowid

def end_sync_run(run_id: int, *, items_seen: int, offers_seen: int, notes: str | None = None):
    with _conn() as conn:
        conn.execute(
            "UPDATE sync_runs SET ended_at=?, items_seen=?, offers_seen=?, notes=? WHERE id=?",
            (dt.datetime.now().isoformat(timespec="seconds"), items_seen, offers_seen, notes, run_id),
        )
        conn.commit()

def upsert_offer_from_api(sku: str, off: dict):
    # Normalize a few common fields from Inventory API getOffers()
    offer_id = off.get("offerId")
    listing_id = off.get("listingId")
    marketplace_id = off.get("marketplaceId")
    listing_status = off.get("listingStatus")
    fmt = off.get("format")
    avail_qty = off.get("availableQuantity")
    sold_qty = off.get("soldQuantity")
    price = (off.get("pricingSummary") or {}).get("price") or {}
    price_value = price.get("value")
    price_currency = price.get("currency")
    now = dt.datetime.now().isoformat(timespec="seconds")

    with _conn() as conn:
        conn.execute("""
            INSERT INTO offers(offer_id, sku, listing_id, marketplace_id, format, listing_status,
                               available_quantity, sold_quantity, price_value, price_currency, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(offer_id) DO UPDATE SET
              sku=excluded.sku,
              listing_id=excluded.listing_id,
              marketplace_id=excluded.marketplace_id,
              format=excluded.format,
              listing_status=excluded.listing_status,
              available_quantity=excluded.available_quantity,
              sold_quantity=excluded.sold_quantity,
              price_value=excluded.price_value,
              price_currency=excluded.price_currency,
              last_seen_at=excluded.last_seen_at
        """, (
            offer_id, sku, listing_id, marketplace_id, fmt, listing_status,
            avail_qty, sold_qty, price_value, price_currency, now
        ))
        conn.commit()
