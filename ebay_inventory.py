import requests
from ebay_auth import get_access_token

BASE = "https://api.ebay.com/sell/inventory/v1"

def _hdrs():
    return {"Authorization": f"Bearer {get_access_token()}", "Content-Type": "application/json", "Accept": "application/json"}

def get_offers_for_sku(sku):
    r = requests.get(f"{BASE}/offer?sku={sku}", headers=_hdrs(), timeout=30)
    r.raise_for_status()
    return r.json().get("offers", [])

# === Minimal adapters so sync.py can run now (no real eBay writes yet) ===
# Looks for local items in either a CSV or SQLite; remote ops are no-ops for now.

from pathlib import Path
import os, csv, sqlite3

# Optional overrides
_EBT_LOCAL_CSV       = os.getenv("EBT_LOCAL_CSV")              # e.g. data\items.csv
_EBT_SQLITE_PATH     = os.getenv("EBT_SQLITE_PATH", "ebay_tracker.db")
_EBT_SQLITE_TABLE    = os.getenv("EBT_SQLITE_TABLE", "listings")
_EBT_SQLITE_ID_COL   = os.getenv("EBT_SQLITE_ID_COLUMN", "id")
_EBT_SQLITE_SKU_COL  = os.getenv("EBT_SQLITE_SKU_COLUMN", "sku")

def _normalize_id(row: dict, idx_fallback: int | None = None):
    # sync.py keys by 'id' or 'sku'; ensure one exists
    rid = row.get("id") or row.get("item_id") or row.get("itemId")
    sku = row.get("sku")
    if rid not in (None, "", "None"):
        row["id"] = str(rid)
    elif sku not in (None, "", "None"):
        row["id"] = str(sku)  # fall back to SKU as id
    elif idx_fallback is not None:
        row["id"] = str(idx_fallback)
    return row

def _load_from_csv(path: Path):
    items = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f), 1):
            items.append(_normalize_id(dict(r), i))
    return items

# --- replace your _table_exists and _select_columns with these ---

def _table_or_view_exists(conn: sqlite3.Connection, name: str) -> bool:
    q = "SELECT 1 FROM sqlite_master WHERE (type='table' OR type='view') AND name=?"
    return conn.execute(q, (name,)).fetchone() is not None

def _select_columns(conn: sqlite3.Connection, name: str):
    # Try PRAGMA first (works for tables and most views)
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
    if not cols:
        # Fallback: probe the schema via a zero-row SELECT
        cur = conn.execute(f"SELECT * FROM {name} LIMIT 0")
        cols = [d[0] for d in (cur.description or [])]

    # Prefer a tidy subset if available; otherwise include everything
    preferred = [
        "id","sku","title","status","list_price","sold_price","ebay_item_id","itemId","item_id",
        # timestamps the --since filter understands:
        "updated_at","modified","last_modified","lastUpdate","last_updated","mtime",
        "modified_at","date_modified","changed_at","created","created_at","listed_at",
        # schema you showed (may feed updated_at in your view)
        "sold_date","list_date",
    ]
    chosen = [c for c in preferred if c in cols] or cols
    return chosen


def _select_columns(conn: sqlite3.Connection, table: str):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    # Prefer these if present; ELSE select all columns
    preferred = [
        "id","sku","title","status","list_price","sold_price","ebay_item_id","itemId","item_id",
        # timestamps used by --since
        "updated_at","modified","last_modified","lastUpdate","last_updated","mtime",
        "modified_at","date_modified","changed_at","created","created_at","listed_at",
        # your schema extras that feed updated_at in the view
        "sold_date","list_date",
    ]
    chosen = [c for c in preferred if c in cols] or cols
    return chosen


def get_local_items():
    """
    Returns iterable[dict] of local items.
    Priority:
      1) CSV if EBT_LOCAL_CSV is set
      2) SQLite (ebay_tracker.db / listings)
      3) empty list
    Ensures each row has an 'id' (falls back to 'sku' or row index).
    """
    # CSV
    if _EBT_LOCAL_CSV:
        p = Path(_EBT_LOCAL_CSV)
        if p.exists():
            return _load_from_csv(p)
        

    # SQLite
    dbp = Path(_EBT_SQLITE_PATH)
    if dbp.exists():
        conn = sqlite3.connect(str(dbp))
        conn.row_factory = sqlite3.Row
        try:
            if not _table_or_view_exists(conn, _EBT_SQLITE_TABLE):
                return []
            cols = _select_columns(conn, _EBT_SQLITE_TABLE)
            rows = conn.execute(f"SELECT {', '.join(cols)} FROM {_EBT_SQLITE_TABLE}").fetchall()
            items = []
            for i, r in enumerate(rows, 1):
                items.append(_normalize_id(dict(r), i))
            return items
        finally:
            conn.close()

    # Nothing found
    return []

def get_remote_items():
    """
    No real remote read until API creds are ready.
    Return empty -> upsert pass treats everything as 'skipped'.
    """
    return []

def upsert_remote_item(local_item: dict, remote_item: dict | None = None):
    """
    Placeholder: don't call eBay yet—just signal 'skipped'.
    When APIs are ready, implement add/update and return 'added'|'updated'|'skipped'.
    """
    return "skipped"

def delete_remote_item(remote_item: dict):
    """Placeholder: never delete on eBay right now."""
    return "skipped"

