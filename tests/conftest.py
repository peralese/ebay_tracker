import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True, scope="session")
def add_repo_to_path(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    try:
        yield
    finally:
        if str(repo_root) in sys.path:
            sys.path.remove(str(repo_root))


@pytest.fixture()
def csv_file(tmp_path: Path) -> Path:
    csv_path = tmp_path / "items.csv"
    csv_path.write_text(
        """id,sku,title,updated_at
1,SKU-1,Item 1,2025-10-02
2,SKU-2,Item 2,2025-09-01
""",
        encoding="utf-8",
    )
    return csv_path


@pytest.fixture(autouse=True)
def env_overrides(monkeypatch: pytest.MonkeyPatch, csv_file: Path):
    monkeypatch.setenv("EBT_LOCAL_CSV", str(csv_file))
    monkeypatch.setenv("EBT_DISABLE_AUTH", "1")
    monkeypatch.setenv("EBT_DISABLE_DELETE", "1")
    yield

