import sqlite3



LISTINGS_SCHEMA = """
CREATE TABLE listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sku TEXT,
  title TEXT,
  status TEXT,
  list_date TEXT,
  list_price REAL,
  sold_price REAL,
  sold_date TEXT,
  ebay_item_id TEXT,
  shared_item_id TEXT,
  last_updated TEXT
);
"""


INVENTORY_SCHEMA = """
CREATE TABLE inventory (
  item_id TEXT PRIMARY KEY,
  sku TEXT,
  title TEXT NOT NULL,
  purchase_date TEXT,
  listing_status TEXT,
  list_date TEXT,
  list_price REAL,
  sold_price REAL,
  sold_date TEXT,
  ebay_item_id TEXT,
  updated_at TEXT
);
"""


def test_build_reconciliation_report(tmp_path):
    from reconciliation import build_reconciliation_report

    ebay_db = tmp_path / "ebay_tracker.db"
    shared_db = tmp_path / "shared_inventory.db"

    with sqlite3.connect(ebay_db) as conn:
        conn.execute(LISTINGS_SCHEMA)
        conn.executemany(
            """
            INSERT INTO listings(id, sku, title, status, list_date, list_price, sold_price, sold_date,
                                 ebay_item_id, shared_item_id, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "SKU-1",
                    "Linked sold item",
                    "sold",
                    "2026-03-20",
                    100.0,
                    120.0,
                    "2026-03-21",
                    "EBAY-1",
                    "AUC-1",
                    "2026-03-22T10:00:00",
                ),
                (
                    2,
                    "SKU-2",
                    "Unlinked with unique candidate",
                    "listed",
                    "2026-03-20",
                    40.0,
                    None,
                    None,
                    None,
                    None,
                    "2026-03-22T10:05:00",
                ),
                (
                    3,
                    "SKU-3",
                    "Unlinked ambiguous",
                    "listed",
                    "2026-03-20",
                    55.0,
                    None,
                    None,
                    None,
                    None,
                    "2026-03-22T10:10:00",
                ),
            ],
        )
        conn.commit()

    with sqlite3.connect(shared_db) as conn:
        conn.execute(INVENTORY_SCHEMA)
        conn.executemany(
            """
            INSERT INTO inventory(item_id, sku, title, purchase_date, listing_status, list_date, list_price,
                                  sold_price, sold_date, ebay_item_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "AUC-1",
                    "SKU-1",
                    "Linked sold item",
                    "2026-03-18",
                    "listed",
                    "2026-03-20",
                    95.0,
                    120.0,
                    "2026-03-21",
                    "EBAY-9",
                    "2026-03-22T10:00:00",
                ),
                (
                    "AUC-2",
                    "SKU-2",
                    "Unlinked with unique candidate",
                    "2026-03-19",
                    "purchased",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "2026-03-22T10:01:00",
                ),
                (
                    "AUC-3A",
                    "SKU-3",
                    "Unlinked ambiguous A",
                    "2026-03-19",
                    "purchased",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "2026-03-22T10:01:00",
                ),
                (
                    "AUC-3B",
                    "SKU-3",
                    "Unlinked ambiguous B",
                    "2026-03-19",
                    "purchased",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "2026-03-22T10:01:00",
                ),
                (
                    "AUC-4",
                    "SKU-4",
                    "Purchased but never linked",
                    "2026-03-19",
                    "ready_to_list",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "2026-03-22T10:01:00",
                ),
            ],
        )
        conn.commit()

    report = build_reconciliation_report(ebay_db, shared_db)

    assert report["counts"] == {
        "unlinked_listings": 2,
        "linked_sale_state_mismatches": 1,
        "shared_unlinked_purchases": 4,
        "unresolved_unique_candidates": 1,
        "ambiguous_candidates": 1,
    }

    mismatch_row = report["linked_sale_state_mismatches"].iloc[0]
    assert mismatch_row["shared_item_id"] == "AUC-1"
    assert mismatch_row["mismatch_fields"] == "status, list_price, ebay_item_id"

    unique_candidate = report["unresolved_unique_candidates"].iloc[0]
    assert unique_candidate["id"] == 2
    assert unique_candidate["candidate_item_ids"] == "AUC-2"

    ambiguous_candidate = report["ambiguous_candidates"].iloc[0]
    assert ambiguous_candidate["id"] == 3
    assert ambiguous_candidate["candidate_count"] == 2
