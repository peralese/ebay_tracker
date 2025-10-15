from types import SimpleNamespace


def test_sync_smoke(csv_file):
    import sync

    # No --since: both rows are processed (dry run => skipped)
    args = SimpleNamespace(dry_run=True, summary_csv=None, since=None, verbose=0)
    s1 = sync.run(args)
    assert s1.counts["errors"] == 0
    assert s1.counts["skipped"] == 2

    # With --since: only the 2025-10-02 row remains
    args2 = SimpleNamespace(dry_run=True, summary_csv=None, since="2025-10-01", verbose=0)
    s2 = sync.run(args2)
    assert s2.counts["errors"] == 0
    assert s2.counts["skipped"] == 1

