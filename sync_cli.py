# sync_cli.py
from sync import run_sync  # or from sync import run_sync

def run_sync():
    """Programmatic entrypoint used by sync_cli.py."""
    s = sync()
    return {"counts": s.counts, "duration_sec": s.duration_sec}


if __name__ == "__main__":
    result = run_sync()
    print(f"✅ Sync complete: {result}")


