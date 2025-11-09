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
import os, csv, sqlite3, io, re

# Optional overrides
_EBT_LOCAL_CSV       = os.getenv("EBT_LOCAL_CSV")              # e.g. data\items.csv
_EBT_SQLITE_PATH     = os.getenv("EBT_SQLITE_PATH", "ebay_tracker.db")
_EBT_SQLITE_TABLE    = os.getenv("EBT_SQLITE_TABLE", "listings")
_EBT_SQLITE_ID_COL   = os.getenv("EBT_SQLITE_ID_COLUMN", "id")
_EBT_SQLITE_SKU_COL  = os.getenv("EBT_SQLITE_SKU_COLUMN", "sku")

def _normalize_id(row: dict, idx_fallback: int | None = None):
    # sync.py keys by 'id' or 'sku'; ensure one exists
    rid = row.get("id") or row.get("ebay_item_id") or row.get("item_id") or row.get("itemId")
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
    Return iterable[dict] for current eBay items.
    Offline-safe: if auth is disabled or creds are missing, return [].
    When online, uses Feed API ACTIVE_INVENTORY_REPORT for broad coverage.
    """
    # Offline / auth-disabled short-circuit
    if os.getenv("EBT_DISABLE_AUTH"):
        return []

    # Basic cred check (mirror sync.py tolerance for placeholders)
    cid = os.getenv("EBAY_CLIENT_ID") or os.getenv("EBAY_APP_ID")
    csec = os.getenv("EBAY_CLIENT_SECRET") or os.getenv("EBAY_CERT_ID")
    rtok = os.getenv("EBAY_REFRESH_TOKEN")
    def _looks_real(v: str | None) -> bool:
        if not v:
            return False
        up = v.strip().upper()
        return not (up.startswith("YOUR_") or up.startswith("PLACEHOLDER") or up.startswith("XXX"))
    if not (_looks_real(cid) and _looks_real(csec) and _looks_real(rtok)):
        return []

    # Defer import to avoid pulling requests/auth when offline
    import ebay_feed

    # Request + wait + download
    task_id = ebay_feed.request_active_inventory_report()
    meta = ebay_feed.wait_for_task(task_id)
    # Result URL key can vary; handle common cases
    url = (
        (meta.get("resultFileUrl") or
         (meta.get("resultFileUrls") or [None])[0])
    )
    if not url:
        raise RuntimeError("Feed task missing result file URL")
    text = ebay_feed.download_report(url)

    # Parse CSV/TSV into dicts with stable keys
    def _pick(row: dict, candidates: list[str]):
        keys = {k.lower(): k for k in row.keys()}
        for c in candidates:
            if c.lower() in keys:
                return row.get(keys[c.lower()])
        return None

    def _to_int(v):
        if v is None:
            return None
        s = str(v).replace(",", "").strip()
        return int(s) if re.fullmatch(r"[-+]?\d+", s or "") else None

    def _to_float(v):
        if v is None:
            return None
        s = str(v).replace(",", "").strip()
        s = re.sub(r"[^0-9.+-]", "", s)
        try:
            return float(s)
        except Exception:
            return None

    sample = text[: min(len(text), 8192)]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except Exception:
        class _D(csv.Dialect):
            delimiter = ","; quotechar = '"'; escapechar = None; doublequote = True; skipinitialspace = False; lineterminator = "\n"; quoting = csv.QUOTE_MINIMAL
        dialect = _D

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    items: list[dict] = []
    for r in reader:
        r = { (k or "").strip(): (v if v != "" else None) for k, v in r.items() }
        sku = _pick(r, ["SKU","Custom label","Custom Label","Sku","sku"])
        item_id = _pick(r, ["Item ID","ItemId","item_id","ebay_item_id"]) or None
        title = _pick(r, ["Title","Item title","title"]) or None
        status = _pick(r, ["Status","Listing Status","Result"]) or None
        price = _pick(r, ["Price","Current price","BIN price","Buy It Now price"]) or None
        sold_q = _pick(r, ["Sold quantity","Quantity Sold","Qty Sold"]) or None
        avail_q = _pick(r, ["Available quantity","Quantity Available","Quantity"]) or None

        obj = {}
        if item_id not in (None, ""):
            obj["id"] = str(item_id)
            obj["ebay_item_id"] = str(item_id)
        elif sku not in (None, ""):
            obj["id"] = str(sku)
        if sku not in (None, ""):
            obj["sku"] = str(sku)
        if title is not None:
            obj["title"] = title
        if status is not None:
            obj["status"] = status
        if price is not None:
            obj["list_price"] = _to_float(price)
        if sold_q is not None:
            obj["sold_quantity"] = _to_int(sold_q)
        if avail_q is not None:
            obj["available_quantity"] = _to_int(avail_q)

        if obj:
            items.append(obj)

    return items

def upsert_remote_item(local_item: dict, remote_item: dict | None = None):
    """
    Placeholder: don't call eBay yet - just signal 'skipped'.
    When APIs are ready, implement add/update and return 'added'|'updated'|'skipped'.
    """
    return "skipped"

def delete_remote_item(remote_item: dict):
    """Placeholder: never delete on eBay right now."""
    return "skipped"


