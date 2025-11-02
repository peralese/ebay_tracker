"""
sync.py — eBay Tracker sync runner

Adds CLI flags:
  --dry-run              : simulate (no auth, no writes, no deletes)
  --summary-csv <path>   : write a one-row CSV rollup with counts
  --since YYYY-MM-DD     : only process local items changed on/after date (local-side filter)
  -v / -vv (--verbose)   : increase log verbosity to INFO / DEBUG

Keeps:
  - Adaptive function discovery with ENV overrides
  - Offline auth gating (skip OAuth when creds are placeholders or EBT_DISABLE_AUTH=1)
  - Timezone-aware UTC timestamps
  - JSON per-run artifact + rolling sync.log
  - Delete pass controlled by EBT_DISABLE_DELETE
"""

from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterable
import argparse
import csv
import inspect
import json
import logging
import os
import sys
import time

# Optional dotenv for local dev
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---------------- Files & logging ----------------
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

def configure_logging(verbosity: int):
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        filename=LOG_DIR / "debug.log",
        filemode="a",
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

def _banner(txt):
    print("\n" + "=" * 60)
    print(txt)
    print("=" * 60)

# ---------------- Import inventory module ----------------
try:
    import ebay_inventory as _inv
except Exception:
    print("❌ Could not import ebay_inventory.py. Is it in this folder?", file=sys.stderr)
    raise

# ---------------- Helpers ----------------
def _is_iterable_of_dicts(x):
    if not isinstance(x, Iterable) or isinstance(x, (str, bytes, dict)):
        return False
    try:
        for i, v in enumerate(x):
            if not isinstance(v, dict):
                return False
            if i > 4:
                break
        return True
    except Exception:
        return False

