from types import SimpleNamespace


def test_write_summary_csv(tmp_path):
    import sync

    # Run a dry-run to obtain a summary (env fixtures provide CSV + offline)
    args = SimpleNamespace(dry_run=True, summary_csv=None, since=None, verbose=0)
    s = sync.run(args)

    out = tmp_path / "summary.csv"
    sync._write_summary_csv(s, out)

    content = out.read_text(encoding="utf-8").splitlines()
    assert content[0] == "started_at,ended_at,duration_sec,added,updated,skipped,deleted,errors"
    assert len(content) == 2


def test_dry_run_skips_remote(monkeypatch):
    import sync

    # Set _GET_REMOTE to raise if called; in dry-run it must not be invoked
    def _boom():
        raise AssertionError("remote fetch should not be called in dry-run")

    monkeypatch.setattr(sync, "_GET_REMOTE", _boom)

    args = SimpleNamespace(dry_run=True, summary_csv=None, since=None, verbose=0)
    s = sync.run(args)

    # With the csv_file fixture (2 rows), both become skipped in dry-run
    assert s.counts["errors"] == 0
    assert s.counts["skipped"] == 2

