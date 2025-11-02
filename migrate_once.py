# migrate_once.py
from db import _conn
with _conn() as conn:
    print("DB ready.")
