import time, requests
from ebay_auth import get_access_token

BASE = "https://api.ebay.com/sell/feed/v1"

def _hdrs():
    return {"Authorization": f"Bearer {get_access_token()}", "Content-Type": "application/json", "Accept": "application/json"}

def request_active_inventory_report():
    # create task
    payload = {"feedType": "ACTIVE_INVENTORY_REPORT"}
    r = requests.post(f"{BASE}/inventory_task", json=payload, headers=_hdrs(), timeout=30)
    r.raise_for_status()
    task = r.json()
    return task["taskId"]

def wait_for_task(task_id, timeout_s=180):
    start = time.time()
    while time.time() - start < timeout_s:
        r = requests.get(f"{BASE}/inventory_task/{task_id}", headers=_hdrs(), timeout=30)
        r.raise_for_status()
        st = r.json()["status"]
        if st in ("COMPLETED","COMPLETED_WITH_ERRORS"):
            return r.json()
        if st in ("FAILED","ABORTED"):
            raise RuntimeError(f"Feed task failed: {st}")
        time.sleep(5)
    raise TimeoutError("Feed task polling timed out")

def download_report(result_url, session=None):
    sess = session or requests.Session()
    with sess.get(result_url, headers=_hdrs(), stream=True, timeout=60) as r:
        r.raise_for_status()
        return r.text  # CSV/TSV text
