from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pandas as pd

from shared_db import DB_PATH as SHARED_DB_PATH, get_item_by_id, update_inventory_item


EBAY_DB_PATH = Path("ebay_tracker.db")


STATUS_TO_SHARED_STATUS = {
    "draft": "ready_to_list",
    "listed": "listed",
    "sold": "sold",
    "returned": "closed",
    "archived": "closed",
}


def _text(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _tokenize_title(value) -> set[str]:
    text = _text(value)
    if text is None:
        return set()
    cleaned = []
    for ch in text.lower():
        cleaned.append(ch if ch.isalnum() else " ")
    return {token for token in "".join(cleaned).split() if len(token) >= 3}


def _shared_status(status) -> str | None:
    normalized = _text(status)
    if normalized is None:
        return None
    return STATUS_TO_SHARED_STATUS.get(normalized.lower(), normalized.lower())


def build_shared_update_payload(listing_row: dict) -> dict:
    return {
        "listing_status": _shared_status(listing_row.get("status")),
        "list_date": _text(listing_row.get("list_date")),
        "list_price": listing_row.get("list_price"),
        "sold_price": listing_row.get("sold_price"),
        "sold_date": _text(listing_row.get("sold_date")),
        "shipping_cost": float(listing_row.get("shipping_cost_seller") or 0.0),
        "marketplace_fees": float(listing_row.get("ebay_fees") or 0.0),
        "ebay_item_id": _text(listing_row.get("ebay_item_id")),
        "sku": _text(listing_row.get("sku")),
    }


def _fetch_listing_row(conn: sqlite3.Connection, listing_id: int) -> dict | None:
    cur = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,))
    row = cur.fetchone()
    if row is None:
        return None
    cols = [desc[0] for desc in cur.description]
    return dict(zip(cols, row))


def _read_df(db_path: Path, query: str, params: tuple = ()) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_manual_link_context(
    listing_id: int,
    ebay_db_path: Path | str = EBAY_DB_PATH,
    shared_db_path: Path | str = SHARED_DB_PATH,
) -> dict[str, pd.DataFrame | dict]:
    ebay_db_path = Path(ebay_db_path)
    shared_db_path = Path(shared_db_path)

    listing_df = _read_df(ebay_db_path, "SELECT * FROM listings WHERE id = ?", (listing_id,))
    if listing_df.empty:
        raise ValueError("Listing not found.")

    listing = listing_df.iloc[0].to_dict()
    linked_ids_df = _read_df(
        ebay_db_path,
        "SELECT shared_item_id FROM listings WHERE id != ? AND shared_item_id IS NOT NULL AND TRIM(shared_item_id) != ''",
        (listing_id,),
    )
    linked_ids = tuple(linked_ids_df["shared_item_id"].dropna().astype(str).tolist())

    inventory_df = _read_df(
        shared_db_path,
        """
        SELECT item_id, title, purchase_date, lot_number, total_purchase_cost, sku, ebay_item_id, listing_status, updated_at
        FROM inventory
        WHERE listing_status IN ('purchased', 'ready_to_list')
        ORDER BY purchase_date DESC, updated_at DESC, item_id
        """,
    )
    if linked_ids:
        inventory_df = inventory_df[~inventory_df["item_id"].isin(linked_ids)].copy()

    listing_sku = _text(listing.get("sku"))
    listing_ebay_item_id = _text(listing.get("ebay_item_id"))
    listing_title_tokens = _tokenize_title(listing.get("title"))

    reasons = []
    scores = []
    for row in inventory_df.itertuples(index=False):
        row_reasons = []
        score = 0

        row_sku = _text(getattr(row, "sku", None))
        row_ebay_item_id = _text(getattr(row, "ebay_item_id", None))
        row_title_tokens = _tokenize_title(getattr(row, "title", None))

        if listing_sku is not None and listing_sku == row_sku:
            row_reasons.append("sku_exact")
            score += 3

        if listing_ebay_item_id is not None and listing_ebay_item_id == row_ebay_item_id:
            row_reasons.append("ebay_item_id_exact")
            score += 3

        overlap = listing_title_tokens.intersection(row_title_tokens)
        if len(overlap) >= 2:
            row_reasons.append("title_overlap")
            score += 1

        reasons.append(", ".join(row_reasons))
        scores.append(score)

    inventory_df = inventory_df.copy()
    inventory_df["match_reasons"] = reasons
    inventory_df["match_score"] = scores

    suggested_candidates = inventory_df[inventory_df["match_score"] > 0].copy()
    suggested_candidates = suggested_candidates.sort_values(
        ["match_score", "purchase_date", "item_id"], ascending=[False, False, True]
    )

    fallback_candidates = inventory_df.sort_values(
        ["purchase_date", "updated_at", "item_id"], ascending=[False, False, True]
    ).head(50)

    listing_summary = {
        "id": listing.get("id"),
        "title": listing.get("title"),
        "status": listing.get("status"),
        "list_price": listing.get("list_price"),
        "sold_price": listing.get("sold_price"),
        "sold_date": listing.get("sold_date"),
        "sku": listing.get("sku"),
        "ebay_item_id": listing.get("ebay_item_id"),
        "shared_item_id": listing.get("shared_item_id"),
    }

    return {
        "listing": listing_summary,
        "listing_row": listing,
        "suggested_candidates": suggested_candidates,
        "fallback_candidates": fallback_candidates,
    }


def manual_link_listing(
    conn: sqlite3.Connection,
    listing_id: int,
    shared_item_id: str,
    *,
    sync_shared: bool = True,
) -> tuple[bool, str]:
    shared_item_id = (shared_item_id or "").strip()
    if not shared_item_id:
        return False, "Invalid selection: choose a shared inventory record."

    listing_row = _fetch_listing_row(conn, listing_id)
    if listing_row is None:
        return False, "Invalid selection: listing not found."

    if _text(listing_row.get("shared_item_id")) is not None:
        return False, "Invalid selection: listing is already linked."

    shared_row = get_item_by_id(shared_item_id)
    if shared_row is None:
        return False, "Invalid selection: shared inventory record not found."

    existing_link = conn.execute(
        "SELECT id FROM listings WHERE shared_item_id = ? AND id != ?",
        (shared_item_id, listing_id),
    ).fetchone()
    if existing_link is not None:
        return False, "Invalid selection: shared inventory record is already linked to another listing."

    if shared_row.get("listing_status") not in {"purchased", "ready_to_list"}:
        return False, "Invalid selection: shared inventory record must be in purchased or ready_to_list state."

    payload = build_shared_update_payload(listing_row)
    now = dt.datetime.now().isoformat(timespec="seconds")

    try:
        conn.execute("BEGIN")
        cur = conn.execute(
            """
            UPDATE listings
            SET shared_item_id = ?, last_updated = ?
            WHERE id = ? AND (shared_item_id IS NULL OR TRIM(shared_item_id) = '')
            """,
            (shared_item_id, now, listing_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return False, "Invalid selection: listing could not be linked."

        if sync_shared:
            update_inventory_item(shared_item_id, payload)

        conn.commit()
    except Exception as exc:
        conn.rollback()
        return False, f"Manual link failed: {exc}"

    return True, f"Linked successfully: listing {listing_id} -> {shared_item_id}."
