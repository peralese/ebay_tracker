"""
Seed the local SQLite database from an eBay CSV export (without opening the UI).

Usage (PowerShell):
  python seed_from_csv.py --csv .\path\to\ebay_export.csv

Options:
  --db           Path to SQLite DB (default: ebay_tracker.db)
  --table        Target table (default: listings)
  --force        Import even if the exact file hash already exists
  --dry-run      Parse and show counts, but do not write to DB
  -v/--verbose   Extra logging

The import normalizes common columns and safely inserts rows using
INSERT OR IGNORE with a unique index on (ebay_item_id, sku).
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path

import pandas as pd


SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sku TEXT,
  title TEXT,
  category TEXT,
  condition TEXT,
  status TEXT DEFAULT 'draft',
  list_date TEXT,
  list_price REAL,
  bin_price REAL,
  sold_price REAL,
  sold_date TEXT,
  buyer_username TEXT,
  order_id TEXT,
  shipping_cost_buyer REAL DEFAULT 0.0,
  shipping_cost_seller REAL DEFAULT 0.0,
  ebay_fees REAL DEFAULT 0.0,
  tax_collected REAL DEFAULT 0.0,
  cost_of_goods REAL DEFAULT 0.0,
  views INTEGER DEFAULT 0,
  watchers INTEGER DEFAULT 0,
  bids INTEGER DEFAULT 0,
  quantity INTEGER DEFAULT 1,
  relist_count INTEGER DEFAULT 0,
  item_url TEXT,
  photo_urls TEXT,
  notes TEXT,
  last_updated TEXT,
  ebay_item_id TEXT
);

CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_hash TEXT UNIQUE,
  file_name TEXT,
  imported_at TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_listings_item_sku
ON listings(ebay_item_id, sku);
"""


