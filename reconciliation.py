from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from shared_db import DB_PATH as SHARED_DB_PATH


EBAY_DB_PATH = Path("ebay_tracker.db")

LISTING_STATUS_TO_SHARED_STATUS = {
    "draft": "ready_to_list",
    "listed": "listed",
    "sold": "sold",
    "returned": "closed",
    "archived": "closed",
}

LISTING_COLUMNS = [
    "id",
    "sku",
    "title",
    "status",
    "list_date",
    "list_price",
    "sold_price",
    "sold_date",
    "ebay_item_id",
    "shared_item_id",
    "last_updated",
]

INVENTORY_COLUMNS = [
    "item_id",
    "sku",
    "title",
    "purchase_date",
    "listing_status",
    "list_date",
    "list_price",
    "sold_price",
    "sold_date",
    "ebay_item_id",
    "updated_at",
]


def _read_df(db_path: Path, query: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(query, conn)


def _text(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _number(value) -> float | None:
    if pd.isna(value) or value in ("", None):
        return None
    return round(float(value), 2)


def _date(value) -> str | None:
    text = _text(value)
    if text is None:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text
    return parsed.date().isoformat()


def _expected_shared_status(status) -> str | None:
    normalized = _text(status)
    if normalized is None:
        return None
    return LISTING_STATUS_TO_SHARED_STATUS.get(normalized.lower(), normalized.lower())


def _normalize_text_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([None] * len(df), index=df.index, dtype="object")
    return df[column].map(_text)


def _linked_listings(listings: pd.DataFrame, inventory: pd.DataFrame) -> pd.DataFrame:
    linked = listings[_normalize_text_column(listings, "shared_item_id").notna()].copy()
    if linked.empty:
        return linked
    return linked.merge(
        inventory,
        how="left",
        left_on="shared_item_id",
        right_on="item_id",
        suffixes=("_listing", "_shared"),
        indicator=True,
    )


def _collect_mismatches(row: pd.Series) -> list[str]:
    mismatches: list[str] = []
    if row.get("_merge") != "both":
        return ["missing_shared_record"]

    expected_status = _expected_shared_status(row.get("status"))
    shared_status = _text(row.get("listing_status"))
    if expected_status != shared_status:
        mismatches.append("status")

    if _number(row.get("list_price_listing")) != _number(row.get("list_price_shared")):
        mismatches.append("list_price")

    if _number(row.get("sold_price_listing")) != _number(row.get("sold_price_shared")):
        mismatches.append("sold_price")

    if _date(row.get("sold_date_listing")) != _date(row.get("sold_date_shared")):
        mismatches.append("sold_date")

    if _text(row.get("ebay_item_id_listing")) != _text(row.get("ebay_item_id_shared")):
        mismatches.append("ebay_item_id")

    return mismatches


def _match_candidates(unlinked: pd.DataFrame, inventory: pd.DataFrame) -> pd.DataFrame:
    if unlinked.empty:
        return pd.DataFrame(
            columns=[
                "id",
                "sku",
                "title",
                "ebay_item_id",
                "sku_match_count",
                "ebay_item_id_match_count",
                "candidate_count",
                "candidate_item_ids",
                "match_state",
            ]
        )

    purchasable = inventory[_normalize_text_column(inventory, "listing_status") == "purchased"].copy()
    purchasable["sku_norm"] = _normalize_text_column(purchasable, "sku")
    purchasable["ebay_item_id_norm"] = _normalize_text_column(purchasable, "ebay_item_id")

    rows = []
    for row in unlinked.itertuples(index=False):
        sku = _text(getattr(row, "sku", None))
        ebay_item_id = _text(getattr(row, "ebay_item_id", None))

        sku_matches = []
        if sku is not None:
            sku_matches = purchasable.loc[purchasable["sku_norm"] == sku, "item_id"].dropna().tolist()

        ebay_matches = []
        if ebay_item_id is not None:
            ebay_matches = purchasable.loc[
                purchasable["ebay_item_id_norm"] == ebay_item_id, "item_id"
            ].dropna().tolist()

        candidate_item_ids = sorted(set(sku_matches + ebay_matches))
        if len(candidate_item_ids) == 1:
            match_state = "unique_candidate"
        elif len(candidate_item_ids) > 1:
            match_state = "ambiguous"
        else:
            match_state = "no_candidate"

        rows.append(
            {
                "id": getattr(row, "id", None),
                "sku": sku,
                "title": _text(getattr(row, "title", None)),
                "ebay_item_id": ebay_item_id,
                "sku_match_count": len(set(sku_matches)),
                "ebay_item_id_match_count": len(set(ebay_matches)),
                "candidate_count": len(candidate_item_ids),
                "candidate_item_ids": ", ".join(candidate_item_ids),
                "match_state": match_state,
            }
        )

    return pd.DataFrame(rows)


def build_reconciliation_report(
    ebay_db_path: Path | str = EBAY_DB_PATH,
    shared_db_path: Path | str = SHARED_DB_PATH,
) -> dict[str, pd.DataFrame | dict[str, int] | str]:
    ebay_db_path = Path(ebay_db_path)
    shared_db_path = Path(shared_db_path)

    if not ebay_db_path.exists():
        raise FileNotFoundError(f"eBay tracker DB not found: {ebay_db_path}")
    if not shared_db_path.exists():
        raise FileNotFoundError(f"Shared inventory DB not found: {shared_db_path}")

    listings = _read_df(ebay_db_path, "SELECT * FROM listings ORDER BY id DESC")
    inventory = _read_df(shared_db_path, "SELECT * FROM inventory ORDER BY purchase_date DESC, item_id")

    for column in LISTING_COLUMNS:
        if column not in listings.columns:
            listings[column] = pd.NA
    for column in INVENTORY_COLUMNS:
        if column not in inventory.columns:
            inventory[column] = pd.NA

    listings = listings[LISTING_COLUMNS].copy()
    inventory = inventory[INVENTORY_COLUMNS].copy()

    shared_item_ids = _normalize_text_column(listings, "shared_item_id")
    unlinked = listings[shared_item_ids.isna()].copy()

    linked = _linked_listings(listings, inventory)
    if linked.empty:
        linked_mismatches = pd.DataFrame(
            columns=[
                "id",
                "sku_listing",
                "title_listing",
                "shared_item_id",
                "status",
                "listing_status",
                "list_price_listing",
                "list_price_shared",
                "sold_price_listing",
                "sold_price_shared",
                "sold_date_listing",
                "sold_date_shared",
                "ebay_item_id_listing",
                "ebay_item_id_shared",
                "mismatch_fields",
            ]
        )
    else:
        linked["mismatch_fields"] = linked.apply(_collect_mismatches, axis=1)
        linked["mismatch_count"] = linked["mismatch_fields"].map(len)
        linked_mismatches = linked[linked["mismatch_count"] > 0].copy()
        linked_mismatches["mismatch_fields"] = linked_mismatches["mismatch_fields"].map(", ".join)
        linked_mismatches = linked_mismatches[
            [
                "id",
                "sku_listing",
                "title_listing",
                "shared_item_id",
                "status",
                "listing_status",
                "list_price_listing",
                "list_price_shared",
                "sold_price_listing",
                "sold_price_shared",
                "sold_date_listing",
                "sold_date_shared",
                "ebay_item_id_listing",
                "ebay_item_id_shared",
                "mismatch_fields",
            ]
        ]

    linked_ids = set(shared_item_ids.dropna().tolist())
    shared_unlinked = inventory[
        _normalize_text_column(inventory, "listing_status").isin(["purchased", "ready_to_list"])
        & ~_normalize_text_column(inventory, "item_id").isin(linked_ids)
    ].copy()

    opportunities = _match_candidates(unlinked, inventory)
    unique_candidates = opportunities[opportunities["match_state"] == "unique_candidate"].copy()
    ambiguous_candidates = opportunities[opportunities["match_state"] == "ambiguous"].copy()

    counts = {
        "unlinked_listings": int(len(unlinked)),
        "linked_sale_state_mismatches": int(len(linked_mismatches)),
        "shared_unlinked_purchases": int(len(shared_unlinked)),
        "unresolved_unique_candidates": int(len(unique_candidates)),
        "ambiguous_candidates": int(len(ambiguous_candidates)),
    }

    return {
        "counts": counts,
        "unlinked_listings": unlinked.sort_values(["last_updated", "id"], ascending=[False, False]),
        "linked_sale_state_mismatches": linked_mismatches.sort_values("id", ascending=False),
        "shared_unlinked_purchases": shared_unlinked.sort_values(
            ["purchase_date", "item_id"], ascending=[False, True]
        ),
        "unresolved_unique_candidates": unique_candidates.sort_values("id", ascending=False),
        "ambiguous_candidates": ambiguous_candidates.sort_values("id", ascending=False),
        "match_opportunities": opportunities.sort_values("id", ascending=False),
        "ebay_db_path": str(ebay_db_path),
        "shared_db_path": str(shared_db_path),
    }
