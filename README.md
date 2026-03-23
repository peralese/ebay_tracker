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
- Dry-run performs no network calls (skips remote fetch)
- CLI flags: `--dry-run`, `--since`, `--summary-csv`, `--verbose`

## Quick start (offline)
```powershell
# from project root
$env:EBT_DISABLE_AUTH = "1"
$env:EBT_DISABLE_DELETE = "1"
python sync.py --dry-run -v
```

### Flags
- `--dry-run` - simulate (no auth, no remote fetch, no writes, no deletes)
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

## Convenience Scripts (Profiles)
Use PowerShell helpers to set env automatically and run with the right profile.

```powershell
# Run sync in common modes
scripts\run-sync.ps1 -Profile offline -Verbose -DryRun
scripts\run-sync.ps1 -Profile csv -CsvPath .\tests\_tmp_smoke.csv -DryRun -Verbose
scripts\run-sync.ps1 -Profile sqlite -Since 2025-10-01 -DryRun
# If you have credentials in .env and want to fetch remote feed (no writes):
scripts\run-sync.ps1 -Profile online -Verbose -DryRun:$false

# Launch the UI with a profile
scripts\run-ui.ps1 -Profile sqlite
scripts\run-ui.ps1 -Profile csv -CsvPath .\path\to\file.csv
```

Profiles set these env vars for the current process:
- `offline`: `EBT_DISABLE_AUTH=1`, `EBT_DISABLE_DELETE=1`, clears `EBT_LOCAL_CSV`
- `csv`: sets `EBT_LOCAL_CSV=<CsvPath>`, `EBT_DISABLE_AUTH=1`, `EBT_DISABLE_DELETE=1`
- `sqlite`: clears `EBT_LOCAL_CSV`; if unset, sets `EBT_SQLITE_TABLE=listings_for_sync`; `EBT_DISABLE_AUTH=1`, `EBT_DISABLE_DELETE=1`
- `online`: clears `EBT_DISABLE_AUTH` (auth enabled); leaves `EBT_DISABLE_DELETE=1` unless you override; clears `EBT_LOCAL_CSV`

## Seed From CSV (CLI)
Import an eBay export into the SQLite DB without opening the UI.

```powershell
# Basic import
python seed_from_csv.py --csv .\path\to\ebay_export.csv

# Dry-run (parse + report, no writes)
python seed_from_csv.py --csv .\path\to\ebay_export.csv --dry-run

# Specify DB path/table and force re-import of the same file hash
python seed_from_csv.py --csv .\file.csv --db ebay_tracker.db --table listings --force
```

The importer normalizes common Seller Hub columns, sets `status` for Active Listings, and
inserts rows with `INSERT OR IGNORE` under a unique `(ebay_item_id, sku)` index. It also
records the file hash in `imports` to avoid re-importing identical files.

## Going online (later)
1. Copy `.env.example` to `.env` and fill values:
   ```env
   EBAY_CLIENT_ID=...
   EBAY_CLIENT_SECRET=...
   EBAY_REFRESH_TOKEN=...
   ```
2. Remove `EBT_DISABLE_AUTH` to enable online mode. A default `get_remote_items()` implementation reads active listings via the Feed API when auth is configured. For writes, implement:
   - `upsert_remote_item(local_item, remote_item)` - return `"added" | "updated" | "skipped"`
   - (Optional) `delete_remote_item(remote_item)` after you're confident
Artifacts and summaries work the same in both offline and online modes.


## Troubleshooting
- `--since` returns 0 items - ensure your adapter returns a timestamp column (`updated_at`, `sold_date`, `list_date`, etc.). Using the view above is the fastest fix.
- Still using CSV accidentally - unset `EBT_LOCAL_CSV` so SQLite is used.
- Deletes happening in tests - set `EBT_DISABLE_DELETE=1`.
- Remote items empty during `--dry-run` - expected: dry-run skips remote fetch and all network calls.

## Shared Inventory Integration

