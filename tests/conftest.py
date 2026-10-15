import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def isolate_persistence(tmp_path, monkeypatch):
    """Ensure tests run against an isolated temporary data file instead of user data."""
    test_file = tmp_path / "chats.json"
    from ghost_ai import persistence
    monkeypatch.setattr(persistence, "get_default_storage_path", lambda: test_file)