def _call_zero_arg(fn):
    try:
        sig = inspect.signature(fn)
        req = [p for p in sig.parameters.values()
               if p.default is inspect._empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        if req:
            return (False, RuntimeError("function requires arguments"))
        out = fn()
        return (True, out)
    except Exception as e:
        return (False, e)

def _discover(kind):
    """Return best function name for kind in {'local','remote','upsert','delete'}; allow env override."""
    env_key = {
        "local": "EBT_GET_LOCAL_FN",
        "remote": "EBT_GET_REMOTE_FN",
        "upsert": "EBT_UPSERT_FN",
        "delete": "EBT_DELETE_FN",
    }[kind]
    override = os.getenv(env_key)
    if override and hasattr(_inv, override):
        return override

    names = [n for n in dir(_inv) if not n.startswith("_") and callable(getattr(_inv, n))]
    lname = [(n, n.lower()) for n in names]

    if kind == "local":
        keys = ("local", "csv_local", "db_local")
        verbs = ("get", "load", "list", "read", "fetch", "iter", "all")
        priority = ["get_local_items","load_local_items","read_local_items"]
    elif kind == "remote":
        keys = ("remote", "ebay", "api")
        verbs = ("get", "load", "list", "read", "fetch", "iter", "all")
        priority = ["get_remote_items","list_remote_items","fetch_remote_items"]
    elif kind == "upsert":
        keys = ("upsert","create_or_update","createupdate","sync","apply","merge")
        verbs = ("item","listing")
        priority = ["upsert_remote_item","upsert_item","sync_remote_item","create_or_update_item"]
    else:
        keys = ("delete","remove","purge")
        verbs = ("item","listing")
        priority = ["delete_remote_item","remove_remote_item","delete_item"]

    candidates = []
    for n, ln in lname:
        if any(k in ln for k in keys) and any(v in ln for v in verbs):
            candidates.append(n)

    ordered = priority + [c for c in candidates if c not in priority]
    for n in ordered:
        if hasattr(_inv, n):
            return n
    return None

# Bind
_FN_LOCAL  = _discover("local")
_FN_REMOTE = _discover("remote")
_FN_UPSERT = _discover("upsert")
_FN_DELETE = _discover("delete")  # optional

# Validate required bindings
missing = [("EBT_GET_LOCAL_FN", _FN_LOCAL), ("EBT_GET_REMOTE_FN", _FN_REMOTE), ("EBT_UPSERT_FN", _FN_UPSERT)]
def _print_binding_help_and_exit():
    _banner("Missing required inventory bindings")
    print("I couldn’t match your function names automatically.")
    print("\nFunctions found in ebay_inventory:")
    funcs = [n for n in dir(_inv) if callable(getattr(_inv, n)) and not n.startswith("_")]
    for n in sorted(funcs):
        print(" -", n)
    print("\nSet these env vars to your actual function names, then re-run:")
    print("  $env:EBT_GET_LOCAL_FN = \"YOUR_LOCAL_FN\"")
    print("  $env:EBT_GET_REMOTE_FN = \"YOUR_REMOTE_FN\"")
    print("  $env:EBT_UPSERT_FN    = \"YOUR_UPSERT_FN\"")
    print("  # optional:")
    print("  # $env:EBT_DELETE_FN    = \"YOUR_DELETE_FN\"")
    print("  # $env:EBT_DISABLE_DELETE = \"1\"")
    sys.exit(2)

if any(v is None for _, v in missing):
    _print_binding_help_and_exit()

# Resolved callables
_GET_LOCAL  = getattr(_inv, _FN_LOCAL)
_GET_REMOTE = getattr(_inv, _FN_REMOTE)
_UPSERT     = getattr(_inv, _FN_UPSERT)
_DELETE     = getattr(_inv, _FN_DELETE) if _FN_DELETE else None

# Optional auth (tolerate absence)
try:
    from ebay_auth import get_access_token as _GET_TOKEN
except Exception:
    _GET_TOKEN = None

def _auth_is_configured():
    keys = ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_REFRESH_TOKEN"]
    vals = [os.getenv(k, "") for k in keys]
    return all(
        v
        and not v.strip().upper().startswith(("YOUR_", "PLACEHOLDER", "XXX"))
        for v in vals
    )

# ---------------- Summary ----------------
class SyncSummary:
    def __init__(self, adapters: dict):
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.ended_at = None
        self.duration_sec = 0.0
        self.counts = {"added":0,"updated":0,"skipped":0,"deleted":0,"errors":0}
        self.items = []
        self.adapters = adapters

    def record(self, item_id, action, reason="", error=""):
        action = action if action in self.counts else "skipped"
        self.counts[action] += 1
        self.items.append({"id": str(item_id), "action": action, "reason": reason, "error": error})

    def finish(self, t0):
        self.ended_at = datetime.now(timezone.utc).isoformat()
        self.duration_sec = round(time.time() - t0, 3)

    def as_dict(self):
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_sec": self.duration_sec,
            "counts": self.counts,
            "items": self.items,
            "adapters": self.adapters,
        }

def _key(obj):
    for k in ("id","sku","itemId","item_id"):
        v = obj.get(k)
        if v not in (None, ""):
            return str(v)
    return None

def _write_artifacts(summary: SyncSummary):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    json_path = LOG_DIR / f"sync-{stamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary.as_dict(), f, indent=2)
    line = (f"{stamp} | added={summary.counts['added']} updated={summary.counts['updated']} "
            f"skipped={summary.counts['skipped']} deleted={summary.counts['deleted']} "
            f"errors={summary.counts['errors']} duration_sec={summary.duration_sec}")
    with open(LOG_DIR / "sync.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return json_path

def _write_summary_csv(summary: SyncSummary, csv_path: Path):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["started_at","ended_at","duration_sec","added","updated","skipped","deleted","errors"])
        c = summary.counts
        w.writerow([summary.started_at, summary.ended_at, summary.duration_sec, c["added"], c["updated"], c["skipped"], c["deleted"], c["errors"]])

# --------------- Date filtering support ( --since ) ---------------
_TS_FIELDS = [
    "updated_at","modified","last_modified","lastUpdate","last_updated",
    "mtime","modified_at","date_modified","changed_at","created","created_at","listed_at"
]

def _parse_ts(value: str):
    fmts = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z","+00:00"))
    except Exception:
        return None

def _item_ts(item: dict):
    for k in _TS_FIELDS:
        v = item.get(k)
        if isinstance(v, (int, float)):
            try:
                return datetime.fromtimestamp(float(v))
            except Exception:
                continue
        if isinstance(v, str) and v.strip():
            ts = _parse_ts(v.strip())
            if ts:
                return ts
    return None

