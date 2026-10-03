import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def no_real_game(tmp_path, monkeypatch):
    """Tests never read the real game installation: NMS_GAME_DIR points at a missing folder
    unless a test sets its own (find_game then reports no installation)."""
    monkeypatch.setenv("NMS_GAME_DIR", str(tmp_path / "no-game-installed"))
    monkeypatch.delenv("NMS_LANGUAGE", raising=False)
