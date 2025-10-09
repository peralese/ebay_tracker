# 🛒 eBay Item Tracker --- Sell API Integration (Phase A)

## 📦 Overview

This update adds **Sell API read-only synchronization** to automatically
refresh your local SQLite database with the latest data from your eBay
account. It introduces new modules and tables for **offers** and
**sync_runs**, and uses OAuth2 refresh tokens for secure, long-lived
access.

------------------------------------------------------------------------

## 🚀 Features Added

-   **Sell Feed API** integration to request Active Inventory Reports.\
-   **Sell Inventory API** integration to fetch offer and listing data
    per SKU.\
-   **Automatic upsert** logic prevents duplicates and updates changed
    records.\
-   **DB migrations** to create new tables: `offers` and `sync_runs`.\
-   **CLI support** to run a sync manually.\
-   **Read-only scopes** for safe access.

------------------------------------------------------------------------

## 🧰 New Files and Modules

  -----------------------------------------------------------------------
  File                       Purpose
  -------------------------- --------------------------------------------
  `ebay_auth.py`             Handles OAuth refresh token flow and
                             short-lived token exchange.

  `ebay_feed.py`             Creates and polls Feed API Active Inventory
                             Report tasks.

  `ebay_inventory.py`        Retrieves offer and listing info per SKU.

  `db.py`                    Database helper for upsert and sync
                             tracking.

  `sych.py`                  Orchestrates Feed and Inventory API calls
                             and writes results to DB.

  `sync_cli.py`              Optional CLI wrapper for `sych.run_sync()`.
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## ⚙️ Environment Setup

### 1️⃣ Create `.env` file

``` ini
EBAY_ENV=PROD
EBAY_APP_ID=YOUR_CLIENT_ID
EBAY_CERT_ID=YOUR_CLIENT_SECRET
EBAY_REFRESH_TOKEN=YOUR_REFRESH_TOKEN
```

*(Your developer account must be approved to obtain these values.)*

### 2️⃣ Install Dependencies

``` bash
pip install python-dotenv requests
```

### 3️⃣ Initialize Database

``` bash
python migrate_once.py
```

### 4️⃣ Run Sync

``` bash
python sync_cli.py
```

Output example:

    ✅ Sync complete: {'items_seen': 122, 'offers_seen': 122, 'task_id': '...UUID...'}

### 5️⃣ Inspect Database

``` bash
sqlite3 ebay_tracker.db "SELECT COUNT(*) FROM offers;"
sqlite3 ebay_tracker.db "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 3;"
```

------------------------------------------------------------------------

## 🧪 Smoke Test (once credentials are available)

``` bash
python -c "from ebay_auth import get_access_token; print(get_access_token()[:32]+'...')"
python -c "import sych; print(sych.run_sync())"
```

Expected behavior: - Tokens refresh successfully.\
- Feed API task runs and returns results.\
- Offers and sync_runs tables are populated.

------------------------------------------------------------------------

## 🧭 Next Steps

-   Wait for **eBay Developer Program approval**.\
-   Once approved, add credentials to `.env`.\
-   Perform first live sync (read-only).\
-   Add Streamlit dashboard integration to visualize sync stats.

------------------------------------------------------------------------

## 📜 License

MIT License. Use freely, modify, and share!

## Author

Erick Perales
IT Architect, Cloud Migration Specialist  
<https://github.com/peralese>
📧 *Private project maintained locally*
