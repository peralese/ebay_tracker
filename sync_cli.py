# sync_cli.py
from sync import run_sync  # or from sync import run_sync

if __name__ == "__main__":
    result = run_sync()
    print(f"✅ Sync complete: {result}")
