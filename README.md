# eBay Tracker

Track your eBay listings locally and (when ready) sync to eBay. The runner prints a clean end-of-run summary and writes portable logs/artifacts for CI and troubleshooting.

## Install
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Features
- Console summary + JSON artifact (`logs/sync-YYYYMMDD-HHMMSS.json`) + rolling `logs/sync.log`
- Timezone-aware UTC timestamps
- Offline mode (skip OAuth with `EBT_DISABLE_AUTH=1`)
- Safe deletes off during testing (`EBT_DISABLE_DELETE=1`)
- CLI flags: `--dry-run`, `--since`, `--summary-csv`, `--verbose`

## Quick start (offline)
```powershell
# from project root
$env:EBT_DISABLE_AUTH = "1"
$env:EBT_DISABLE_DELETE = "1"
python sync.py --dry-run -v
```

### Flags
- `--dry-run` - simulate (no auth, no writes, no deletes)
- `--since YYYY-MM-DD` - only process local items with a timestamp on/after date
- `--summary-csv <path>` - write a one-row CSV rollup (counts + duration)
- `-v | -vv` - increase log verbosity in `logs/debug.log`

## Using SQLite as the local source
By default the runner reads from SQLite (`EBT_SQLITE_PATH=ebay_tracker.db`, `EBT_SQLITE_TABLE=listings`). If you prefer CSV, set `EBT_LOCAL_CSV` and it will take precedence.

### Make `--since` work with your schema (view approach)
If your table doesn't have `updated_at` but it has `last_updated`, `sold_date`, or `list_date`, create a view that surfaces an `updated_at` column. Example:

```sql
DROP VIEW IF EXISTS listings_for_sync;
CREATE VIEW listings_for_sync AS
SELECT
  id, sku, title, status, list_price, sold_price, ebay_item_id,
  CASE
    WHEN last_updated IS NOT NULL AND last_updated <> '' THEN last_updated
    WHEN sold_date    IS NOT NULL AND sold_date    <> '' THEN sold_date
    WHEN list_date    IS NOT NULL AND list_date    <> '' THEN list_date
    ELSE NULL
  END AS updated_at
FROM listings;
```

Point the runner at the view and test:
```powershell
$env:EBT_SQLITE_TABLE = "listings_for_sync"
python sync.py --dry-run --since 2025-10-01 -v
```

> Dates like `MM/DD/YYYY` are supported; the runner also accepts ISO (`YYYY-MM-DD`).

## Examples
```powershell
# Dry run + verbose
python sync.py --dry-run -v

# Since-filter + CSV rollup
python sync.py --dry-run --since 2025-10-01 --summary-csv logs\summary-db.csv

# Extra debug detail
python sync.py --dry-run -vv
```

## UI (Streamlit)
Run a local UI to browse and edit records in `ebay_tracker.db`:
```powershell
streamlit run ebay_tracker_app.py
```
The app creates tables on first run and supports CSV imports from eBay Seller Hub.

## Going online (later)
1. Copy `.env.example` to `.env` and fill values:
   ```env
   EBAY_CLIENT_ID=...
   EBAY_CLIENT_SECRET=...
   EBAY_REFRESH_TOKEN=...
   ```
2. Remove `EBT_DISABLE_AUTH` and implement in `ebay_inventory.py`:
   - `get_remote_items()` — fetch current eBay items (keyed by `sku` or `id`)
   - `upsert_remote_item(local_item, remote_item)` — return `"added" | "updated" | "skipped"`
   - (Optional) `delete_remote_item()` after you're confident

Artifacts and summaries work the same in both offline and online modes.

## Troubleshooting
- `--since` returns 0 items — ensure your adapter returns a timestamp column (`updated_at`, `sold_date`, `list_date`, etc.). Using the view above is the fastest fix.
- Still using CSV accidentally — unset `EBT_LOCAL_CSV` so SQLite is used.
- Deletes happening in tests — set `EBT_DISABLE_DELETE=1`.

## Changelog
**2025-10-13**  
- Wire `--since` to SQLite via `listings_for_sync` view example.  
- Confirmed flags: `--dry-run`, `--since`, `--summary-csv`, `--verbose`.

**2025-10-11**  
- Added CLI flags; preserved adaptive imports, offline auth gating, and artifacts.

**2025-10-09**  
- Introduced end-of-run summary artifacts and UTC timestamps.

---

## License

MIT - use, modify, and share freely.

## Author

Erick Perales  
IT Architect, Cloud Migration Specialist  
<https://github.com/peralese>

*Private project maintained locally*

