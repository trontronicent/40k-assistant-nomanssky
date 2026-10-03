"""Find the No Man's Sky installation and the language the game runs in. Read-only.

Steam keeps every installed game in a library folder listed in
``<Steam>/steamapps/libraryfolders.vdf``; the game's
``appmanifest_275850.acf`` names its folder, the installed build id and the
language Steam starts it in (``UserConfig.language``, e.g. ``german``).
``NMS_GAME_DIR`` points at another installation (GOG, a copy) and
``NMS_LANGUAGE`` overrides the language (a Steam code such as ``german`` or the
game's own file suffix such as ``latinamericanspanish``).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

STEAM_APP_ID = "275850"

# Steam language code -> suffix of the game's language files (language/nms_loc1_<suffix>.mbin).
STEAM_TO_NMS = {
    "english": "english", "german": "german", "french": "french", "italian": "italian", "spanish": "spanish",
    "latam": "latinamericanspanish", "brazilian": "brazilianportuguese", "portuguese": "portuguese",
    "polish": "polish", "russian": "russian", "japanese": "japanese", "koreana": "korean",
    "schinese": "simplifiedchinese", "tchinese": "traditionalchinese", "dutch": "dutch",
}

# Column headers: each language in its own words.
LANGUAGE_LABELS = {
    "english": "English", "usenglish": "English (US)", "german": "Deutsch", "french": "Français",
    "italian": "Italiano", "spanish": "Español", "latinamericanspanish": "Español (Latinoamérica)",
    "brazilianportuguese": "Português (Brasil)", "portuguese": "Português", "polish": "Polski",
    "russian": "Русский", "japanese": "日本語", "korean": "한국어", "simplifiedchinese": "简体中文",
    "traditionalchinese": "繁體中文", "tencentchinese": "简体中文 (Tencent)", "dutch": "Nederlands",
}


@dataclass(frozen=True)
class GameInstall:
    root: Path              # the game folder (contains GAMEDATA)
    build_id: str | None    # Steam build id; None outside Steam
    language: str           # suffix of the game's language files, e.g. "german"
    source: str             # "steam" or "NMS_GAME_DIR"

    @property
    def pcbanks(self) -> Path:
        return self.root / "GAMEDATA" / "PCBANKS"


def parse_vdf(text: str) -> dict:
    """Parse Valve KeyValues text (libraryfolders.vdf, appmanifest_*.acf) into nested dicts."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root: dict = {}
    stack = [root]
    key: str | None = None
    for quoted, brace in tokens:
        if brace == "{":
            child: dict = {}
            if key is not None:
                stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = quoted.replace("\\\\", "\\")
        else:
            stack[-1][key] = quoted.replace("\\\\", "\\")
            key = None
    return root


def _ci(d: dict, key: str):
    """Case-insensitive dict lookup (Steam writes keys in varying case)."""
    for k, v in d.items():
        if k.lower() == key.lower():
            return v
    return None


def nms_language(code: str | None) -> str:
    """A Steam language code or a game file suffix -> the game file suffix ('english' when unknown)."""
    code = (code or "").strip().lower()
    if code in STEAM_TO_NMS:
        return STEAM_TO_NMS[code]
    return code if code in LANGUAGE_LABELS else "english"


def language_label(suffix: str) -> str:
    return LANGUAGE_LABELS.get(suffix, suffix.title())


def steam_roots() -> list[Path]:
    """Steam installation folders that may exist on this machine."""
    roots: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        roots.append(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam")
    else:
        home = Path.home()
        roots += [home / ".steam" / "steam", home / ".local" / "share" / "Steam",
                  home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"]
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def library_folders(steam_root: Path) -> list[Path]:
    """The Steam root plus every library folder listed in libraryfolders.vdf."""
    folders = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return folders
    for entry in (_ci(data, "libraryfolders") or {}).values():
        path = entry.get("path") if isinstance(entry, dict) else entry if isinstance(entry, str) else None
        if path and Path(path) not in folders:
            folders.append(Path(path))
    return folders


def read_manifest(acf: Path) -> dict:
    data = parse_vdf(acf.read_text(encoding="utf-8", errors="replace"))
    return _ci(data, "AppState") or {}


def find_game(env: dict | None = None, roots: list[Path] | None = None) -> GameInstall | None:
    """The installed game, or None when it cannot be found."""
    env = os.environ if env is None else env
    override_language = env.get("NMS_LANGUAGE")
    if env.get("NMS_GAME_DIR"):
        root = Path(env["NMS_GAME_DIR"])
        if (root / "GAMEDATA" / "PCBANKS").is_dir():
            return GameInstall(root, None, nms_language(override_language), "NMS_GAME_DIR")
        return None
    for steam in steam_roots() if roots is None else roots:
        for library in library_folders(steam):
            acf = library / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
            if not acf.is_file():
                continue
            try:
                state = read_manifest(acf)
            except OSError:
                continue
            root = library / "steamapps" / "common" / (_ci(state, "installdir") or "No Man's Sky")
            if not (root / "GAMEDATA" / "PCBANKS").is_dir():
                continue
            config = _ci(state, "UserConfig") or _ci(state, "MountedConfig") or {}
            language = override_language or (_ci(config, "language") if isinstance(config, dict) else None)
            return GameInstall(root, _ci(state, "buildid"), nms_language(language), "steam")
    return None
