# eBay Listing Tracker (MVP)

A lightweight Streamlit + SQLite app to track your eBay listings **separately** from your auction/receipt projects.

- Add/edit listings (SKU, title, price, etc.)
- Mark items **Sold** and auto-calc **Net Profit**
- Track **views, watchers, bids, relist count**
- **Import** from eBay Seller Hub CSV (Active/Sold) — case‑insensitive column mapping
- **Export** all rows to CSV anytime
- Persistent local DB (`ebay_tracker.db`) that survives restarts
- KPI cards: Active Listings | Sold | Gross Sales | Net Profit

---

## Quick Start

```bash
# 1) (Recommended) create & activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 2) Install deps
pip install streamlit pandas

# 3) Run the app
streamlit run ebay_tracker_app.py
```

The app will create `ebay_tracker.db` in the working folder on first run.

---

## Import from eBay Seller Hub (Option A)

1. In **Seller Hub → Listings → Active**, click **Download → CSV** (you can also export Sold later).
2. In the app’s **sidebar**, use **Import CSV (App template or eBay export)** and select your CSV.
3. The importer normalizes eBay headers to the app schema (case‑insensitive).

### Headers this importer recognizes

| App field | eBay CSV header candidates (any of these) |
|---|---|
| `ebay_item_id` | `Item number`, `Item ID`, `ItemID`, `Item Id` |
| `sku` | `Custom label (SKU)`, `Custom label`, `Custom Label (SKU)`, `CustomLabel`, `SKU` |
| `title` | `Title` |
| `list_date` | `Start date`, `Start Date`, `Start time`, `Start Time`, `Creation Date` |
| `list_price` | `Current price`, `Start price`, `Start Price`, `Price` |
| `bin_price` | `Auction Buy It Now price`, `Buy It Now Price`, `BIN Price`, `Buy It Now price` |
| `views` | `Views`, `View Count` |
| `watchers` | `Watchers` |
| `bids` | `Bids` |
| `quantity` | `Available quantity`, `Quantity`, `Quantity Available`, `Quantity Listed` |
| `item_url` | `Item URL`, `URL`, `View Item URL`, `Item URL link` |
| (sold/order fields) | `Sold Price`, `Sold For`, `Order ID`, `Sale Date`, etc. |

> If your export has different column names, add them to the mapping in `map_ebay_export_to_schema()` — it’s case‑insensitive and easy to extend.

---

## Common Tasks

- **Add/Update**: Left pane → fill form → **Save**.
- **Mark Sold**: Right pane → **Mark as sold** → enter price, buyer shipping, buyer/order info → **Mark selected as sold**.
- **Relist**: Right pane → **Relist selected** (bumps `relist_count`, resets status/date).
- **Adjust Metrics/Fees**: Right pane → **Update metrics / fees / costs** (views/watchers/bids/fees/COGS/shipping).
- **Filter**: Sidebar quick filters by `status`, `category`, `SKU`.
- **Export**: Sidebar → **Export CSV**.

---

## Data Model (SQLite table `listings`)

Key fields (subset):
- Identity: `id (PK)`, `ebay_item_id`, `sku`, `title`, `category`, `condition`
- Lifecycle: `status (draft|listed|sold|returned|archived)`, `list_date`, `relist_count`
- Pricing: `list_price`, `bin_price`, `sold_price`, `tax_collected`
- Shipping/Fees: `shipping_cost_buyer`, `shipping_cost_seller`, `ebay_fees`, `cost_of_goods`
- Metrics: `views`, `watchers`, `bids`, `quantity`
- Links: `item_url`, `photo_urls`
- Outcome: `sold_date`, `buyer_username`, `order_id`
- Bookkeeping: `last_updated`
- **Computed (UI only):** `net_profit = sold_price + shipping_cost_buyer − shipping_cost_seller − ebay_fees − cost_of_goods`

> The app persists data in `ebay_tracker.db` via `PRAGMA journal_mode=WAL` for stability during use.

---

## Database Migration (keep your data)

If you created `ebay_tracker.db` **before** we added new columns (e.g., `ebay_item_id`) you may see:

```
sqlite3.OperationalError: table listings has no column named ebay_item_id
```

**Two fixes:**

**A) Quick reset (fastest):**
- Stop the app, delete or rename `ebay_tracker.db`, restart, and re‑import your CSV.

**B) In‑place migration (keeps existing rows):**
Add this helper and call it at startup (already present in recent full drops):

```python
def migrate_listings_table(conn):
    cur = conn.execute("PRAGMA table_info(listings);")
    existing = {row[1] for row in cur.fetchall()}

    def add(coldef: str):
        conn.execute(f"ALTER TABLE listings ADD COLUMN {coldef};")

    needed = [
        ("ebay_item_id", "TEXT"),
        ("last_updated", "TEXT"),
        ("shipping_cost_buyer", "REAL DEFAULT 0.0"),
        ("shipping_cost_seller", "REAL DEFAULT 0.0"),
        ("ebay_fees", "REAL DEFAULT 0.0"),
        ("tax_collected", "REAL DEFAULT 0.0"),
        ("cost_of_goods", "REAL DEFAULT 0.0"),
        ("views", "INTEGER DEFAULT 0"),
        ("watchers", "INTEGER DEFAULT 0"),
        ("bids", "INTEGER DEFAULT 0"),
        ("quantity", "INTEGER DEFAULT 1"),
        ("relist_count", "INTEGER DEFAULT 0"),
        ("photo_urls", "TEXT"),
        ("notes", "TEXT"),
    ]
    for name, decl in needed:
        if name not in existing:
            add(f"{name} {decl}")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_ebay_item_id ON listings(ebay_item_id);")
    conn.commit()
```

Then in `get_conn()`:

```python
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(SCHEMA)
    migrate_listings_table(conn)   # <-- ensure this is called
    return conn
```

---

## Roadmap

- **Option B: Direct eBay API Sync (read‑only)**  
  - OAuth refresh token flow  
  - Pull **active listings** (Trading API `GetMyeBaySelling` or Sell Inventory API)  
  - Pull **orders** (Sell Fulfillment) → auto‑mark sold  
  - Pull **traffic** (Sell Analytics) → watchers/views enrichment  
  - Store `ebay_item_id` and upsert by that key

- **Reports & Alerts**  
  - Stale listings, monthly P&L, category profitability

- **Fee presets**  
  - % + fixed values per category or store level

---

## Troubleshooting

- **Import says 0 rows** → Check the first line of your CSV has headers. Ensure you downloaded “CSV” (not Excel) and that the file isn’t empty/filtered.
- **Missing columns** → Add their names to the mapping array in `map_ebay_export_to_schema()` (case‑insensitive).
- **DB locked** → Close extra Streamlit tabs/instances; WAL mode usually avoids this.
- **Windows emoji in text** → If you see encoding oddities, re‑save the CSV as UTF‑8 or try downloading again.

---

## License

MIT License. Use freely, modify, and share!

## Author

Erick Perales — IT Architect, Cloud Migration Specialist
