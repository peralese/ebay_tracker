#!/usr/bin/env python3
"""
sync.py — eBay inventory sync runner with end-of-run summary + adaptive imports.

- Prints a concise summary after sync (added / updated / skipped / deleted / errors)
- Writes JSON artifact to ./logs/sync-YYYYMMDD-HHMMSS.json
- Appends a single-line summary to ./logs/sync.log
- Adapts to existing function names in ebay_inventory.py
    * local items:   get_local_items | load_local_items | read_local_items | fetch_local_items | iter_local_items
    * remote items:  get_remote_items | load_remote_items | list_remote_items | fetch_remote_items | iter_remote_items
    * upsert item:   upsert_remote_item | upsert_item | create_or_update_item | sync_remote_item | apply_item
    * delete item:   delete_remote_item | remove_remote_item | delete_item
- Set EBT_DISABLE_DELETE=1 to skip delete pass without code changes.
"""

import os
import sys
import json
import time
import logging
import inspect 
from datetime import datetime, timezone
from pathlib import Path

# Optional dotenv for local dev; safe if not installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- Adaptive import layer ---------------------------------------------------
try:
    import ebay_inventory as _inv
except Exception as e:
    print("Failed to import ebay_inventory.py — is it in this folder?", file=sys.stderr)
    raise

def _auth_is_configured():
    # Adjust keys if your ebay_auth.py uses different names
    keys = ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_REFRESH_TOKEN"]
    vals = [os.getenv(k, "") for k in keys]
    # treat blanks or “YOUR_” placeholders as not-configured
    return all(v and not v.strip().upper().startswith(("YOUR_", "PLACEHOLDER", "XXX")) for v in vals)


def _resolve(name_candidates, required=True, env_var: str | None = None):
    """Return first attribute in ebay_inventory that exists; allow ENV override."""
    if env_var:
        override = os.getenv(env_var)
        if override and hasattr(_inv, override):
            return getattr(_inv, override), override
    for n in name_candidates:
        if hasattr(_inv, n):
            return getattr(_inv, n), n
    if required:
        raise ImportError(
            "Missing required function in ebay_inventory.py. "
            f"Tried: {', '.join(name_candidates)}"
        )
    return None, None


_GET_LOCAL,  _GET_LOCAL_NAME  = _resolve(
    ["get_local_items","load_local_items","read_local_items","fetch_local_items","iter_local_items"],
    env_var="EBT_GET_LOCAL_FN"
)
_GET_REMOTE, _GET_REMOTE_NAME = _resolve(
    ["get_remote_items","load_remote_items","list_remote_items","fetch_remote_items","iter_remote_items"],
    env_var="EBT_GET_REMOTE_FN"
)
_UPSERT,     _UPSERT_NAME     = _resolve(
    ["upsert_remote_item","upsert_item","create_or_update_item","sync_remote_item","apply_item"],
    env_var="EBT_UPSERT_FN"
)
# _DELETE stays optional; allow override too:
_DELETE,     _DELETE_NAME     = _resolve(
    ["delete_remote_item","remove_remote_item","delete_item"],
    required=False, env_var="EBT_DELETE_FN"
)


# Optional auth import if you have it; otherwise tolerate absence
try:
    from ebay_auth import get_access_token as _GET_TOKEN
except Exception:
    _GET_TOKEN = None

# ---- Files & logging ---------------------------------------------------------
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_LOG = LOG_DIR / "sync.log"

logging.basicConfig(
    filename=LOG_DIR / "debug.log",
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

def _banner(text: str):
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)

class SyncSummary:
    def __init__(self):
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.ended_at = None
        self.duration_sec = 0.0
        self.counts = {"added": 0, "updated": 0, "skipped": 0, "deleted": 0, "errors": 0}
        self.items = []

    def record(self, item_id: str, action: str, reason: str = "", error: str = ""):
        action_norm = action if action in self.counts else "skipped"
        self.counts[action_norm] += 1
        self.items.append({"id": str(item_id), "action": action_norm, "reason": reason, "error": error})

    def finish(self, start_ts: float):
        self.ended_at = datetime.now(timezone.utc).isoformat()
        self.duration_sec = round(time.time() - start_ts, 3)

    def as_dict(self):
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_sec": self.duration_sec,
            "counts": self.counts,
            "items": self.items,
            "adapters": {
                "get_local_items": _GET_LOCAL_NAME,
                "get_remote_items": _GET_REMOTE_NAME,
                "upsert_item": _UPSERT_NAME,
                "delete_item": _DELETE_NAME or "(not available)",
            },
        }

