import sqlite3

conn = sqlite3.connect("ebay_tracker.db")
cur = conn.cursor()

# Make sure the unique index exists first (same as in app)
cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS ux_listings_item_sku
ON listings(ebay_item_id, sku);
""")

# Delete duplicates by keeping the lowest id per (ebay_item_id, sku)
# Note: treats NULL/empty sku as the same key; adjust if you need separate behavior
cur.execute("""
DELETE FROM listings
WHERE id NOT IN (
  SELECT MIN(id)
  FROM listings
  GROUP BY ebay_item_id, sku
);
""")

conn.commit()
print("Cleanup complete. Rows remaining:", cur.execute("SELECT COUNT(*) FROM listings;").fetchone()[0])
conn.close()
