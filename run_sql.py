import sqlite3, os
db = os.getenv("EBT_SQLITE_PATH", "ebay_tracker.db")
con = sqlite3.connect(db)
con.executescript("""
DROP VIEW IF EXISTS listings_for_sync;
CREATE VIEW listings_for_sync AS
SELECT
  id, sku, title, status, list_price, sold_price, ebay_item_id,
  CASE
    WHEN last_updated IS NOT NULL AND last_updated <> '' THEN last_updated
    WHEN sold_date    IS NOT NULL AND sold_date    <> '' THEN sold_date
    WHEN list_date    IS NOT NULL AND list_date    <> '' THEN list_date
    ELSE NULL
  END AS updated_at
FROM listings;
""")
con.close()
print(" View created: listings_for_sync")
