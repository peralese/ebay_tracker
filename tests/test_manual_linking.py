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
  shipping_cost_seller REAL,
  ebay_fees REAL,
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
  lot_number TEXT,
  total_purchase_cost REAL,
  listing_status TEXT,
  list_date TEXT,
  list_price REAL,
  sold_price REAL,
  sold_date TEXT,
  shipping_cost REAL,
  marketplace_fees REAL,
  ebay_item_id TEXT,
  updated_at TEXT
);
"""


def test_get_manual_link_context_scores_candidates(tmp_path):
    from manual_linking import get_manual_link_context

    ebay_db = tmp_path / "ebay_tracker.db"
    shared_db = tmp_path / "shared_inventory.db"

    with sqlite3.connect(ebay_db) as conn:
        conn.execute(LISTINGS_SCHEMA)
        conn.execute(
            """
            INSERT INTO listings(id, sku, title, status, list_date, list_price, sold_price, sold_date,
                                 shipping_cost_seller, ebay_fees, ebay_item_id, shared_item_id, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 'SKU-100', 'Vintage Sony Radio', 'listed', '2026-03-20', 85.0, None, None, 0.0, 0.0, 'EBAY-100', None, '2026-03-22T10:00:00'),
        )
        conn.execute(
            "INSERT INTO listings(id, shared_item_id) VALUES (?, ?)",
            (2, 'AUC-LINKED'),
        )
        conn.commit()

    with sqlite3.connect(shared_db) as conn:
        conn.execute(INVENTORY_SCHEMA)
        conn.executemany(
            """
            INSERT INTO inventory(item_id, sku, title, purchase_date, lot_number, total_purchase_cost,
                                  listing_status, ebay_item_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ('AUC-100', 'SKU-100', 'Vintage Sony Radio', '2026-03-18', 'LOT-1', 42.5, 'purchased', None, '2026-03-22T10:00:00'),
                ('AUC-101', None, 'Vintage Sony Radio', '2026-03-17', 'LOT-2', 39.0, 'ready_to_list', 'EBAY-100', '2026-03-22T09:00:00'),
                ('AUC-LINKED', 'SKU-999', 'Already linked item', '2026-03-16', 'LOT-9', 10.0, 'purchased', None, '2026-03-22T08:00:00'),
            ],
        )
        conn.commit()

    context = get_manual_link_context(1, ebay_db, shared_db)

    suggested = context['suggested_candidates']
    assert suggested['item_id'].tolist() == ['AUC-100', 'AUC-101']
    assert 'AUC-LINKED' not in context['fallback_candidates']['item_id'].tolist()
    assert set(context['listing'].keys()) >= {'id', 'title', 'sku', 'ebay_item_id'}


def test_manual_link_listing_updates_both_dbs(tmp_path, monkeypatch):
    import shared_db
    from manual_linking import manual_link_listing

    ebay_db = tmp_path / "ebay_tracker.db"
    shared_db_path = tmp_path / "shared_inventory.db"
    monkeypatch.setattr(shared_db, 'DB_PATH', shared_db_path)

    with sqlite3.connect(ebay_db) as conn:
        conn.execute(LISTINGS_SCHEMA)
        conn.execute(
            """
            INSERT INTO listings(id, sku, title, status, list_date, list_price, sold_price, sold_date,
                                 shipping_cost_seller, ebay_fees, ebay_item_id, shared_item_id, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 'SKU-200', 'Camera Lens', 'sold', '2026-03-20', 120.0, 150.0, '2026-03-21', 12.0, 18.0, 'EBAY-200', None, '2026-03-22T10:00:00'),
        )
        conn.commit()

        with sqlite3.connect(shared_db_path) as shared_conn:
            shared_conn.execute(INVENTORY_SCHEMA)
            shared_conn.execute(
                """
                INSERT INTO inventory(item_id, sku, title, purchase_date, lot_number, total_purchase_cost,
                                      listing_status, ebay_item_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ('AUC-200', 'SKU-OLD', 'Camera Lens', '2026-03-18', 'LOT-20', 70.0, 'purchased', None, '2026-03-22T09:00:00'),
            )
            shared_conn.commit()

        ok, message = manual_link_listing(conn, 1, 'AUC-200', sync_shared=True)
        assert ok is True
        assert 'Linked successfully' in message

        row = conn.execute('SELECT shared_item_id FROM listings WHERE id = 1').fetchone()
        assert row[0] == 'AUC-200'

    with sqlite3.connect(shared_db_path) as shared_conn:
        row = shared_conn.execute(
            'SELECT listing_status, list_price, sold_price, sold_date, shipping_cost, marketplace_fees, ebay_item_id, sku FROM inventory WHERE item_id = ?',
            ('AUC-200',),
        ).fetchone()
        assert row == ('sold', 120.0, 150.0, '2026-03-21', 12.0, 18.0, 'EBAY-200', 'SKU-200')
