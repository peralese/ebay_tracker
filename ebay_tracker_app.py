# ebay_tracker_app.py
# Full drop-in replacement:
# - Correctly treats eBay "All Active Listings" export as status='listed'
# - Safe import (manual button + MD5 de-dupe + unique index + INSERT OR IGNORE)
# - Maintenance tools (Fix statuses, De-duplicate)
# - KPIs use normalized status

import sqlite3
import pandas as pd
import datetime as dt
from datetime import date
import streamlit as st
from pathlib import Path
from io import BytesIO
import hashlib

from shared_db import connect as shared_connect, get_item_by_id, update_inventory_item
from reconciliation import build_reconciliation_report
from manual_linking import build_shared_update_payload, get_manual_link_context, manual_link_listing

DB_PATH = Path("ebay_tracker.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sku TEXT,
  title TEXT,
  category TEXT,
  condition TEXT,
  status TEXT DEFAULT 'draft',
  list_date TEXT,
  list_price REAL,
  bin_price REAL,
  sold_price REAL,
  sold_date TEXT,
  buyer_username TEXT,
  order_id TEXT,
  shipping_cost_buyer REAL DEFAULT 0.0,
  shipping_cost_seller REAL DEFAULT 0.0,
  ebay_fees REAL DEFAULT 0.0,
  tax_collected REAL DEFAULT 0.0,
  cost_of_goods REAL DEFAULT 0.0,
  views INTEGER DEFAULT 0,
  watchers INTEGER DEFAULT 0,
  bids INTEGER DEFAULT 0,
  quantity INTEGER DEFAULT 1,
  relist_count INTEGER DEFAULT 0,
  item_url TEXT,
  photo_urls TEXT,
  notes TEXT,
  last_updated TEXT,
  ebay_item_id TEXT,
  shared_item_id TEXT
);
"""

IMPORTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_hash TEXT UNIQUE,
  file_name TEXT,
  imported_at TEXT
);
"""

UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_listings_item_sku
ON listings(ebay_item_id, sku);
"""

# ----------------- DB helpers -----------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(SCHEMA)
    conn.execute(IMPORTS_SCHEMA)
    conn.execute(UNIQUE_INDEX)
    # Add shared_item_id column if missing
    try:
        conn.execute("ALTER TABLE listings ADD COLUMN shared_item_id TEXT;")
    except sqlite3.OperationalError:
        pass  # Column already exists
    return conn

def df_all(conn):
    df = pd.read_sql_query("SELECT * FROM listings ORDER BY id DESC;", conn)
    if not df.empty:
        df["net_profit"] = (
            df["sold_price"].fillna(0)
            + df["shipping_cost_buyer"].fillna(0)
            - df["shipping_cost_seller"].fillna(0)
            - df["ebay_fees"].fillna(0)
            - df["cost_of_goods"].fillna(0)
        )
    return df

def upsert(conn, data: dict, row_id: int | None):
    data = dict(data)
    data["last_updated"] = dt.datetime.now().isoformat(timespec="seconds")

    cols = list(data.keys())
    vals = [data[c] for c in cols]

    if row_id is None:
        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT INTO listings ({','.join(cols)}) VALUES ({placeholders});"
        conn.execute(sql, vals)
    else:
        sets = ",".join([f"{c}=?" for c in cols])
        sql = f"UPDATE listings SET {sets} WHERE id=?;"
        conn.execute(sql, vals + [row_id])
    conn.commit()

def find_shared_item_id(sku=None, ebay_item_id=None):
    """Find matching item_id from shared inventory. Returns item_id if exactly one match, else None."""
    with shared_connect() as conn:
        if sku:
            cur = conn.execute("SELECT item_id FROM inventory WHERE sku = ? AND listing_status = 'purchased'", (sku,))
            results = cur.fetchall()
            if len(results) == 1:
                return results[0][0]
        if ebay_item_id:
            cur = conn.execute("SELECT item_id FROM inventory WHERE ebay_item_id = ? AND listing_status = 'purchased'", (ebay_item_id,))
            results = cur.fetchall()
            if len(results) == 1:
                return results[0][0]
    return None

# ----------------- Import helpers -----------------
def to_number(series):
    return pd.to_numeric(series, errors="coerce")

def normalize_status(raw):
    if pd.isna(raw):
        return None
    s = str(raw).strip().lower()
    mapping = {
        "active": "listed",
        "listed": "listed",
        "live": "listed",
        "unsold": "archived",
        "ended": "archived",
        "completed": "archived",
        "sold": "sold",
        "return": "returned",
        "returned": "returned",
        "draft": "draft",
    }
    return mapping.get(s, s)

def _pick_ci(df: pd.DataFrame, candidates: list[str]):
    """Pick a column from df by case-insensitive match from candidates."""
    lower = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower:
            return df[lower[c.lower()]]
    return None

def looks_like_active_listings(imp: pd.DataFrame) -> bool:
    """
    Heuristic for eBay 'All Active Listings' report:
    - Often has 'Sold quantity' and 'Available quantity'
    - Usually lacks a 'Status'/'Listing Status' column
    """
    cols = set(imp.columns)
    has_qty_cols = ("Sold quantity" in cols or "Quantity Sold" in cols or "Qty Sold" in cols) \
                   or ("Available quantity" in cols or "Quantity Available" in cols or "Quantity" in cols)
    has_status = ("Status" in cols) or ("Listing Status" in cols) or ("Result" in cols)
    return has_qty_cols and not has_status

def map_ebay_export_to_schema(imp: pd.DataFrame) -> pd.DataFrame:
    """
    Accepts common eBay Seller Hub CSV exports (Active Listings, Orders/Sold, etc.)
    and maps columns to our schema. Unknown columns are ignored.
    - If this is an Active Listings export, force status='listed' for all rows.
    """
    imp = imp.copy()
    imp.columns = [c.strip() for c in imp.columns]

    colmap = {
        "ebay_item_id": ["Item number", "Item ID", "ItemID", "Item Id"],
        "sku": ["Custom label (SKU)", "Custom label", "Custom Label (SKU)", "SKU"],
        "title": ["Title"],
        "category": ["Category", "Category Name", "Primary Category", "eBay category 1 name"],
        "status": ["Status", "Listing Status", "Result"],  # may not exist in Active Listings
        "list_date": ["Start date", "Start Date", "Start time", "Start Time", "Creation Date"],
        "list_price": ["Current price", "Start price", "Start Price", "Price"],
        "bin_price": ["Auction Buy It Now price", "Buy It Now Price", "Buy It Now price"],
        "views": ["Views", "View Count"],
        "watchers": ["Watchers"],
        "bids": ["Bids"],
        "quantity": ["Available quantity", "Quantity", "Quantity Available", "Quantity Listed"],
        "sold_qty": ["Sold quantity", "Quantity Sold", "Qty Sold"],
        "item_url": ["Item URL", "URL", "View Item URL", "Item URL link"],
        "sold_price": ["Sold Price", "Sold For", "Total price", "Total Price", "Price (total)"],
        "sold_date": ["Sale Date", "Paid On", "Order Date", "End Date", "End date", "End time", "End Time"],
        "buyer_username": ["Buyer User ID", "Buyer Username", "Buyer ID", "Buyer"],
        "order_id": ["Order ID", "Sales Record Number", "Sales Record #", "Record number", "Order id"],
        "shipping_cost_buyer": ["Shipping And Handling", "Shipping charged to buyer", "Postage and packaging - paid by buyer", "Shipping paid by buyer"],
        "notes": ["Notes", "Private notes"],
        "condition": ["Condition"],
    }

    data = {}
    for our, cands in colmap.items():
        v = _pick_ci(imp, cands)
        if v is not None:
            data[our] = v

    df = pd.DataFrame(data)

    # ---- Types / normalization ----
    for c in ["list_price", "bin_price", "sold_price", "shipping_cost_buyer", "sold_qty"]:
        if c in df.columns:
            df[c] = to_number(df[c]).fillna(0)

    for c in ["views", "watchers", "bids", "quantity"]:
        if c in df.columns:
            df[c] = to_number(df[c]).fillna(0).astype("Int64")

    if "list_date" in df.columns:
        df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce").dt.date.astype("string")

    if "sold_date" in df.columns:
        df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce").dt.date.astype("string")

    # ---- Determine status ----
    if looks_like_active_listings(imp):
        # This is the Active Listings export → everything is 'listed'
        df["status"] = "listed"
    else:
        # If a status column exists, normalize it
        if "status" in df.columns:
            df["status"] = df["status"].map(normalize_status)
        else:
            # Fallback heuristic for other reports:
            # if sold markers exist, mark sold; else listed
            sold_markers = []
            if "sold_price" in df.columns:
                sold_markers.append(df["sold_price"].fillna(0) > 0)
            if "sold_date" in df.columns:
                sold_markers.append(df["sold_date"].notna())
            any_sold = pd.concat(sold_markers, axis=1).any(axis=1) if sold_markers else pd.Series(False, index=df.index)
            df.loc[any_sold, "status"] = "sold"
            df.loc[~any_sold, "status"] = "listed"

    # Ensure all schema columns exist
    expected = [
        "sku","title","category","condition","status","list_date","list_price","bin_price",
        "sold_price","sold_date","buyer_username","order_id","shipping_cost_buyer",
        "shipping_cost_seller","ebay_fees","tax_collected","cost_of_goods","views",
        "watchers","bids","quantity","relist_count","item_url","photo_urls","notes",
        "last_updated","ebay_item_id"
    ]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA

    # Safe numeric defaults
    for c in ["shipping_cost_seller","ebay_fees","tax_collected","cost_of_goods","relist_count"]:
        df[c] = to_number(df[c]).fillna(0)

    return df[expected]

# ----------------- UI -----------------
st.set_page_config(page_title="eBay Listing Tracker", layout="wide")
st.title("eBay Listing Tracker")

with get_conn() as conn:
    # ---------- SIDEBAR ----------
    with st.sidebar:
        st.header("Data")

        # --- SAFE IMPORT (button + MD5 hash + unique index + INSERT OR IGNORE) ---
        uploaded = st.file_uploader("Import CSV (App template or eBay export)", type=["csv"])

        def _md5_of(b: bytes) -> str:
            h = hashlib.md5()
            h.update(b)
            return h.hexdigest()

        if uploaded is not None:
            file_bytes = uploaded.getvalue()
            file_hash = _md5_of(file_bytes)
            st.caption(f"Selected file: {uploaded.name}")

            if st.button("Import this file"):
                already = conn.execute("SELECT 1 FROM imports WHERE file_hash=?;", (file_hash,)).fetchone()
                if already:
                    st.info("This exact file was already imported. Skipping re-import ✅")
                else:
                    imp = pd.read_csv(BytesIO(file_bytes))
                    ebay_markers = {"Title", "Custom label", "Custom label (SKU)", "Item number", "Item ID", "Listing Status"}
                    if len(ebay_markers.intersection(set(imp.columns))) > 0:
                        df_norm = map_ebay_export_to_schema(imp)
                    else:
                        # Treat as our app template; keep only known columns
                        tbl_cols = list(pd.read_sql_query("PRAGMA table_info(listings);", conn)["name"])
                        keep = [c for c in imp.columns if c in tbl_cols and c != "id"]
                        df_norm = imp[keep].copy()
                        for c in tbl_cols:
                            if c not in df_norm.columns and c != "id":
                                df_norm[c] = pd.NA

                    # Ensure keys exist and are not NULL (unique index uses both)
                    if "ebay_item_id" not in df_norm.columns:
                        df_norm["ebay_item_id"] = pd.NA
                    if "sku" not in df_norm.columns:
                        df_norm["sku"] = pd.NA
                    df_norm["sku"] = df_norm["sku"].fillna("")

                    cols = [c for c in df_norm.columns if c != "id"]
                    placeholders = ",".join(["?"] * len(cols))
                    sql = f"INSERT OR IGNORE INTO listings ({','.join(cols)}) VALUES ({placeholders});"
                    conn.executemany(sql, df_norm[cols].where(pd.notna(df_norm[cols]), None).values.tolist())
                    conn.execute(
                        "INSERT OR IGNORE INTO imports(file_hash, file_name, imported_at) VALUES (?,?,datetime('now'));",
                        (file_hash, uploaded.name),
                    )
                    conn.commit()
                    st.success(f"Imported {len(df_norm)} listings (duplicates ignored). ✅")

        # Export
        exp_df = df_all(conn)
        st.download_button(
            "Export CSV",
            exp_df.to_csv(index=False),
            file_name="listings.csv",
            mime="text/csv"
        )

        st.divider()
        st.caption("Quick Filters")
        status_filter = st.multiselect(
            "Status", ["draft","listed","sold","returned","archived"],
            default=["listed","draft"]
        )
        cat_filter = st.text_input("Category contains...")
        sku_filter = st.text_input("SKU contains...")

    # ---------- MAIN: Left = Add/Edit, Right = Actions/Table ----------
    col1, col2 = st.columns([1, 1])

    # Add / Edit form
    with col1:
        st.subheader("Add or Update Listing")
        mode = st.radio("Mode", ["Add new", "Edit existing"], horizontal=True)
        edit_id = None
        edit_row = None

        if mode == "Edit existing":
            all_rows = df_all(conn)
            if all_rows.empty:
                st.info("No rows yet. Switch to 'Add new'.")
            else:
                choices = all_rows.apply(
                    lambda r: f"[{r['id']}] {r['sku'] or ''} - {r['title'] or ''}", axis=1
                ).tolist()
                pick = st.selectbox("Pick a row to edit", choices)
                try:
                    edit_id = int(pick.split("]")[0][1:])
                    edit_row = all_rows[all_rows["id"] == edit_id].iloc[0].fillna("")
                except Exception:
                    edit_id = None
                    edit_row = None

        def pref(key, default=""):
            if edit_row is not None and key in edit_row.index:
                return edit_row[key] if pd.notna(edit_row[key]) else default
            return default

        with st.form("listing_form"):
            sku = st.text_input("SKU", value=pref("sku"))
            title = st.text_input("Title", value=pref("title"))
            category = st.text_input("Category", value=pref("category"))
            condition = st.text_input("Condition", value=pref("condition"))
            status = st.selectbox(
                "Status",
                ["draft","listed","sold","returned","archived"],
                index=["draft","listed","sold","returned","archived"].index(
                    pref("status", "listed")
                ) if pref("status", "listed") in ["draft","listed","sold","returned","archived"] else 1
            )

            # Date
            existing_list_date = pref("list_date")
            try:
                existing_ld = pd.to_datetime(existing_list_date).date() if existing_list_date else date.today()
            except Exception:
                existing_ld = date.today()
            list_date_val = st.date_input("List date", value=existing_ld)

            list_price = st.number_input("List price", min_value=0.0, step=0.01, value=float(pref("list_price", 0) or 0))
            bin_price  = st.number_input("Buy-It-Now price", min_value=0.0, step=0.01, value=float(pref("bin_price", 0) or 0))
            item_url = st.text_input("Item URL", value=pref("item_url"))
            photo_urls = st.text_area("Photo URLs (comma separated)", value=pref("photo_urls"))
            views = st.number_input("Views", min_value=0, step=1, value=int(pref("views", 0) or 0))
            watchers = st.number_input("Watchers", min_value=0, step=1, value=int(pref("watchers", 0) or 0))
            bids = st.number_input("Bids", min_value=0, step=1, value=int(pref("bids", 0) or 0))
            quantity = st.number_input("Quantity", min_value=1, step=1, value=int(pref("quantity", 1) or 1))
            relist_count = st.number_input("Relist count", min_value=0, step=1, value=int(pref("relist_count", 0) or 0))
            cost_of_goods = st.number_input("Cost of goods", min_value=0.0, step=0.01, value=float(pref("cost_of_goods", 0) or 0))
            notes = st.text_area("Notes", value=pref("notes"))

            submitted = st.form_submit_button("Save")
            if submitted:
                data = dict(
                    sku=sku or None,
                    title=title or None,
                    category=category or None,
                    condition=condition or None,
                    status=status,
                    list_date=str(list_date_val),
                    list_price=float(list_price) if list_price else None,
                    bin_price=float(bin_price) if bin_price else None,
                    item_url=item_url or None,
                    photo_urls=photo_urls or None,
                    views=int(views),
                    watchers=int(watchers),
                    bids=int(bids),
                    quantity=int(quantity),
                    relist_count=int(relist_count),
                    cost_of_goods=float(cost_of_goods or 0.0),
                    notes=notes or None
                )
                # Try to link to shared inventory
                shared_id = find_shared_item_id(sku=data.get('sku'), ebay_item_id=data.get('ebay_item_id'))
                if shared_id:
                    data['shared_item_id'] = shared_id
                    st.info(f"Linked to shared inventory: {shared_id}")
                    # Update shared inventory with sale data
                    update_inventory_item(shared_id, build_shared_update_payload(data))
                else:
                    st.warning("No confident match in shared inventory. Manual linking may be needed.")
                upsert(conn, data, edit_id if mode == "Edit existing" else None)
                st.success("Saved.")

    # Actions, KPIs, Table, Maintenance
    with col2:
        st.subheader("Quick Actions")
        df = df_all(conn)

        # Apply filters
        if not df.empty:
            if status_filter:
                df = df[df["status"].isin(status_filter)]
            if cat_filter:
                df = df[df["category"].fillna("").str.contains(cat_filter, case=False)]
            if sku_filter:
                df = df[df["sku"].fillna("").str.contains(sku_filter, case=False)]

        if df.empty:
            st.info("No rows match.")
        else:
            sel = st.multiselect("Select rows by ID", df["id"].tolist())

            with st.expander("Update metrics / fees / costs"):
                u_views = st.number_input("Add views (+)", 0, step=1, value=0)
                u_watch = st.number_input("Add watchers (+)", 0, step=1, value=0)
                u_bids = st.number_input("Add bids (+)", 0, step=1, value=0)
                u_fees = st.number_input("Set eBay fees (absolute)", 0.0, step=0.01, value=0.0)
                u_ship_seller = st.number_input("Set shipping cost (seller paid)", 0.0, step=0.01, value=0.0)
                u_cogs = st.number_input("Set cost of goods", 0.0, step=0.01, value=0.0)
                if st.button("Apply to selected"):
                    for rid in sel:
                        row = df[df["id"] == rid].iloc[0]
                        data = dict(
                            views=int((row.get("views") or 0) + u_views),
                            watchers=int((row.get("watchers") or 0) + u_watch),
                            bids=int((row.get("bids") or 0) + u_bids),
                            ebay_fees=float(u_fees if u_fees else (row.get("ebay_fees") or 0.0)),
                            shipping_cost_seller=float(u_ship_seller if u_ship_seller else (row.get("shipping_cost_seller") or 0.0)),
                            cost_of_goods=float(u_cogs if u_cogs else (row.get("cost_of_goods") or 0.0)),
                        )
                        upsert(conn, data, rid)
                    st.success("Updated.")

            with st.expander("Mark as sold"):
                sold_price = st.number_input("Sold price", 0.0, step=0.01, value=0.0)
                ship_buyer = st.number_input("Shipping charged to buyer", 0.0, step=0.01, value=0.0)
                buyer = st.text_input("Buyer username")
                order_id = st.text_input("Order ID")
                sold_date_val = st.date_input("Sold date", value=date.today())
                if st.button("Mark selected as sold"):
                    for rid in sel:
                        data = dict(
                            status="sold",
                            sold_price=sold_price,
                            shipping_cost_buyer=ship_buyer,
                            buyer_username=buyer or None,
                            order_id=order_id or None,
                            sold_date=str(sold_date_val),
                        )
                        upsert(conn, data, rid)
                    st.success("Marked as sold.")

            with st.expander("Relist selected"):
                if st.button("Relist"):
                    for rid in sel:
                        row = df[df["id"] == rid].iloc[0]
                        data = dict(
                            status="listed",
                            relist_count=int((row.get("relist_count") or 0)) + 1,
                            list_date=str(date.today())
                        )
                        upsert(conn, data, rid)
                    st.success("Relisted.")

            with st.expander("Delete"):
                if st.button("Delete selected"):
                    if sel:
                        delete_rows(conn, sel)
                        st.success(f"Deleted {len(sel)} row(s).")

            # KPIs (use normalized status)
            k1, k2, k3, k4 = st.columns(4)
            total_listed = int((df["status"] == "listed").sum())
            total_sold = int((df["status"] == "sold").sum())
            gross_sales = float(df.loc[df["status"] == "sold", "sold_price"].fillna(0).sum())
            net_profit = float(
                df.loc[df["status"] == "sold", "sold_price"].fillna(0).sum()
                + df.loc[df["status"] == "sold", "shipping_cost_buyer"].fillna(0).sum()
                - df.loc[df["status"] == "sold", "shipping_cost_seller"].fillna(0).sum()
                - df.loc[df["status"] == "sold", "ebay_fees"].fillna(0).sum()
                - df.loc[df["status"] == "sold", "cost_of_goods"].fillna(0).sum()
            )
            k1.metric("Active Listings", total_listed)
            k2.metric("Sold", total_sold)
            k3.metric("Gross Sales", f"${gross_sales:,.2f}")
            k4.metric("Net Profit", f"${net_profit:,.2f}")

            st.dataframe(df.fillna(""), use_container_width=True)

        # ---------- Maintenance ----------
        st.subheader("Maintenance")
        with st.expander("One-click fixes"):
            col_a, col_b = st.columns(2)

            with col_a:
                if st.button("Fix statuses (set to 'listed' if no sold_date/price)"):
                    conn.execute("""
                        UPDATE listings
                        SET status='listed', last_updated=datetime('now')
                        WHERE (status='sold' OR status IS NULL OR status='')
                          AND (sold_date IS NULL OR sold_date='')
                          AND (sold_price IS NULL OR sold_price=0);
                    """)
                    conn.commit()
                    st.success("Statuses corrected.")

            with col_b:
                if st.button("De-duplicate listings (keep lowest id per (item_id, sku))"):
                    conn.execute(UNIQUE_INDEX)  # ensure index exists
                    conn.execute("""
                        DELETE FROM listings
                        WHERE id NOT IN (
                          SELECT MIN(id)
                          FROM listings
                          GROUP BY ebay_item_id, sku
                        );
                    """)
                    conn.commit()
                    st.success("Duplicates removed.")

        # ---------- Reconciliation ----------
        st.subheader("Reconciliation")
        st.caption("Read-only comparison of ebay_tracker.db against shared_inventory.db.")

        try:
            report = build_reconciliation_report(DB_PATH)
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Unlinked Listings", report["counts"]["unlinked_listings"])
            c2.metric("Linked Mismatches", report["counts"]["linked_sale_state_mismatches"])
            c3.metric("Shared Purchased/RTL Unlinked", report["counts"]["shared_unlinked_purchases"])
            c4.metric("Unique Match Candidates", report["counts"]["unresolved_unique_candidates"])
            c5.metric("Ambiguous Candidates", report["counts"]["ambiguous_candidates"])

            with st.expander("Unlinked listings", expanded=True):
                st.caption("Listings in ebay_tracker with no shared_item_id.")
                st.dataframe(
                    report["unlinked_listings"][
                        [
                            "id",
                            "sku",
                            "title",
                            "status",
                            "list_price",
                            "sold_price",
                            "sold_date",
                            "ebay_item_id",
                            "last_updated",
                        ]
                    ].fillna(""),
                    use_container_width=True,
                )

            with st.expander("Linked listings with sale-state mismatches", expanded=True):
                st.caption("Compares linked listings against shared inventory by shared_item_id.")
                st.dataframe(report["linked_sale_state_mismatches"].fillna(""), use_container_width=True)

            with st.expander("Shared inventory purchased or ready_to_list but never linked", expanded=True):
                st.caption("Shared inventory rows in pre-list states with no matching shared_item_id in listings.")
                st.dataframe(
                    report["shared_unlinked_purchases"][
                        [
                            "item_id",
                            "sku",
                            "title",
                            "purchase_date",
                            "listing_status",
                            "list_price",
                            "sold_price",
                            "ebay_item_id",
                            "updated_at",
                        ]
                    ].fillna(""),
                    use_container_width=True,
                )

            with st.expander("Matching opportunities", expanded=False):
                st.caption("Read-only detection using the current exact-match signals on purchased shared inventory.")
                st.write("Unique candidates")
                st.dataframe(report["unresolved_unique_candidates"].fillna(""), use_container_width=True)
                st.write("Ambiguous candidates")
                st.dataframe(report["ambiguous_candidates"].fillna(""), use_container_width=True)
                st.write("All unlinked listing match scans")
                st.dataframe(report["match_opportunities"].fillna(""), use_container_width=True)

            manual_feedback = st.session_state.pop("manual_link_feedback", None)
            if manual_feedback:
                level, message = manual_feedback
                if level == "success":
                    st.success(message)
                elif level == "error":
                    st.error(message)
                else:
                    st.info(message)

            with st.expander("Manual link one listing", expanded=False):
                unlinked_rows = report["unlinked_listings"]
                if unlinked_rows.empty:
                    st.info("No unlinked listings available for manual linking.")
                else:
                    listing_options = unlinked_rows[["id", "sku", "title", "ebay_item_id"]].copy()
                    listing_ids = listing_options["id"].astype(int).tolist()

                    def _listing_label(listing_id: int) -> str:
                        row = listing_options[listing_options["id"] == listing_id].iloc[0]
                        sku = row["sku"] if pd.notna(row["sku"]) and row["sku"] else "no-sku"
                        ebay_item_id = row["ebay_item_id"] if pd.notna(row["ebay_item_id"]) and row["ebay_item_id"] else "no-ebay-id"
                        title = row["title"] if pd.notna(row["title"]) and row["title"] else "untitled"
                        return f"[{listing_id}] {sku} | {ebay_item_id} | {title}"

                    selected_listing_id = st.selectbox(
                        "Select one unlinked listing",
                        listing_ids,
                        format_func=_listing_label,
                        key="manual_link_listing_id",
                    )

                    try:
                        manual_context = get_manual_link_context(selected_listing_id, DB_PATH)
                        listing_summary_df = pd.DataFrame([manual_context["listing"]])
                        st.caption("Selected listing")
                        st.dataframe(listing_summary_df.fillna(""), use_container_width=True)

                        candidate_cols = [
                            "item_id",
                            "title",
                            "purchase_date",
                            "lot_number",
                            "total_purchase_cost",
                            "sku",
                            "ebay_item_id",
                            "listing_status",
                            "match_reasons",
                            "match_score",
                        ]
                        suggested_candidates = manual_context["suggested_candidates"]
                        fallback_candidates = manual_context["fallback_candidates"]

                        st.caption("Suggested shared inventory candidates")
                        if suggested_candidates.empty:
                            st.info("No suggested candidates were detected from exact SKU, exact eBay item ID, or title overlap.")
                        else:
                            st.dataframe(suggested_candidates[candidate_cols].fillna(""), use_container_width=True)

                        show_additional = st.checkbox(
                            "Show additional eligible shared inventory rows",
                            key="manual_link_show_additional",
                        )
                        if show_additional:
                            st.caption("Additional eligible shared inventory rows (up to 50 recent records)")
                            st.dataframe(fallback_candidates[candidate_cols].fillna(""), use_container_width=True)

                        option_source = suggested_candidates if not suggested_candidates.empty else fallback_candidates
                        combined_candidates = pd.concat([suggested_candidates, fallback_candidates], ignore_index=True)
                        combined_candidates = combined_candidates.drop_duplicates(subset=["item_id"]).reset_index(drop=True)
                        if combined_candidates.empty:
                            st.warning("No eligible shared inventory rows are available for manual linking.")
                        else:
                            candidate_ids = [""] + combined_candidates["item_id"].astype(str).tolist()

                            def _candidate_label(item_id: str) -> str:
                                if not item_id:
                                    return "Select a shared inventory record"
                                row = combined_candidates[combined_candidates["item_id"] == item_id].iloc[0]
                                cost = row["total_purchase_cost"]
                                cost_text = f"${float(cost):,.2f}" if pd.notna(cost) else "n/a"
                                reasons = row["match_reasons"] if pd.notna(row["match_reasons"]) and row["match_reasons"] else "manual_review"
                                lot_number = row["lot_number"] if pd.notna(row["lot_number"]) and row["lot_number"] else "no-lot"
                                purchase_date = row["purchase_date"] if pd.notna(row["purchase_date"]) and row["purchase_date"] else "no-date"
                                title = row["title"] if pd.notna(row["title"]) and row["title"] else "untitled"
                                return f"{item_id} | {purchase_date} | {lot_number} | {cost_text} | {reasons} | {title}"

                            selected_shared_item_id = st.selectbox(
                                "Choose the shared inventory record to link",
                                candidate_ids,
                                format_func=_candidate_label,
                                key="manual_link_shared_item_id",
                            )
                            sync_shared = st.checkbox(
                                "Sync current listing sale/list data to shared inventory after linking",
                                value=True,
                                key="manual_link_sync_shared",
                            )
                            confirm_manual_link = st.checkbox(
                                "I confirm that this listing and shared inventory record refer to the same item",
                                key="manual_link_confirm",
                            )
                            action_col1, action_col2 = st.columns(2)
                            with action_col1:
                                if st.button("Confirm manual link", key="manual_link_confirm_button"):
                                    if not selected_shared_item_id:
                                        st.warning("Invalid selection: choose a shared inventory record.")
                                    elif not confirm_manual_link:
                                        st.warning("Explicit confirmation is required before assigning shared_item_id.")
                                    else:
                                        ok, message = manual_link_listing(
                                            conn,
                                            int(selected_listing_id),
                                            selected_shared_item_id,
                                            sync_shared=sync_shared,
                                        )
                                        st.session_state["manual_link_feedback"] = ("success" if ok else "error", message)
                                        st.rerun()
                            with action_col2:
                                if st.button("Cancel", key="manual_link_cancel_button"):
                                    st.info("Manual link canceled.")
                    except ValueError as exc:
                        st.error(str(exc))

            st.caption(
                f"Compared listing data from {report['ebay_db_path']} against shared inventory at {report['shared_db_path']}."
            )
        except FileNotFoundError as exc:
            st.warning(str(exc))

