"""
Smoke test for sync.py

Creates a tiny CSV as the local source, forces dry-run with auth/deletes disabled,
and verifies counts with and without a --since filter.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace


def write_csv(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """id,sku,title,updated_at
1,SKU-1,Item 1,2025-10-02
2,SKU-2,Item 2,2025-09-01
""",
        encoding="utf-8",
    )


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    csv_path = repo / "tests" / "_tmp_smoke.csv"
    write_csv(csv_path)

    # Ensure CSV is used and network-side effects are disabled
    os.environ["EBT_LOCAL_CSV"] = str(csv_path)
    os.environ["EBT_DISABLE_AUTH"] = "1"
    os.environ["EBT_DISABLE_DELETE"] = "1"

    import sys
    sys.path.insert(0, str(repo))
    import sync  # import after env is prepared

    # Run without --since
    args = SimpleNamespace(dry_run=True, summary_csv=None, since=None, verbose=0)
    s1 = sync.run(args)
    if s1.counts.get("errors", 0) != 0:
        print("Smoke: unexpected errors in run 1:", s1.counts)
        return 1
    if s1.counts.get("skipped", 0) != 2:
        print("Smoke: expected 2 skipped in run 1, got:", s1.counts)
        return 1

    # Run with --since (should keep only the 2025-10-02 row)
    args2 = SimpleNamespace(dry_run=True, summary_csv=None, since="2025-10-01", verbose=0)
    s2 = sync.run(args2)
    if s2.counts.get("errors", 0) != 0:
        print("Smoke: unexpected errors in run 2:", s2.counts)
        return 1
    if s2.counts.get("skipped", 0) != 1:
        print("Smoke: expected 1 skipped in run 2, got:", s2.counts)
        return 1

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
