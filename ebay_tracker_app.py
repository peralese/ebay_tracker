# ebay_tracker_app.py
# Full drop-in replacement with robust eBay CSV import (Option A)
import sqlite3
import pandas as pd
import datetime as dt
from datetime import date
import streamlit as st
from pathlib import Path

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
  ebay_item_id TEXT
);
"""

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(SCHEMA)
    return conn

def df_all(conn):
    df = pd.read_sql_query("SELECT * FROM listings ORDER BY id DESC;", conn)
    if not df.empty:
        # Computed net_profit for display/export convenience
        df["net_profit"] = (
            df["sold_price"].fillna(0)
            + df["shipping_cost_buyer"].fillna(0)
            - df["shipping_cost_seller"].fillna(0)
            - df["ebay_fees"].fillna(0)
            - df["cost_of_goods"].fillna(0)
        )
    return df

def upsert(conn, data: dict, row_id: int | None):
    # Ensure last_updated is always set for inserts/updates
    data = dict(data)  # shallow copy so we don't mutate caller
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

def delete_rows(conn, ids):
    if not ids:
        return
    q = "DELETE FROM listings WHERE id IN ({})".format(",".join(["?"]*len(ids)))
    conn.execute(q, ids)
    conn.commit()

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
    # pick best match or return original
    return mapping.get(s, s)

def map_ebay_export_to_schema(imp: pd.DataFrame) -> pd.DataFrame:
    """
    Accepts common eBay Seller Hub CSV exports (Active/Sold/etc.)
    and maps columns to our schema. Unknown columns are ignored.
    """
    # Trim header whitespace
    # Build a case-insensitive lookup
    cols_lower = {c.lower(): c for c in imp.columns}

    def pick(cands):
        for c in cands:
            if c.lower() in cols_lower:
                return imp[cols_lower[c.lower()]]
        return None

    colmap = {
        "ebay_item_id": ["Item number", "Item ID", "ItemID", "Item Id"],
        "sku": ["Custom label (SKU)", "Custom label", "Custom Label (SKU)", "CustomLabel", "SKU"],
        "title": ["Title"],
        "category": ["Category", "Category Name", "Primary Category"],  # may be absent in this export
        "status": ["Status", "Listing Status", "Result"],               # absent -> we'll default to 'listed'
        "list_date": ["Start date", "Start Date", "Start time", "Start Time", "Creation Date"],
        "list_price": ["Current price", "Start price", "Start Price", "Price"],
        "bin_price": ["Auction Buy It Now price", "Buy It Now Price", "BIN Price", "Buy It Now price"],
        "views": ["Views", "View Count"],
        "watchers": ["Watchers"],
        "bids": ["Bids"],
        "quantity": ["Available quantity", "Quantity", "Quantity Available", "Quantity Listed"],
        "item_url": ["Item URL", "URL", "View Item URL", "Item URL link"],  # often absent in this report
        "sold_price": ["Sold Price", "Sold For", "Total price", "Total Price", "Price (total)"],
        "sold_date": ["Sale Date", "Paid On", "Order Date", "End Date", "End date", "End time", "End Time", "End Time (GMT)"],
        "buyer_username": ["Buyer User ID", "Buyer Username", "Buyer ID", "Buyer"],
        "order_id": ["Order ID", "Sales Record Number", "Sales Record #", "Record number", "Order id"],
        "shipping_cost_buyer": ["Shipping And Handling", "Shipping charged to buyer", "Postage and packaging - paid by buyer", "Shipping paid by buyer"],
        "notes": ["Notes", "Private notes"],
    }

    data = {}
    for our, cands in colmap.items():
        v = pick(cands)
        if v is not None:
            data[our] = v

    df = pd.DataFrame(data)


    def pick(cands):
        for c in cands:
            if c in imp.columns:
                return imp[c]
        return None

    data = {}
    for our, cands in colmap.items():
        col = pick(cands)
        if col is not None:
            data[our] = col

    df = pd.DataFrame(data)

    # Type cleanup and normalization
    for c in ["list_price", "bin_price", "sold_price", "shipping_cost_buyer"]:
        if c in df.columns:
            df[c] = to_number(df[c])

    for c in ["views", "watchers", "bids", "quantity"]:
        if c in df.columns:
            df[c] = to_number(df[c]).fillna(0).astype("Int64")

    if "list_date" in df.columns:
        df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce").dt.date.astype("string")

    if "sold_date" in df.columns:
        df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce").dt.date.astype("string")

    if "status" in df.columns:
        df["status"] = df["status"].map(normalize_status)

    # Infer status if not provided but sold columns exist
    if "status" not in df.columns:
        df["status"] = None
    if "sold_price" in df.columns:
        df.loc[df["sold_price"].fillna(0) > 0, "status"] = "sold"
    if "sold_date" in df.columns:
        df.loc[df["sold_date"].notna(), "status"] = "sold"
    df["status"] = df["status"].fillna("listed")

    # Ensure our full schema columns exist (except id)
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

    # Safe defaults to avoid null math errors later
    for c in ["shipping_cost_seller","ebay_fees","tax_collected","cost_of_goods","relist_count"]:
        df[c] = to_number(df[c]).fillna(0)

    return df[expected]

st.set_page_config(page_title="eBay Listing Tracker", layout="wide")
st.title("eBay Listing Tracker")

with get_conn() as conn:

    # ---------- SIDEBAR ----------
    with st.sidebar:
        st.header("Data")

        # Import: our template or eBay Seller Hub CSV
        uploaded = st.file_uploader("Import CSV (App template or eBay export)", type=["csv"])
        if uploaded is not None:
            imp = pd.read_csv(uploaded)
            # If CSV already matches our schema (template), keep as-is.
            expected_cols = {c for c in pd.read_sql_query("PRAGMA table_info(listings);", conn)["name"]}
            if set(imp.columns) & {"Title", "Custom label", "Item ID", "Listing Status"}:
                # Looks like an eBay export -> map it
                df_norm = map_ebay_export_to_schema(imp)
            else:
                # Assume it's our template; drop unknowns and keep known columns
                keep = [c for c in imp.columns if c in expected_cols and c != "id"]
                df_norm = imp[keep].copy()
                # Ensure all expected columns exist
                for col in expected_cols:
                    if col not in df_norm.columns and col != "id":
                        df_norm[col] = pd.NA

            rows = df_norm.to_dict(orient="records")
            # Upsert (insert) each row; duplicates are not deduped at this stage
            for row in rows:
                row.pop("id", None)
                upsert(conn, row, None)
            st.success(f"Imported {len(rows)} listings.")

        # Export (always available)
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
        cat_filter = st.text_input("Category contains…")
        sku_filter = st.text_input("SKU contains…")

    # ---------- MAIN: Left = Add/Edit, Right = Actions/Table ----------
    col1, col2 = st.columns([1,1])

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
                    lambda r: f"[{r['id']}] {r['sku'] or ''} – {r['title'] or ''}",
                    axis=1
                ).tolist()
                pick = st.selectbox("Pick a row to edit", choices)
                try:
                    edit_id = int(pick.split("]")[0][1:])
                    edit_row = all_rows[all_rows["id"] == edit_id].iloc[0].fillna("")
                except Exception:
                    edit_id = None
                    edit_row = None

        # Prefill fields in edit mode
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
                "Status", ["draft","listed","sold","returned","archived"],
                index=["draft","listed","sold","returned","archived"].index(pref("status","listed")) if pref("status","listed") in ["draft","listed","sold","returned","archived"] else 1
            )
            # Parse existing date if present
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
                upsert(conn, data, edit_id if mode == "Edit existing" else None)
                st.success("Saved.")

    # Actions, KPIs, and Table
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

            # KPIs
            k1, k2, k3, k4 = st.columns(4)
            total_listed = int((df["status"] == "listed").sum())
            total_sold = int((df["status"] == "sold").sum())
            gross_sales = float(df.loc[df["status"]=="sold", "sold_price"].fillna(0).sum())
            net_profit = float(
                df.loc[df["status"]=="sold", "sold_price"].fillna(0).sum()
                + df.loc[df["status"]=="sold", "shipping_cost_buyer"].fillna(0).sum()
                - df.loc[df["status"]=="sold", "shipping_cost_seller"].fillna(0).sum()
                - df.loc[df["status"]=="sold", "ebay_fees"].fillna(0).sum()
                - df.loc[df["status"]=="sold", "cost_of_goods"].fillna(0).sum()
            )
            k1.metric("Active Listings", total_listed)
            k2.metric("Sold", total_sold)
            k3.metric("Gross Sales", f"${gross_sales:,.2f}")
            k4.metric("Net Profit", f"${net_profit:,.2f}")

            st.dataframe(df.fillna(""), use_container_width=True)
