from ebay_feed import request_active_inventory_report, wait_for_task, download_report
from ebay_inventory import get_offers_for_sku
import csv, io, time
from db import upsert_offer_from_api, begin_sync_run, end_sync_run  # <- wire to your DB layer

def run_sync():
    run_id = begin_sync_run(source="feed")
    task_id = request_active_inventory_report()
    task = wait_for_task(task_id)
    file_url = task["resultFileUrl"]
    raw = download_report(file_url)
    reader = csv.DictReader(io.StringIO(raw), delimiter="," if "," in raw.splitlines()[0] else "\t")

    items_seen = offers_seen = 0
    for row in reader:
        sku = row.get("SKU") or row.get("sku")
        if not sku:
            continue
        items_seen += 1
        offers = get_offers_for_sku(sku)
        for off in offers:
            upsert_offer_from_api(sku, off)
            offers_seen += 1

    end_sync_run(run_id, items_seen=items_seen, offers_seen=offers_seen, notes=f"task={task_id}")
    return {"items_seen": items_seen, "offers_seen": offers_seen, "task_id": task_id}
