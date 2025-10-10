# eBay Tracker — Sync Summary & Offline Mode

This app tracks your eBay listings and now includes a clean **end‑of‑run sync summary** with portable artifacts for quick troubleshooting and CI.

## ✅ What we added/changed today (2025‑10‑09)

- **End‑of‑run summary** printed to console **and** written to artifacts:
  - `logs/sync-YYYYMMDD-HHMMSS.json` (detailed counts + per‑item entries + adapters used)
  - `logs/sync.log` (one‑line rollup per run)
  - `logs/debug.log` (stack traces / details)
- **Timezone‑aware UTC timestamps** (replaced deprecated `utcnow()`).
- **Offline mode by default** when credentials are placeholders/missing, or when `EBT_DISABLE_AUTH=1`.  
  → Runs complete with **Errors: 0** until your eBay developer creds are ready.
- **Safe deletes off while testing** via `EBT_DISABLE_DELETE=1`.
- **Minimal inventory adapters** in `ebay_inventory.py` so you can exercise the flow without live APIs:
  - `get_local_items()` reads from a CSV (if `EBT_LOCAL_CSV` is set) **or** from SQLite (`ebay_tracker.db`, table `listings`).
  - `get_remote_items()` returns `[]` in offline mode.
  - `upsert_remote_item()` / `delete_remote_item()` return `"skipped"` in offline mode.

> When your eBay API is approved and credentials are added, OAuth will run automatically and you can implement real add/update/delete behavior.

---

## Quick start (offline)

1. **Python**: 3.10+ recommended. Create/activate a venv.
2. **Environment**: add these to `.env` while waiting on eBay approval:
   ```env
   EBT_DISABLE_AUTH=1
   EBT_DISABLE_DELETE=1
   # Optional local data sources (pick one)
   # EBT_LOCAL_CSV=C:\path\to\items.csv
   # EBT_SQLITE_PATH=ebay_tracker.db
   # EBT_SQLITE_TABLE=listings
   ```
3. **Run the sync**:
   ```bash
   python sync.py
   ```
4. **Check artifacts** in `logs/`:
   - Look for the latest `sync-YYYYMMDD-HHMMSS.json` and a new line in `sync.log`.

### Expected (offline mode)
- Most items will be reported as **skipped** (no remote writes).  
- **Errors: 0** (OAuth is skipped until creds are real).

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
   # or set it to empty in your .env
   ```
3. Implement real eBay calls inside `ebay_inventory.py`:
   - `get_remote_items()` → fetch your existing eBay items (or offers) to build a remote index.
   - `upsert_remote_item(local_item, remote_item)` → decide `"added" | "updated" | "skipped"` and call the Sell APIs.
   - Optionally enable deletes (remove `EBT_DISABLE_DELETE`).

> The summary logic in `sync.py` does not change—counts and artifacts keep working in both offline and online modes.

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

> Advanced: If your function names differ, the runner can be extended to honor `EBT_GET_LOCAL_FN`, `EBT_GET_REMOTE_FN`, `EBT_UPSERT_FN`, and `EBT_DELETE_FN` to point at custom functions.

---

## Smoke test checklist

- [ ] `python sync.py` completes with **Errors: 0** in offline mode.  
- [ ] `logs/sync-YYYYMMDD-HHMMSS.json` exists and includes `counts` and `adapters`.  
- [ ] `logs/sync.log` has a new line with `added=… updated=… skipped=… errors=… duration_sec=…`.  
- [ ] Toggle `EBT_DISABLE_DELETE=1` on while testing; remove only when you’re confident.

---

## Changelog

**2025‑10‑09**
- Add end‑of‑run summary artifacts (JSON + rolling log) and console summary.
- Use timezone‑aware UTC timestamps.
- Gate OAuth behind real creds or `EBT_DISABLE_AUTH` (offline by default).
- Provide minimal adapters for local CSV/SQLite, plus no‑op remote ops.

---

## Troubleshooting

- **Auth error with placeholders** → set `EBT_DISABLE_AUTH=1` (offline) or add real creds.  
- **No local items loaded** → set `EBT_LOCAL_CSV` to a valid CSV, or ensure `EBT_SQLITE_PATH`/`_TABLE` point to a DB that has data.  
- **Deletes disabled** but still seeing delete attempts → make sure `EBT_DISABLE_DELETE=1` is exported in your shell **or** present in `.env`.

---

## License

MIT — use, modify, and share freely.

## Author

Erick Perales
IT Architect, Cloud Migration Specialist  
<https://github.com/peralese>
📧 *Private project maintained locally*
