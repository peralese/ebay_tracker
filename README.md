# 🛒 eBay Listing Tracker

The **eBay Listing Tracker** is a local Streamlit-based app for managing your eBay listings database.  
It allows you to import eBay CSV exports, track listing status, update metrics, and maintain a clean, deduplicated dataset.

---

## 🚀 Features

### 🔄 Import & Data Management
- **Import eBay exports** (e.g., *All Active Listings* reports).
- **Safe Import System**:
  - Manual **Import** button to avoid accidental re-imports.
  - **MD5 hash tracking** to prevent duplicate uploads.
  - **Unique index** on `(ebay_item_id, sku)` to ensure duplicates are ignored.
- Supports both **Active Listings** and (future) **Orders/Sold** reports.
- Data stored locally in a lightweight **SQLite** database (`ebay_tracker.db`).

### 🧩 Corrected Active Listings Handling
- Active Listings files now correctly import as **`status = listed`**.
- The app **no longer misclassifies** active items as sold.
- “Sold” and “Gross/Net Sales” counters only update for listings manually marked as sold or imported from future “Orders” reports.

### 📊 Dashboard & KPIs
- **Active Listings** count.
- **Sold Listings** count.
- **Gross Sales** and **Net Profit** (computed from sold data).
- Auto-calculated metrics for:
  - Fees
  - Shipping (buyer/seller)
  - Cost of goods
  - Profit margins

### 🧮 Add / Edit Listings
- Add or edit listing details such as:
  - SKU, Title, Category, Condition, Status, Dates, Prices, URLs
  - Views, Watchers, Bids, Relist count
  - Cost of goods, eBay fees, Notes
- All changes automatically saved to the database.

### ⚙️ Quick Actions
- **Update metrics** — Add views, watchers, bids, or set fees & costs.
- **Mark as Sold** — Convert a listing to sold, track buyer/order/shipping.
- **Relist** — Reset status to `listed` and increment relist count.
- **Delete Selected** — Remove listings permanently.

### 🧹 Maintenance Tools
Built-in one-click cleanup under the **Maintenance** section:
- **Fix Statuses**: Resets incorrect “sold” statuses to `listed` for active items.
- **De-duplicate Listings**: Keeps the lowest ID per `(ebay_item_id, sku)` pair and removes duplicates.
- Ensures database consistency without needing external scripts.

---

## 📂 Project Structure

```
ebay_tracker_app.py     # Streamlit app
ebay_tracker.db         # SQLite database (auto-created)
README.md               # This file
```

---

## 🧠 How to Use

1. **Run the App**
   ```bash
   streamlit run ebay_tracker_app.py
   ```

2. **Import Your eBay CSV**
   - Click **Browse files** and select your `All Active Listings` export from eBay.
   - Click **Import this file**.
   - The app will import new listings (duplicates ignored).
   - You’ll see a confirmation message:
     > ✅ Imported 122 listings (duplicates ignored).

3. **View and Filter Listings**
   - Use sidebar filters for `Status`, `Category`, or `SKU`.
   - Listings will appear in the table on the right.

4. **Add / Edit Listings**
   - Switch between **Add new** and **Edit existing**.
   - Fill or update listing details.
   - Click **Save**.

5. **Quick Actions**
   - **Mark as Sold** → Manually mark listings as sold.
   - **Relist selected** → Reactivate sold or archived listings.
   - **Update metrics / fees / costs** → Adjust views, watchers, or eBay fees.

6. **Maintenance**
   - **Fix Statuses**: Correct legacy imported statuses.
   - **De-duplicate Listings**: Remove duplicate entries if any remain.

---

## 🧱 Database Schema

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER | Primary key |
| sku | TEXT | eBay SKU |
| title | TEXT | Listing title |
| category | TEXT | eBay category |
| condition | TEXT | Item condition |
| status | TEXT | `listed`, `sold`, `draft`, etc. |
| list_date | TEXT | Date listed |
| list_price | REAL | Starting price |
| bin_price | REAL | Buy-It-Now price |
| sold_price | REAL | Sale price |
| sold_date | TEXT | Date sold |
| buyer_username | TEXT | Buyer ID |
| order_id | TEXT | eBay order number |
| shipping_cost_buyer | REAL | Shipping charged to buyer |
| shipping_cost_seller | REAL | Seller-paid shipping |
| ebay_fees | REAL | eBay fees |
| tax_collected | REAL | Tax collected |
| cost_of_goods | REAL | Cost of goods sold |
| views | INTEGER | Page views |
| watchers | INTEGER | Watchers |
| bids | INTEGER | Number of bids |
| quantity | INTEGER | Quantity |
| relist_count | INTEGER | Relist counter |
| item_url | TEXT | eBay listing URL |
| photo_urls | TEXT | Optional image URLs |
| notes | TEXT | Notes or remarks |
| last_updated | TEXT | Auto timestamp |
| ebay_item_id | TEXT | eBay item number |

---

## 🧩 Recent Updates (2025-10-07)

| Change | Description |
|--------|--------------|
| ✅ Safe Import System | Added MD5-hash detection, manual import button, and `INSERT OR IGNORE` logic |
| ✅ Unique Index | Enforced unique `(ebay_item_id, sku)` per listing |
| ✅ Correct Active Listings Detection | Detects “All Active Listings” exports and sets all items to `status='listed'` |
| ✅ Maintenance UI | Added Fix Statuses and De-duplicate buttons inside the app |
| ✅ Fixed KPI Calculations | “Sold” count no longer mislabels listed items |
| ✅ Database Stability | Added WAL mode, schema autoload, and consistent column defaults |
| ✅ UI Polishing | Simplified filters, added success notifications, and improved import UX |

---

## 🔮 Coming Next

Planned enhancements:
- **Sold Orders Importer** → Automatically update Gross/Net Profit using eBay Sales Report.
- **CSV Merge Detection** → Smart merging between Active and Sold datasets.
- **Visual Analytics Dashboard** → Trend charts for sales, profits, and listing performance.
- **Cloud Backup / Google Sheets Sync** → Optional sync of your data to Google Sheets.

---

## 📜 License

MIT License — use freely, modify, and share.

---

## 👤 Author

**Erick Perales**  
IT Architect, Cloud Migration Specialist  
<https://github.com/peralese>
📧 *Private project maintained locally*