def to_number(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def normalize_status(raw):
    if pd.isna(raw):
        return None
    s = str(raw).strip().lower()
    mapping = {
        "active": "listed",
        "listed": "listed",
        "live": "listed",
        "unsold": "archived",
        "ended": "archived",
        "completed": "archived",
        "sold": "sold",
        "return": "returned",
        "returned": "returned",
        "draft": "draft",
    }
    return mapping.get(s, s)


def _pick_ci(df: pd.DataFrame, candidates: list[str]):
    lower = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower:
            return df[lower[c.lower()]]
    return None


def looks_like_active_listings(imp: pd.DataFrame) -> bool:
    cols = set(imp.columns)
    has_qty_cols = ("Sold quantity" in cols or "Quantity Sold" in cols or "Qty Sold" in cols) \
                   or ("Available quantity" in cols or "Quantity Available" in cols or "Quantity" in cols)
    has_status = ("Status" in cols) or ("Listing Status" in cols) or ("Result" in cols)
    return has_qty_cols and not has_status


def map_ebay_export_to_schema(imp: pd.DataFrame) -> pd.DataFrame:
    imp = imp.copy()
    imp.columns = [c.strip() for c in imp.columns]

    colmap = {
        "ebay_item_id": ["Item number", "Item ID", "ItemID", "Item Id"],
        "sku": ["Custom label (SKU)", "Custom label", "Custom Label (SKU)", "SKU"],
        "title": ["Title"],
        "category": ["Category", "Category Name", "Primary Category", "eBay category 1 name"],
        "status": ["Status", "Listing Status", "Result"],
        "list_date": ["Start date", "Start Date", "Start time", "Start Time", "Creation Date"],
        "list_price": ["Current price", "Start price", "Start Price", "Price"],
        "bin_price": ["Auction Buy It Now price", "Buy It Now Price", "Buy It Now price"],
        "views": ["Views", "View Count"],
        "watchers": ["Watchers"],
        "bids": ["Bids"],
        "quantity": ["Available quantity", "Quantity", "Quantity Available", "Quantity Listed"],
        "sold_qty": ["Sold quantity", "Quantity Sold", "Qty Sold"],
        "item_url": ["Item URL", "URL", "View Item URL", "Item URL link"],
        "sold_price": ["Sold Price", "Sold For", "Total price", "Total Price", "Price (total)"],
        "sold_date": ["Sale Date", "Paid On", "Order Date", "End Date", "End date", "End time", "End Time"],
        "buyer_username": ["Buyer User ID", "Buyer Username", "Buyer ID", "Buyer"],
        "order_id": ["Order ID", "Sales Record Number", "Sales Record #", "Record number", "Order id"],
        "shipping_cost_buyer": ["Shipping And Handling", "Shipping charged to buyer", "Postage and packaging - paid by buyer", "Shipping paid by buyer"],
        "notes": ["Notes", "Private notes"],
        "condition": ["Condition"],
    }

    data = {}
    for our, cands in colmap.items():
        v = _pick_ci(imp, cands)
        if v is not None:
            data[our] = v

    df = pd.DataFrame(data)

    for c in ["list_price", "bin_price", "sold_price", "shipping_cost_buyer", "sold_qty"]:
        if c in df.columns:
            df[c] = to_number(df[c]).fillna(0)

    for c in ["views", "watchers", "bids", "quantity"]:
        if c in df.columns:
            df[c] = to_number(df[c]).fillna(0).astype("Int64")

    if "list_date" in df.columns:
        df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce").dt.date.astype("string")

    if "sold_date" in df.columns:
        df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce").dt.date.astype("string")

    if looks_like_active_listings(imp):
        df["status"] = "listed"
    else:
        if "status" in df.columns:
            df["status"] = df["status"].map(normalize_status)
        else:
            sold_markers = []
            if "sold_price" in df.columns:
                sold_markers.append(df["sold_price"].fillna(0) > 0)
            if "sold_date" in df.columns:
                sold_markers.append(df["sold_date"].notna())
            any_sold = pd.concat(sold_markers, axis=1).any(axis=1) if sold_markers else pd.Series(False, index=df.index)
            df.loc[any_sold, "status"] = "sold"
            df.loc[~any_sold, "status"] = "listed"

    expected = [
        "sku","title","category","condition","status","list_date","list_price","bin_price",
        "sold_price","sold_date","buyer_username","order_id","shipping_cost_buyer",
        "shipping_cost_seller","ebay_fees","tax_collected","cost_of_goods","views",
        "watchers","bids","quantity","relist_count","item_url","photo_urls","notes",
        "last_updated","ebay_item_id"
    ]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA

    for c in ["shipping_cost_seller","ebay_fees","tax_collected","cost_of_goods","relist_count"]:
        df[c] = to_number(df[c]).fillna(0)

    return df[expected]


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_schema(conn: sqlite3.Connection):
    for stmt in SCHEMA.strip().split(";\n"):
        if stmt.strip():
            conn.execute(stmt)
    conn.commit()


def insert_rows(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    cols = [c for c in df.columns if c != "id"]
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({placeholders});"
    values = df[cols].where(pd.notna(df[cols]), None).values.tolist()
    cur = conn.executemany(sql, values)
    conn.commit()
    return cur.rowcount if cur is not None else 0


def main():
    ap = argparse.ArgumentParser(description="Seed SQLite from an eBay CSV export")
    ap.add_argument("--csv", required=True, help="Path to eBay CSV export")
    ap.add_argument("--db", default="ebay_tracker.db", help="Path to SQLite DB")
    ap.add_argument("--table", default="listings", help="Target table name")
    ap.add_argument("--force", action="store_true", help="Force import even if this file hash was already imported")
    ap.add_argument("--dry-run", action="store_true", help="Parse and show summary without writing to DB")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    # Read CSV
    imp = pd.read_csv(csv_path)
    df_norm = map_ebay_export_to_schema(imp)

    if args.dry_run:
        print(f"Dry-run: would import {len(df_norm)} rows into {args.table} in {args.db}")
        return 0

    # Prepare DB
    conn = sqlite3.connect(args.db)
    try:
        ensure_schema(conn)

        # Duplicate detection via imports table
        file_hash = md5_file(csv_path)
        if not args.force:
            exists = conn.execute("SELECT 1 FROM imports WHERE file_hash=?", (file_hash,)).fetchone()
            if exists:
                print("This exact file was already imported. Skipping. ✅")
                return 0

        # Ensure key columns exist
        if "ebay_item_id" not in df_norm.columns:
            df_norm["ebay_item_id"] = pd.NA
        if "sku" not in df_norm.columns:
            df_norm["sku"] = pd.NA
        df_norm["sku"] = df_norm["sku"].fillna("")

        inserted = insert_rows(conn, args.table, df_norm)
        conn.execute(
            "INSERT OR IGNORE INTO imports(file_hash, file_name) VALUES (?,?)",
            (file_hash, csv_path.name),
        )
        conn.commit()
        print(f"Imported {inserted} rows into {args.table}. ✅")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

