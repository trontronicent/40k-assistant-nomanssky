"""Paths and settings of the standalone host."""
import json

from standalone import config, paths


def test_data_dir_follows_localappdata():
    """`data_dir` must sit under LOCALAPPDATA, not in the install folder: the install folder is replaced
    wholesale by an update, and the user's save-derived data must survive it."""
    env = {"LOCALAPPDATA": r"C:\Users\X\AppData\Local"}
    assert paths.data_dir(env) == paths.Path(r"C:\Users\X\AppData\Local\NMS Companion")


def test_data_dir_falls_back_to_home(tmp_path):
    """Without LOCALAPPDATA (a test box, a non-Windows developer machine) the data dir must still resolve,
    so the host can start and log instead of crashing at import time."""
    env = {"USERPROFILE": str(tmp_path)}
    assert paths.data_dir(env) == tmp_path / ".nms-companion"


def test_settings_round_trip(tmp_path):
    """Settings must survive a save/load cycle unchanged, because the installer writes them once and the
    host reads them on every start."""
    s = config.Settings(port=8790, ai_enabled=True, chat_model="40k-12b-companion")
    config.save(tmp_path / "standalone.json", s)
    assert config.load(tmp_path / "standalone.json") == s


def test_settings_defaults_when_file_missing(tmp_path):
    """A missing settings file must read as the defaults (AI off, voice off), so a copied install folder
    runs rather than failing: the installer is what turns features on."""
    s = config.load(tmp_path / "nothing.json")
    assert (s.ai_enabled, s.tts_enabled, s.port) == (False, False, 8787)


def test_damaged_settings_file_reads_as_defaults(tmp_path):
    """A truncated or hand-edited settings file must not stop the program; it reads as defaults (the caller
    logs a warning), matching how the app treats its own damaged state files."""
    (tmp_path / "s.json").write_text("{not json", encoding="utf-8")
    assert config.load(tmp_path / "s.json").port == 8787


def test_unknown_keys_are_ignored(tmp_path):
    """A settings file written by a newer version must load on an older one (the updater allows downgrades),
    so unknown keys are dropped instead of raising."""
    (tmp_path / "s.json").write_text(json.dumps({"port": 9000, "future": 1}), encoding="utf-8")
    assert config.load(tmp_path / "s.json").port == 9000