# ---------------- Core sync ----------------
def run(args) -> SyncSummary:
    adapters = {
        "get_local_items": _FN_LOCAL,
        "get_remote_items": _FN_REMOTE,
        "upsert_item": _FN_UPSERT,
        "delete_item": _FN_DELETE or "(not available)",
    }
    t0 = time.time()
    summary = SyncSummary(adapters=adapters)

    dry_run = args.dry_run
    since_dt = None
    if args.since:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d")
        except Exception:
            logging.warning("Could not parse --since '%s' (expected YYYY-MM-DD); continuing without filter", args.since)

    # Auth (only if not dry-run, creds look real, and not disabled)
    if _GET_TOKEN and not dry_run and not os.getenv("EBT_DISABLE_AUTH"):
        if _auth_is_configured():
            try:
                _GET_TOKEN()
            except Exception as e:
                logging.exception("Auth failure")
                summary.record("__auth__", "errors", reason="auth", error=str(e))
                summary.finish(t0); return summary
        else:
            logging.info("Auth skipped (offline mode; creds not configured)")

    # Fetch local/remote
    ok, local_val = _call_zero_arg(_GET_LOCAL)
    if not ok:
        _banner("Failed to load local items")
        summary.record("__local__", "errors", reason="local-load", error=str(local_val))
        summary.finish(t0); return summary
    try:
        local = list(local_val)
    except Exception:
        _banner("Local items is not iterable")
        print(f"Function: {_FN_LOCAL}   Type: {type(local_val).__name__}")
        summary.record("__local__", "errors", reason="local-load", error="invalid-local-iterable")
        summary.finish(t0); return summary
    if not all(isinstance(v, dict) for v in local):
        _banner("Local items must be a list of dicts")
        print(f"Function: {_FN_LOCAL}   Type: list[{type(local[0]).__name__}]" if local else "Function produced empty list")
        summary.record("__local__", "errors", reason="local-load", error="invalid-local-iterable")
        summary.finish(t0); return summary
    if False:
        _banner("Local items function didn’t return iterable[dict]")
        print(f"Function: {_FN_LOCAL}   Type: {type(local).__name__}")
        summary.record("__local__", "errors", reason="local-load", error="invalid-local-iterable")
        summary.finish(t0); return summary

    if dry_run:
        remote = []
    else:
        ok, remote_val = _call_zero_arg(_GET_REMOTE)
        if not ok:
            _banner("Failed to load remote items")
            summary.record("__remote__", "errors", reason="remote-load", error=str(remote_val))
            summary.finish(t0); return summary
        try:
            remote = list(remote_val)
        except Exception:
            _banner("Remote items is not iterable")
            print(f"Function: {_FN_REMOTE}   Type: {type(remote_val).__name__}")
            summary.record("__remote__", "errors", reason="remote-load", error="invalid-remote-iterable")
            summary.finish(t0); return summary
        if not all(isinstance(v, dict) for v in remote):
            _banner("Remote items must be a list of dicts")
            print(f"Function: {_FN_REMOTE}   Type: list[{type(remote[0]).__name__}]" if remote else "Function produced empty list")
            summary.record("__remote__", "errors", reason="remote-load", error="invalid-remote-iterable")
            summary.finish(t0); return summary
    if False:
        _banner("Remote items function didn’t return iterable[dict]")
        print(f"Function: {_FN_REMOTE}   Type: {type(remote).__name__}")
        # remote can be empty in offline; only error if completely invalid
        if remote is None:
            summary.record("__remote__", "errors", reason="remote-load", error="invalid-remote-iterable")
        summary.finish(t0); return summary

    # --since filtering (local side)
    if since_dt:
        before = len(local)
        # normalize comparison to UTC-aware datetimes to avoid naive/aware errors
        def _to_utc_aware(dt):
            if dt is None:
                return None
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

        since_cut = _to_utc_aware(since_dt)
        filtered = []
        for it in local:
            ts = _item_ts(it)
            if not ts:
                continue
            ts_cmp = _to_utc_aware(ts)
            if ts_cmp >= since_cut:
                filtered.append(it)
        local = filtered
        logging.info("Filtered local items by --since %s: %d -> %d", args.since, before, len(local))

    # Index by ID
    def _key_local(obj): return _key(obj)
    def _key_remote(obj): return _key(obj)

    remote_by_id = {}
    for r in remote:
        rid = _key_remote(r)
        if rid:
            remote_by_id[rid] = r

    local_by_id = {}
    for l in local:
        lid = _key_local(l)
        if lid:
            local_by_id[lid] = l
        else:
            summary.record("(unknown)", "skipped", reason="no-id-key")

    # Upsert pass
    for lid, litem in local_by_id.items():
        ritem = remote_by_id.get(lid)
        try:
            if dry_run:
                summary.record(lid, "skipped", reason="dry-run")
                continue

            params = inspect.signature(_UPSERT).parameters
            req = [p for p in params.values()
                   if p.default is inspect._empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            if len(req) >= 2:
                result = _UPSERT(litem, ritem)
            else:
                result = _UPSERT(litem)

            if result is True and ritem is None:
                norm = "added"
            elif result is True and ritem is not None:
                norm = "updated"
            elif result in ("added","updated","skipped","deleted"):
                norm = result
            else:
                norm = "skipped"
            summary.record(lid, norm, reason="upsert")
        except Exception as e:
            logging.exception("Upsert failed for %s", lid)
            summary.record(lid, "errors", reason=_FN_UPSERT, error=str(e))

    # Optional delete pass
    if not dry_run and not os.getenv("EBT_DISABLE_DELETE") and _DELETE is not None:
        for rid, ritem in remote_by_id.items():
            if rid not in local_by_id:
                try:
                    result = _DELETE(ritem)
                    norm = "deleted" if result is True or result == "deleted" else "skipped"
                    summary.record(rid, norm, reason="reconcile-delete")
                except Exception as e:
                    logging.exception("Delete failed for %s", rid)
                    summary.record(rid, "errors", reason=_FN_DELETE, error=str(e))

    summary.finish(t0)
    return summary

def main():
    parser = argparse.ArgumentParser(description="eBay Tracker sync runner")
    parser.add_argument("--dry-run", action="store_true", help="Do not auth, fetch remote, upsert, or delete; simulate actions")
    parser.add_argument("--summary-csv", type=str, help="Write a CSV summary to this path")
    parser.add_argument("--since", type=str, help="Only process local items changed on/after YYYY-MM-DD")
    parser.add_argument("-v","--verbose", action="count", default=0, help="Increase log verbosity (-v, -vv)")
    args = parser.parse_args()

    configure_logging(args.verbose)

    _banner("eBay Sync — Running")
    print(f"Adapters — local:{_FN_LOCAL} | remote:{_FN_REMOTE} | upsert:{_FN_UPSERT} | delete:{_FN_DELETE or 'N/A'}")
    if args.dry_run:
        print("Mode     — DRY RUN (no auth, no writes, no deletes)")
    if args.since:
        print(f"Filter   — since {args.since} (local items only)")

    summary = run(args)

    c = summary.counts
    print(f"Added   : {c['added']}")
    print(f"Updated : {c['updated']}")
    print(f"Skipped : {c['skipped']}")
    print(f"Deleted : {c['deleted']}")
    print(f"Errors  : {c['errors']}")
    print(f"Duration: {summary.duration_sec}s")

    json_path = _write_artifacts(summary)
    if args.summary_csv:
        _write_summary_csv(summary, Path(args.summary_csv))
        print(f"Summary CSV: {args.summary_csv}")

    if c["errors"] > 0:
        _banner("Sync completed WITH ERRORS"); print(f"Details JSON: {json_path}"); sys.exit(1)
    else:
        _banner("Sync completed successfully"); print(f"Details JSON: {json_path}"); sys.exit(0)

# Programmatic entrypoint (e.g., if another module imports this)
def run_sync():
    s = run(argparse.Namespace(dry_run=True, summary_csv=None, since=None, verbose=0))
    return {"counts": s.counts, "duration_sec": s.duration_sec}

if __name__ == "__main__":
    main()

