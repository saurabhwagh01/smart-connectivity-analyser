import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import backend.main as main  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    """API client backed by an isolated, empty SQLite database."""
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test_network_history.db")
    main.initialize_database()

    with TestClient(main.app) as test_client:
        yield test_client
