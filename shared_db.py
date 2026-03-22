import sqlite3
import os
from pathlib import Path
from datetime import datetime

# Configurable DB path: default to shared location, override with env var
DEFAULT_DB_PATH = Path("/home/peralese/Projects/shared_inventory.db")
DB_PATH = Path(os.environ.get("SHARED_INVENTORY_DB", str(DEFAULT_DB_PATH)))

SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
  item_id TEXT PRIMARY KEY,
  sku TEXT,
  title TEXT NOT NULL,
  description TEXT,
  purchase_source TEXT,
  purchase_date TEXT,
  lot_number TEXT,
  purchase_price REAL,
  purchase_fees REAL DEFAULT 0.0,
  total_purchase_cost REAL,
  listing_status TEXT DEFAULT 'purchased' CHECK (listing_status IN ('purchased', 'ready_to_list', 'listed', 'sold', 'closed')),
  list_date TEXT,
  list_price REAL,
  sold_price REAL,
  sold_date TEXT,
  shipping_cost REAL DEFAULT 0.0,
  marketplace_fees REAL DEFAULT 0.0,
  net_profit REAL,
  ebay_item_id TEXT UNIQUE,
  notes TEXT,
  source_file TEXT,
  source_hash TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_purchase_date ON inventory(purchase_date);
CREATE INDEX IF NOT EXISTS idx_listing_status ON inventory(listing_status);
CREATE INDEX IF NOT EXISTS idx_sku ON inventory(sku);
"""

def connect():
    """Connect to the shared inventory DB, creating it and schema if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    # Ensure schema exists
    for stmt in SCHEMA.strip().split(";\n"):
        if stmt.strip():
            conn.execute(stmt)
    return conn

def check_if_exists(item_id: str) -> bool:
    """Check if an item_id exists in the inventory."""
    with connect() as conn:
        cur = conn.execute("SELECT 1 FROM inventory WHERE item_id = ?", (item_id,))
        return cur.fetchone() is not None

def insert_inventory_item(data: dict):
    """Insert a new inventory item. data should be a dict with required fields."""
    data = dict(data)
    now = datetime.now().isoformat(timespec="seconds")
    if "created_at" not in data:
        data["created_at"] = now
    data["updated_at"] = now
    # Calculate total_purchase_cost if not provided
    if "total_purchase_cost" not in data and "purchase_price" in data and "purchase_fees" in data:
        data["total_purchase_cost"] = (data.get("purchase_price", 0) or 0) + (data.get("purchase_fees", 0) or 0)
    # Calculate net_profit if possible
    if "net_profit" not in data and all(k in data for k in ["sold_price", "total_purchase_cost", "shipping_cost", "marketplace_fees"]):
        data["net_profit"] = (data.get("sold_price", 0) or 0) - (data.get("total_purchase_cost", 0) or 0) - (data.get("shipping_cost", 0) or 0) - (data.get("marketplace_fees", 0) or 0)

    cols = list(data.keys())
    vals = [data[c] for c in cols]
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO inventory ({','.join(cols)}) VALUES ({placeholders});"
    with connect() as conn:
        conn.execute(sql, vals)
        conn.commit()

def update_inventory_item(item_id: str, data: dict):
    """Update an existing inventory item by item_id."""
    data = dict(data)
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    # Recalculate if needed
    if "total_purchase_cost" not in data and "purchase_price" in data and "purchase_fees" in data:
        data["total_purchase_cost"] = (data.get("purchase_price", 0) or 0) + (data.get("purchase_fees", 0) or 0)
    if "net_profit" not in data and all(k in data for k in ["sold_price", "total_purchase_cost", "shipping_cost", "marketplace_fees"]):
        data["net_profit"] = (data.get("sold_price", 0) or 0) - (data.get("total_purchase_cost", 0) or 0) - (data.get("shipping_cost", 0) or 0) - (data.get("marketplace_fees", 0) or 0)

    sets = ",".join([f"{k}=?" for k in data.keys()])
    vals = list(data.values()) + [item_id]
    sql = f"UPDATE inventory SET {sets} WHERE item_id=?;"
    with connect() as conn:
        conn.execute(sql, vals)
        conn.commit()

def get_item_by_id(item_id: str) -> dict | None:
    """Retrieve an inventory item by item_id."""
    with connect() as conn:
        cur = conn.execute("SELECT * FROM inventory WHERE item_id = ?", (item_id,))
        row = cur.fetchone()
        if row:
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
    return None