def _write_summary_files(summary: SyncSummary):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = LOG_DIR / f"sync-{stamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary.as_dict(), f, indent=2)
    c = summary.counts
    line = (
        f"{stamp} | added={c['added']} updated={c['updated']} skipped={c['skipped']} "
        f"deleted={c['deleted']} errors={c['errors']} duration_sec={summary.duration_sec}"
    )
    with open(SUMMARY_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return json_path

# ---- Core sync ---------------------------------------------------------------
def sync() -> SyncSummary:
    start_ts = time.time()
    summary = SyncSummary()
    logging.info("Sync start")

    # Auth once if available
   
    # Auth once if available and configured, unless disabled
    if _GET_TOKEN and not os.getenv("EBT_DISABLE_AUTH"):
        if _auth_is_configured():
            try:
                _GET_TOKEN()
            except Exception as e:
                logging.exception("Auth failure")
                summary.record("__auth__", "errors", reason="auth", error=str(e))
                summary.finish(start_ts)
                return summary
        else:
            # Offline mode: skip auth silently
            logging.info("Auth skipped (offline mode; creds not configured)")


    # Load inventories
    try:
        local_items = list(_GET_LOCAL())
    except Exception as e:
        logging.exception("Failed to load local items via %s", _GET_LOCAL_NAME)
        summary.record("__inventory_local__", "errors", reason=_GET_LOCAL_NAME, error=str(e))
        summary.finish(start_ts)
        return summary

    try:
        remote_items = list(_GET_REMOTE())
    except Exception as e:
        logging.exception("Failed to load remote items via %s", _GET_REMOTE_NAME)
        summary.record("__inventory_remote__", "errors", reason=_GET_REMOTE_NAME, error=str(e))
        summary.finish(start_ts)
        return summary

    def _key(obj):
        # common id keys; adjust if needed
        for k in ("id", "sku", "itemId", "item_id"):
            v = obj.get(k)
            if v not in (None, ""):
                return str(v)
        # fallback: stringified dict hash (keeps process going, but marked skipped)
        return None

    remote_by_id = {}
    for r in remote_items:
        rid = _key(r)
        if rid:
            remote_by_id[rid] = r

    local_by_id = {}
    for l in local_items:
        lid = _key(l)
        if lid:
            local_by_id[lid] = l
        else:
            summary.record("(unknown)", "skipped", reason="no-id-key")

    # Upsert pass
    for lid, litem in local_by_id.items():
        ritem = remote_by_id.get(lid)
        try:
            result = _UPSERT(litem, ritem) 
            params = inspect.signature(_UPSERT).parameters
            req = [p for p in params.values()
                if p.default is inspect._empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            if len(req) >= 2:
                result = _UPSERT(litem, ritem)
            else:
                result = _UPSERT(litem)

            # Normalize common truthy returns
            if result is True and ritem is None:
                result = "added"
            elif result is True and ritem is not None:
                result = "updated"
            elif result is False or result is None:
                result = "skipped"
            summary.record(lid, str(result), reason="upsert")
        except Exception as e:
            logging.exception("Upsert failed for %s via %s", lid, _UPSERT_NAME)
            summary.record(lid, "errors", reason=_UPSERT_NAME, error=str(e))

    # Optional delete pass
    if not os.getenv("EBT_DISABLE_DELETE") and _DELETE:
        for rid, ritem in remote_by_id.items():
            if rid not in local_by_id:
                try:
                    result = _DELETE(ritem)
                    if result is True:
                        result = "deleted"
                    elif result in (False, None):
                        result = "skipped"
                    summary.record(rid, str(result), reason="reconcile-delete")
                except Exception as e:
                    logging.exception("Delete failed for %s via %s", rid, _DELETE_NAME)
                    summary.record(rid, "errors", reason=_DELETE_NAME, error=str(e))

    summary.finish(start_ts)
    logging.info("Sync finished: %s", summary.counts)
    return summary

def main():
    _banner("eBay Sync — Running")
    print(f"Adapters — local:{_GET_LOCAL_NAME} | remote:{_GET_REMOTE_NAME} | upsert:{_UPSERT_NAME} | delete:{_DELETE_NAME or 'N/A'}")
    summary = sync()

    c = summary.counts
    print(f"Added   : {c['added']}")
    print(f"Updated : {c['updated']}")
    print(f"Skipped : {c['skipped']}")
    print(f"Deleted : {c['deleted']}")
    print(f"Errors  : {c['errors']}")
    print(f"Duration: {summary.duration_sec}s")

    json_path = _write_summary_files(summary)

    if c["errors"] > 0:
        _banner("Sync completed WITH ERRORS")
        print(f"Details JSON: {json_path}")
        sys.exit(1)
    else:
        _banner("Sync completed successfully")
        print(f"Details JSON: {json_path}")
        sys.exit(0)

if __name__ == "__main__":
    main()