This app is part of a larger inventory workflow that includes `auction_tracker` for purchase tracking. A shared SQLite database (`shared_inventory.db`) in `/home/peralese/Projects/` serves as the central lifecycle record for items from purchase to sale.

- **DB Path**: Defaults to `/home/peralese/Projects/shared_inventory.db`; override with `SHARED_INVENTORY_DB` env var.
- **Schema**: See `docs/inventory_integration_plan.md` for details. Includes CHECK constraints for status and automatic timestamps.
- **Helpers**: Use `shared_db.py` for DB operations (connect, insert, update, query). Handles calculations and deduplication.
- **Deduplication**: Based on deterministic `item_id` (stable across reprocessing) and `source_hash` for file-level checks.
- **Linkage**: Listings table has `shared_item_id` linking to shared inventory. Matching on SKU or eBay Item ID when saving.
- **Updates**: When linked, shared inventory is updated with sale data (status, prices, fees, net_profit).
- **Reconciliation**: The Streamlit app now includes a read-only reconciliation section for validating integration state before manual linking.
- **Current Status**: Phase 3.25 complete (incremental linkage plus observability).

### Reconciliation View

Open the Streamlit app and scroll to the `Reconciliation` section. It compares `ebay_tracker.db` against `shared_inventory.db` without modifying either database.

The view surfaces:
- `Unlinked Listings`: rows in `listings` with no `shared_item_id`.
- `Linked Mismatches`: linked rows where mapped status or key sale fields differ between `listings` and shared `inventory`.
- `Shared Purchased/RTL Unlinked`: shared inventory rows still in `purchased` or `ready_to_list` with no linked listing.
- `Matching Opportunities`: read-only candidate scans for unlinked listings using the current exact-match signals on purchased shared inventory.

Mismatch detection currently compares:
- `status` in `listings` mapped to expected shared `listing_status` (`draft -> ready_to_list`, `listed -> listed`, `sold -> sold`, `returned/archived -> closed`)
- `list_price`
- `sold_price`
- `sold_date`
- `ebay_item_id`

Data sources compared:
- `ebay_tracker.db` table: `listings`
- `shared_inventory.db` table: `inventory`

Notes:
- The reconciliation logic is read-only and does not change current linking behavior.
- Matching opportunities intentionally mirror the current write-path signals and only scan shared rows in `purchased` status.

### Manual Linking

Use the `Manual link one listing` expander inside the `Reconciliation` section for unresolved listings. The workflow is one listing at a time and requires explicit confirmation before anything is written.

User flow:
- Select one unlinked listing from the reconciliation section.
- Review suggested shared inventory candidates with comparison fields: `title`, `purchase_date`, `lot_number`, `total_purchase_cost`, `sku`, and `ebay_item_id`.
- Optionally show additional eligible shared inventory rows when no suggestion is obvious.
- Choose exactly one shared inventory record.
- Check the confirmation box and click `Confirm manual link`.

What gets updated on confirmation:
- `listings.shared_item_id` is assigned for the selected listing.
- If `Sync current listing sale/list data to shared inventory after linking` is enabled, the shared record is updated with the current listing-side fields using the same field mapping used by the app when it auto-links on save. This includes mapped `listing_status`, `list_date`, `list_price`, `sold_price`, `sold_date`, `shipping_cost`, `marketplace_fees`, `ebay_item_id`, and `sku`.

Safety rules:
- Manual linking is single-record only.
- The selected shared record must exist and must not already be linked to another listing.
- The selected shared record must be in `purchased` or `ready_to_list` state.
- Canceling the flow does not write any changes.

## Testing
- Install dev deps: `pip install -r requirements-dev.txt`
- Run quick smoke test: `python tests\smoke_sync.py`
- Run pytest suite: `pytest -q`
## Changelog
**2025-11-02**  
- `--dry-run` skips remote fetch (no network calls).  
- `--since` filter is UTC-aware and parses each item once.  
- Added `.env.example` and `requirements-dev.txt`.  
- Added gated remote read via Feed API (only when auth enabled).
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









