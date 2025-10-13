import os, sqlite3
db  = os.getenv("EBT_SQLITE_PATH","ebay_tracker.db")
tbl = os.getenv("EBT_SQLITE_TABLE","listings_for_sync")
con = sqlite3.connect(db); con.row_factory = sqlite3.Row
# does the view/table exist?
exists = con.execute("SELECT name FROM sqlite_master WHERE name=?",(tbl,)).fetchone()
if not exists:
    print(f" Table/View not found: {tbl}")
else:
    total = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    nonnull = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE updated_at IS NOT NULL AND updated_at<>''").fetchone()[0]
    recent = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE updated_at >= '2025-10-01'").fetchone()[0]
    print(f" {tbl} exists. rows={total}, with updated_at={nonnull}, updated_at>=2025-10-01={recent}")
    samp = con.execute(f"SELECT id, sku, updated_at FROM {tbl} WHERE updated_at IS NOT NULL AND updated_at<>'' LIMIT 5").fetchall()
    print("samples:", samp)
con.close()
