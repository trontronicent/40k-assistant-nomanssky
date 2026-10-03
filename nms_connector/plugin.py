"""The No Man's Sky connector: watches the save folder and presents the data.

Runs inside the 40k Assistant backend (plugin API 2). Reads save files only;
never writes anything into the game's folders. Network use: downloading the
key mapping (mapping.json) from MBINCompiler's GitHub releases.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from . import saves
from .summary import summarize
from .watcher import SaveWatcher

POLL_S = 5
MAPPING_RELEASE_API = "https://api.github.com/repos/monkeyman192/MBINCompiler/releases/latest"
MAPPING_RECHECK_S = 24 * 3600
HTTP_TIMEOUT_S = 20
USER_AGENT = "40k-assistant-nomanssky (https://github.com/trontronicent/40k-assistant-nomanssky)"


def _fmt_int(value) -> str:
    return f"{value:,}" if isinstance(value, int) else "–"


def _fmt_duration(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return "–"
    seconds = int(seconds)
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{seconds // 60} min {seconds % 60:02d} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


def download_mapping(dest: Path) -> str:
    """Fetch mapping.json from the latest MBINCompiler release; return the release tag (blocking)."""
    request = urllib.request.Request(MAPPING_RELEASE_API, headers={"User-Agent": USER_AGENT,
                                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        release = json.loads(response.read().decode("utf-8"))
    asset = next((a for a in release.get("assets", []) if a.get("name") == "mapping.json"), None)
    if asset is None:
        raise RuntimeError(f"release {release.get('tag_name')} has no mapping.json")
    request = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        data = response.read()
    parsed = json.loads(data.decode("utf-8"))
    if not isinstance(parsed.get("Mapping"), list):
        raise RuntimeError("downloaded mapping.json has no Mapping list")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    meta = {"tag": release.get("tag_name"), "libmbin": parsed.get("libMBIN_version"),
            "downloaded_at": datetime.now().isoformat(timespec="seconds")}
    dest.with_name("mapping_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta["tag"]


class NmsConnector:
    def __init__(self, ctx):
        self.ctx = ctx
        self.data_dir: Path = ctx.data_dir
        self.mapping_path = self.data_dir / "mapping.json"
        self.events_path = self.data_dir / "save_events.json"
        self.watcher = SaveWatcher(events=self._load_events())
        self.mapping: dict[str, str] | None = None
        self.mapping_meta: dict = {}
        self.mapping_error: str | None = None
        self._last_mapping_attempt = 0.0
        self.save_dir: Path | None = None
        self.snapshot: dict | None = None
        self.snapshot_file: str | None = None
        self.decoded_at: str | None = None
        self.decode_seconds: float | None = None
        self.unknown_keys = 0
        self.error: str | None = None
        self._force = asyncio.Event()

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self.ctx.spawn(self._run(), "save-watch")

    async def stop(self) -> None:
        await self.ctx.run_blocking(self._save_events)

    def _load_events(self) -> list[dict]:
        try:
            events = json.loads(self.events_path.read_text(encoding="utf-8"))
            return events if isinstance(events, list) else []
        except (OSError, ValueError):
            return []

    def _save_events(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.events_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.watcher.events), encoding="utf-8")
        tmp.replace(self.events_path)

    async def _ensure_mapping(self, force: bool = False) -> None:
        if self.mapping is None and self.mapping_path.is_file() and not force:
            self.mapping = await self.ctx.run_blocking(saves.load_mapping, self.mapping_path)
            try:
                self.mapping_meta = json.loads(self.mapping_path.with_name("mapping_meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.mapping_meta = {}
        stale = self.unknown_keys > 0 and time.time() - self._last_mapping_attempt > MAPPING_RECHECK_S
        if self.mapping is not None and not force and not stale:
            return
        if not force and time.time() - self._last_mapping_attempt < 60:
            return  # do not hammer GitHub after a failure
        self._last_mapping_attempt = time.time()
        try:
            tag = await self.ctx.run_blocking(download_mapping, self.mapping_path)
            self.mapping = await self.ctx.run_blocking(saves.load_mapping, self.mapping_path)
            self.mapping_meta = json.loads(self.mapping_path.with_name("mapping_meta.json").read_text(encoding="utf-8"))
            self.mapping_error = None
            self.ctx.logger.info("[NMS] Key mapping %s downloaded (%d keys)", tag, len(self.mapping))
        except Exception as exc:
            self.mapping_error = f"{type(exc).__name__}: {exc}"
            self.ctx.logger.warning("[NMS] Could not download the key mapping: %s", self.mapping_error)

    async def _run(self) -> None:
        while True:
            try:
                await self._tick()
                self.error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                self.ctx.logger.warning("[NMS] Watch cycle failed: %s", self.error)
            try:
                await asyncio.wait_for(self._force.wait(), POLL_S)
            except asyncio.TimeoutError:
                pass
            self._force.clear()

    async def _tick(self) -> None:
        await self._ensure_mapping()
        dirs = await self.ctx.run_blocking(saves.find_save_dirs)
        self.save_dir = dirs[0] if dirs else None
        if self.save_dir is None:
            return
        files = await self.ctx.run_blocking(saves.list_save_files, self.save_dir)
        before = len(self.watcher.events)
        ready = self.watcher.poll(files, time.time())
        if len(self.watcher.events) != before:
            await self.ctx.run_blocking(self._save_events)
        if ready and self.mapping is not None:
            await self._decode(max(ready, key=lambda f: f.mtime))
        elif self.snapshot is None and files and self.mapping is not None:
            await self._decode(max(files, key=lambda f: f.mtime))

    async def _decode(self, save_file: saves.SaveFile) -> None:
        started = time.perf_counter()
        try:
            readable, unknown = await self.ctx.run_blocking(saves.read_save, save_file.path, self.mapping)
        except saves.SaveFormatError as exc:
            self.error = f"{save_file.path.name}: {exc}"
            return
        self.snapshot = await self.ctx.run_blocking(summarize, readable)
        self.snapshot_file = save_file.path.name
        self.unknown_keys = len(unknown)
        self.decode_seconds = round(time.perf_counter() - started, 2)
        self.decoded_at = datetime.now().isoformat(timespec="seconds")

    # ------------------------------------------------------------------ UI

    async def action(self, action_id: str, params: dict) -> dict:
        if action_id == "rescan":
            self.snapshot = None
            self._force.set()
            return {"ok": True, "message": "Reading the newest save again."}
        if action_id == "update_mapping":
            await self._ensure_mapping(force=True)
            if self.mapping_error:
                return {"ok": False, "message": f"Download failed: {self.mapping_error}"}
            self.snapshot = None
            self._force.set()
            return {"ok": True, "message": f"Key mapping {self.mapping_meta.get('tag')} downloaded."}
        if action_id == "clear_history":
            self.watcher.events.clear()
            await self.ctx.run_blocking(self._save_events)
            return {"ok": True, "message": "Save history cleared."}
        raise ValueError(f"unknown action {action_id}")

    def view(self) -> dict:
        sections: list[dict] = []
        if self.save_dir is None:
            sections.append({"type": "notice", "level": "warn", "text":
                             "No No Man's Sky saves found. Expected under %APPDATA%\\HelloGames\\NMS (Windows) "
                             "or the Steam Proton folder (Linux); set NMS_SAVE_DIR to override."})
        if self.mapping is None:
            sections.append({"type": "notice", "level": "warn" if self.mapping_error else "info", "text":
                             f"Key mapping not available yet ({self.mapping_error})." if self.mapping_error
                             else "Downloading the key mapping (mapping.json) from MBINCompiler…"})
        if self.unknown_keys:
            sections.append({"type": "notice", "level": "warn", "text":
                             f"{self.unknown_keys} save keys are unknown to the current mapping (probably a game "
                             "update). Press 'Update key mapping'."})
        if self.error:
            sections.append({"type": "notice", "level": "error", "text": self.error})

        snap = self.snapshot
        if snap:
            loc = snap["location"]
            sections.append({"type": "stats", "title": "Status", "items": [
                {"label": "Units", "value": _fmt_int(snap["units"])},
                {"label": "Nanites", "value": _fmt_int(snap["nanites"])},
                {"label": "Quicksilver", "value": _fmt_int(snap["quicksilver"])},
                {"label": "Health", "value": snap["health"]},
                {"label": "Shield", "value": snap["shield"]},
                {"label": "Ship health", "value": snap["ship_health"]},
                {"label": "Play time", "value": _fmt_duration(snap["play_time_s"])},
            ]})
            sections.append({"type": "kv", "title": "Location (at the last save)", "items": [
                {"label": "Galaxy", "value": loc["galaxy"]},
                {"label": "Portal address", "value": loc["portal"]},
                {"label": "Region (voxel X, Y, Z)", "value": ", ".join(str(v) for v in loc["voxel"])},
                {"label": "System index", "value": loc["system_index"]},
                {"label": "Planet index", "value": loc["planet_index"]},
                {"label": "Bases in this system", "value": ", ".join(b["name"] for b in snap["bases"] if b["here"]) or "none"},
            ]})
            mission = snap["current_mission"]
            sections.append({"type": "kv", "title": "Fleet and companions", "items": [
                {"label": "Ships", "value": len(snap["ships"])},
                {"label": "Frigates", "value": snap["frigates"]},
                {"label": "Frigate expeditions", "value": snap["expeditions"]},
                {"label": "Companions (pets)", "value": snap["pets"]},
                {"label": "Freighter", "value": snap["freighter"]["name"] or "(unnamed)"},
                {"label": "Current mission id", "value": mission or "none"},
                {"label": "Difficulty", "value": snap["difficulty"]},
            ]})
            sections.append({"type": "table", "title": "Exosuit inventory", "columns": ["Item id", "Amount", "Max"],
                             "rows": snap["exosuit"] + snap["exosuit_cargo"], "empty": "Empty"})
            primary = next((s for s in snap["ships"] if s["primary"]), None)
            if primary:
                sections.append({"type": "table", "title": f"Starship inventory: {primary['name']}",
                                 "columns": ["Item id", "Amount", "Max"], "rows": primary["inventory"], "empty": "Empty"})
            sections.append({"type": "table", "title": "Freighter inventory", "columns": ["Item id", "Amount", "Max"],
                             "rows": snap["freighter"]["inventory"], "empty": "Empty"})
            sections.append({"type": "table", "title": "Ships", "columns": ["Name", "Class", "Primary"],
                             "rows": [[s["name"], s["class"], "yes" if s["primary"] else ""] for s in snap["ships"]]})
            sections.append({"type": "table", "title": "Bases", "columns": ["Name", "Type", "Galaxy", "Portal address", "Parts"],
                             "rows": [[b["name"], b["type"], b["galaxy"], b["portal"], b["objects"]] for b in snap["bases"]]})

        stats = self.watcher.stats()
        sections.append({"type": "kv", "title": "How often the game saves (measured)", "items": [
            {"label": "Save writes recorded", "value": stats["writes"]},
            {"label": "Typical interval while playing", "value": _fmt_duration(stats["median_interval_s"])},
            {"label": "Shortest / longest", "value": f"{_fmt_duration(stats['shortest_interval_s'])} / {_fmt_duration(stats['longest_interval_s'])}"},
        ]})
        sections.append({"type": "table", "title": "Recent save writes", "columns": ["Time", "File", "Slot", "Size (kB)", "Since previous"],
                         "rows": [[e["at"], e["file"], e["slot"], round(e["size"] / 1024), _fmt_duration(e["since_previous_s"])]
                                  for e in reversed(self.watcher.events[-50:])],
                         "empty": "No save written since the connector started. Play and save (or let the game autosave)."})
        source = [
            {"label": "Save folder", "value": str(self.save_dir) if self.save_dir else "not found"},
            {"label": "Read from", "value": self.snapshot_file or "–"},
            {"label": "Read at", "value": self.decoded_at or "–"},
            {"label": "Decode time", "value": f"{self.decode_seconds} s" if self.decode_seconds is not None else "–"},
            {"label": "Key mapping", "value": f"{self.mapping_meta.get('tag', '?')} ({len(self.mapping)} keys)" if self.mapping else "–"},
        ]
        if snap:
            source.append({"label": "Save format version", "value": snap["save_version"]})
        sections.append({"type": "kv", "title": "Source", "items": source})
        return {
            "title": "No Man's Sky",
            "subtitle": "Read from your save files; updates whenever the game saves.",
            "updated_at": self.decoded_at,
            "actions": [
                {"id": "rescan", "label": "Rescan", "description": "Read the newest save file again now."},
                {"id": "update_mapping", "label": "Update key mapping",
                 "description": "Download the newest mapping.json from MBINCompiler (needed after game updates)."},
                {"id": "clear_history", "label": "Clear save history", "description": "Forget the recorded save writes.",
                 "confirm": "Clear the recorded save history?"},
            ],
            "sections": sections,
        }
