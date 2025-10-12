# eBay Tracker — Sync Summary, Offline Mode, and CLI Flags

This app tracks your eBay listings and prints a **clean end-of-run sync summary**. It also writes portable artifacts for quick troubleshooting and CI.

## ✅ What we added recently (2025-10-11)

- **CLI flags**
  - `--dry-run` — simulate the sync (no auth, no writes, no deletes).
  - `--summary-csv <path>` — export a one-row CSV rollup of the run.
  - `--since YYYY-MM-DD` — process only local items with timestamps on/after the date (local-side filter; checks common fields like `updated_at`, `modified`, `created_at`, etc.).
  - `--verbose` / `-v` / `-vv` — increase logging detail in `logs/debug.log`.
- **Timezone-aware UTC timestamps** (replaces deprecated `utcnow()`).
- **Offline mode by default** when credentials are placeholders/missing, or when `EBT_DISABLE_AUTH=1`.
- **Safe deletes off while testing** via `EBT_DISABLE_DELETE=1`.
- **Minimal inventory adapters** in `ebay_inventory.py` to exercise the flow without live APIs:
  - `get_local_items()` reads from a CSV (if `EBT_LOCAL_CSV` is set) **or** from SQLite (`ebay_tracker.db`, table `listings`).
  - `get_remote_items()` returns `[]` in offline mode.
  - `upsert_remote_item()` / `delete_remote_item()` return `"skipped"` in offline mode.

> When your eBay API is approved and credentials are added, OAuth will run automatically and you can implement real add/update/delete behavior.

---

## Quick start (offline)

1) **Python**: 3.10+ recommended. Create/activate a venv.
2) **Environment**: add these to `.env` while waiting on eBay approval:
```env
EBT_DISABLE_AUTH=1
EBT_DISABLE_DELETE=1
# Optional local data sources (pick one)
# EBT_LOCAL_CSV=C:\path\to\items.csv
# EBT_SQLITE_PATH=ebay_tracker.db
# EBT_SQLITE_TABLE=listings
```
3) **Run the sync**:
```bash
python sync.py --dry-run
```
4) **Artifacts** (written to `logs/`):
- `sync-YYYYMMDD-HHMMSS.json` — detailed counts, per-item entries, adapters used
- `sync.log` — one-line rollup (added/updated/skipped/deleted/errors/duration)
- `debug.log` — log output (verbosity controlled by `-v` / `-vv`)

### Expected (offline mode)
- Most items reported as **skipped** (no remote writes).
- **Errors: 0** (OAuth is skipped until creds are real).

---

## CLI usage

```bash
# Dry run with verbose logging
python sync.py --dry-run -v

# Filter local items since a date and output a summary CSV
python sync.py --dry-run --since 2025-10-01 --summary-csv logs/summary-latest.csv

# Extra-verbose logging
python sync.py --dry-run -vv

# Regular run (when creds are ready)
python sync.py --since 2025-10-01
```
> `--since` compares against common timestamp fields on your local items (`updated_at`, `modified`, `created_at`, etc.). If none are present or parseable, the item isn’t counted for the filter.

---

## Switching to online mode (when eBay creds are ready)

1. Add real values to `.env`:
```env
EBAY_CLIENT_ID=...
EBAY_CLIENT_SECRET=...
EBAY_REFRESH_TOKEN=...
```
2. **Remove/Unset** `EBT_DISABLE_AUTH` so OAuth runs:
```bash
# PowerShell
Remove-Item Env:EBT_DISABLE_AUTH
# or delete/comment it in your .env
```
3. Implement real eBay calls inside `ebay_inventory.py`:
   - `get_remote_items()` → fetch current eBay items to build a remote index.
   - `upsert_remote_item(local_item, remote_item)` → decide `"added" | "updated" | "skipped"` and call the Sell APIs.
   - Optionally enable deletes (remove `EBT_DISABLE_DELETE`).

Artifacts and console summaries continue to work in both offline and online modes.

---

## Environment variables (reference)

| Variable | Purpose | Default/Notes |
|---|---|---|
| `EBT_DISABLE_AUTH` | Skip OAuth, run fully offline | **Recommended** while creds are placeholders |
| `EBT_DISABLE_DELETE` | Skip delete reconciliation | Safer during testing |
| `EBT_LOCAL_CSV` | Path to CSV for local items | When set, CSV takes priority over SQLite |
| `EBT_SQLITE_PATH` | SQLite file path | `ebay_tracker.db` |
| `EBT_SQLITE_TABLE` | SQLite table name | `listings` |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` / `EBAY_REFRESH_TOKEN` | eBay OAuth | Required for online mode |

> Advanced adapters: If your function names differ, you can extend the runner to honor `EBT_GET_LOCAL_FN`, `EBT_GET_REMOTE_FN`, `EBT_UPSERT_FN`, and `EBT_DELETE_FN` for custom bindings.

---

## Smoke test checklist

- [ ] `python sync.py --dry-run` completes with **Errors: 0** in offline mode.  
- [ ] `logs/sync-YYYYMMDD-HHMMSS.json` exists and includes `counts` and `adapters`.  
- [ ] `logs/sync.log` has a new line with `added=… updated=… skipped=… deleted=… errors=… duration_sec=…`.  
- [ ] `--summary-csv` creates a one-row CSV rollup.  
- [ ] `--since` reduces local items when a cutoff date is provided.  
- [ ] Toggle `EBT_DISABLE_DELETE=1` on while testing; remove only when you’re confident.

---

## Changelog

**2025-10-11**
- Add CLI flags: `--dry-run`, `--summary-csv`, `--since`, `--verbose`.
- Preserve adaptive imports, offline auth gating, and summary artifacts.

**2025-10-09**
- Add end-of-run summary artifacts (JSON + rolling log) and console summary.
- Use timezone-aware UTC timestamps.
- Gate OAuth behind real creds or `EBT_DISABLE_AUTH` (offline by default).
- Provide minimal adapters for local CSV/SQLite, plus no-op remote ops.

---

## Troubleshooting

- **Auth error with placeholders** → set `EBT_DISABLE_AUTH=1` (offline) or add real creds.  
- **No local items loaded** → set `EBT_LOCAL_CSV` to a valid CSV, or ensure `EBT_SQLITE_PATH`/`_TABLE` point to a DB that has data.  
- **Deletes disabled but still seeing delete attempts** → verify `EBT_DISABLE_DELETE=1` is exported in your shell or present in `.env`.  
- **Bad `--since` value** → use `YYYY-MM-DD` (e.g., `2025-10-01`). A warning is logged and the run continues without filtering.

---

## License

MIT — use, modify, and share freely.


## Author

Erick Perales
IT Architect, Cloud Migration Specialist  
<https://github.com/peralese>
📧 *Private project maintained locally*
