"""The No Man's Sky connector: watches the save folder and presents the data.

Runs inside the 40k Assistant backend (plugin API 2). Reads save files, the
game's own data files (item names and icons) and - while the game runs - its
memory (planets and resources of the current system), all read-only; never
writes anything into the game or its folders. Network use: downloading the key
mapping (mapping.json) from MBINCompiler's GitHub releases.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from . import galaxy, memory, planets_view, route, saves, settlements, ships, timers, trade
from .game_install import GameInstall, find_game
from .gamedata import GameData
from .history import PlanetHistory, visits_from_save
from .live import LiveMemory
from .summary import mission_text_keys, summarize
from .watcher import SaveWatcher

POLL_S = 5
MAPPING_RELEASE_API = "https://api.github.com/repos/monkeyman192/MBINCompiler/releases/latest"
MAPPING_RECHECK_S = 24 * 3600
HTTP_TIMEOUT_S = 20
GAME_CHECK_S = 60          # how often to look for the game / a new game build
GAME_RETRY_S = 300         # after a failed item-database build
LIVE_EVERY_S = 5           # how often to look at the game's memory (a full scan only when needed, see live.py)
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


def _snapshot_item_ids(snap: dict) -> list[str]:
    rows = snap["exosuit"] + snap["exosuit_cargo"] + snap["freighter"]["inventory"]
    for ship in snap["ships"]:
        rows = rows + ship["inventory"]
    # The storage containers too: without them their items (shown since 0.9.0) had names but no icons.
    for chest in snap.get("storage") or []:
        rows = rows + chest["rows"]
    return list(dict.fromkeys(row[0] for row in rows))


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
        self.timers: list[dict] = []              # settlement constructions, expeditions (timers.py)
        self.timer_tables: dict | None = None     # durations from the game's files (timers.load_tables)
        self._timer_tables_for = None
        self.settlements: list[dict] = []         # your settlements' economy (settlements.py)
        self.settlement_tables: dict | None = None
        self.settlement_live = settlements.LiveSettlements(self.data_dir / "settlement_screen.json")
        self.ships: list[dict] = []               # your starships (ships.py)
        self.freighter: dict | None = None        # your freighter's technology (ships.freighter_from_save)
        self.galaxy_colors = "kind"               # how the galaxy map colours systems (planets_view.COLOR_MODES)
        self.ship_tables: dict | None = None      # warp-range bonuses from the game's technology tables   # the settlement screen's values (game memory)
        self.snapshot_file: str | None = None
        self.decoded_at: str | None = None
        self.decode_seconds: float | None = None
        self.unknown_keys = 0
        self.error: str | None = None
        self.gamedata = GameData(self.data_dir, getattr(ctx, "assets_dir", None))
        self.install: GameInstall | None = None
        self._game_checked = 0.0
        self._game_failed = 0.0
        self.history = PlanetHistory(self.data_dir / "planet_history.json")
        self.live = LiveMemory(self.history)
        self.visits: dict[int, dict] = {}
        self.anchor: bytes | None = None
        self.save_system: int | None = None
        self.save_position: dict | None = None   # {system, planet, at} of the newest save (where_you_are)
        self.route_path = self.data_dir / "route.json"
        self.route_state: dict = self._load_route()
        self.combat_timer: str | None = None
        self._live_checked = 0.0
        self.selected_system: int | None = None   # clicked in the visited-systems table
        self._planet_icons_ready = False          # names/icons of the recorded planets ensured since the last build
        self._force = asyncio.Event()

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self.ctx.spawn(self._run(), "save-watch")

    async def stop(self) -> None:
        await self.ctx.run_blocking(self._save_events)
        await self.ctx.run_blocking(self.live.close)

    def _load_route(self) -> dict:
        """The last route request (target, portal, range) and its result - kept across restarts."""
        try:
            data = json.loads(self.route_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_route(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.route_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.route_state), encoding="utf-8")
        tmp.replace(self.route_path)

    def _follow_route(self) -> bool:
        """Plan the stored route again from where you are now, when you moved since it was planned.

        A route shrinks as you fly it, and in the target system it says you arrived. Without this the page kept
        'From: <the system you planned in> (you)' after travelling (seen 2026-10-04). True when it changed.
        """
        request, result = self.route_state.get("request"), self.route_state.get("result") or {}
        origin = self.live.current_system if self.live.current_system is not None else self.save_system
        if not request or not result.get("ok") or origin is None or result["legs"][0]["from"] == origin:
            return False
        target = result["legs"][-1]["to"]
        if origin == target:
            self.route_state = {"request": request, "result": {"ok": False, "arrived": True, "target": target,
                                                               "reason": "you have arrived"}}
            self._save_route()
        else:
            self._plan_route(request)
        return True

    def _plan_route(self, params: dict) -> dict:
        """The plan_route action: form values are untrusted input, checked here before use."""
        target_text = str(params.get("target") or "")[:20]
        portal = str(params.get("portal") or "").strip()[:20]
        try:
            range_ly = float(params.get("range"))
        except (TypeError, ValueError):
            range_ly = 0.0
        request = {"target": target_text, "portal": portal, "range": range_ly if range_ly > 0 else None}
        origin = self.live.current_system if self.live.current_system is not None else self.save_system
        if origin is None:
            result = {"ok": False, "reason": "where you are is not known yet"}
        elif not 50 <= range_ly <= 20000:
            result = {"ok": False, "reason": "the jump range must be between 50 and 20,000 light years"}
        else:
            if portal:
                target = route.portal_to_key(portal, galaxy.galaxy_of(origin))
                reason = "the portal address must be 12 hex digits (0-9, A-F)"
            else:
                target = planets_view.parse_system_key(target_text)
                reason = "choose a target system"
            if target is None:
                result = {"ok": False, "reason": reason}
            else:
                target = memory.system_key(target)
                ctx = planets_view.Context(self.live, self.history, self.visits, self.gamedata, self.combat_timer,
                                           (self.snapshot or {}).get("bases") or [], origin=self.save_system)
                estimate = ships.primary_range(self.ships, self.ship_tables or ships.FALLBACK)
                colours = planets_view.reachable_stars(estimate["colours"]) if estimate else None
                result = route.plan_route(planets_view.route_nodes(ctx, colours), origin, target, range_ly)
                if colours is not None:
                    result["star_colours"] = sorted(colours)
        self.route_state = {"request": request, "result": result}
        self._save_route()
        if not result.get("ok"):
            return {"ok": False, "message": f"No route: {result['reason']}"}
        return {"ok": True, "focus": planets_view.ROUTE_RESULT_ID,
                "message": f"Route planned: {result['jumps']} jump(s), {galaxy.distance_text(result['distance'])}."}

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

    async def _ensure_gamedata(self, force: bool = False) -> None:
        """Find the game and (re)build the item database when the build or language changed."""
        now = time.time()
        if not force and now - self._game_checked < GAME_CHECK_S:
            return
        self._game_checked = now
        self.install = await self.ctx.run_blocking(find_game)
        build = getattr(self.install, "build_id", None)
        if self.timer_tables is None or build != self._timer_tables_for:
            self.timer_tables = await self.ctx.run_blocking(timers.load_tables, self.install)
            self._timer_tables_for = build
            if self.timer_tables.get("error"):
                self.ctx.logger.warning("[NMS] Timer durations: built-in values (%s)", self.timer_tables["error"])
            self.ship_tables = await self.ctx.run_blocking(ships.load_tables, self.install)
            if self.ship_tables.get("error"):
                self.ctx.logger.warning("[NMS] Warp range values: built-in (%s)", self.ship_tables["error"])
            self.settlement_tables = await self.ctx.run_blocking(settlements.load_tables, self.install)
            if self.settlement_tables.get("error"):
                self.ctx.logger.warning("[NMS] Settlement tables: built-in values (%s)", self.settlement_tables["error"])
            await self._ensure_settlement_texts()
        if self.install is None or (self.gamedata.matches(self.install) and not force):
            return
        if not force and self.gamedata.error and now - self._game_failed < GAME_RETRY_S:
            return
        await self.ctx.run_blocking(self.gamedata.load, self.install, force)
        self._planet_icons_ready = False
        if self.gamedata.error:
            self._game_failed = now
            self.ctx.logger.warning("[NMS] Item names unavailable: %s", self.gamedata.error)
        else:
            self.ctx.logger.info("[NMS] Item database: %d items, %s (build %s, %s s)", len(self.gamedata.items),
                                 self.gamedata.language_label, self.gamedata.build_id, self.gamedata.build_seconds)
            await self._ensure_icons()

    async def _ensure_settlement_texts(self) -> None:
        """Perk names and product icons of the Settlements tab and the current mission's text (cached by GameData
        after the first time)."""
        if not ((self.settlements or self.snapshot) and self.settlement_tables and self.install and self.gamedata.ready):
            return
        keys = settlements.text_keys(self.settlements, self.settlement_tables)
        keys |= set(mission_text_keys((self.snapshot or {}).get("current_mission")))
        await self.ctx.run_blocking(self.gamedata.resolve_texts, self.install, keys)
        await self.ctx.run_blocking(self.gamedata.ensure_icons, self.install, settlements.item_ids(self.settlements))

    async def _ensure_icons(self) -> None:
        if self.snapshot and self.install and self.gamedata.ready:
            tech = [t["id"] for s in self.ships for t in s["technology"]]
            await self.ctx.run_blocking(self.gamedata.ensure_icons, self.install, _snapshot_item_ids(self.snapshot) + tech)

    def _substances(self) -> set[str] | None:
        """Substance ids (the planet scan validates resources against them), when the item database is ready."""
        if not self.gamedata.ready:
            return None
        return {k for k, v in self.gamedata.items.items() if "SUBSTANCE" in (v.get("icon") or "")} or None

    async def _read_memory(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._live_checked < LIVE_EVERY_S:
            return
        self._live_checked = now
        if force:
            self.live.last_scan_at = None
        changed = await self.ctx.run_blocking(self.live.tick, self.anchor, self._substances(), now)
        await self.ctx.run_blocking(self._follow_route)
        seeds = [s["seed"] for s in self.settlements if s.get("seed")]
        # The settlement screen's values exist only while it is open: search for them in your system only.
        here = self.live.current_system if self.live.current_system is not None else self.save_system
        nearby = [s["seed"] for s in self.settlements if s.get("seed") and s.get("system") == here]
        if seeds and self.live.reader is not None and self.live.status == "ok":
            try:
                await self.ctx.run_blocking(self.settlement_live.tick, self.live.reader, seeds, nearby)
            except OSError as exc:      # the game closed mid-read: the next tick reopens it
                self.ctx.logger.debug("[NMS] Settlement stats not read: %s", exc)
        # Also once after a start or item-database rebuild (icons are cleared then), so planets recorded
        # earlier get their texts and icons - including the gas icons added in 0.4.0.
        if (changed or not self._planet_icons_ready) and self.install and self.gamedata.ready:
            self._planet_icons_ready = True
            planets = list(self.history.planets.values())
            keys = planets_view.info_keys(planets) | set(trade.ECONOMY_KEYS.values()) | set(trade.CONFLICT_KEYS.values())
            await self.ctx.run_blocking(self.gamedata.resolve_texts, self.install, keys)
            goods = [g for c in trade.CATEGORIES for g in trade.goods(c)]
            await self.ctx.run_blocking(self.gamedata.ensure_icons, self.install, planets_view.resource_ids(planets) + goods)

    async def _tick(self) -> None:
        await self._ensure_mapping()
        await self._ensure_gamedata()
        try:
            await self._tick_saves()
        finally:
            # After the save: the memory reader needs the save's anchor to find the player state.
            await self._read_memory()

    async def _tick_saves(self) -> None:
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
        self.visits = await self.ctx.run_blocking(visits_from_save, readable)
        self.timers = timers.timers_from_save(readable, self.timer_tables or timers.FALLBACK)
        self.settlements = settlements.settlements_from_save(readable)
        self.ships = ships.ships_from_save(readable)
        self.freighter = ships.freighter_from_save(readable)
        ps = (readable.get("BaseContext") or {}).get("PlayerStateData") or {}
        try:
            self.anchor = memory.ua_bytes(ps["GameStartAddress1"]) + memory.ua_bytes(ps["GameStartAddress2"])
            # Where you were at the last save: the galaxy map measures from here while no live position is known.
            self.save_system = memory.system_key(memory.pack_address(ps["UniverseAddress"]))
            self.save_position = {"system": self.save_system,
                                  "planet": ps["UniverseAddress"]["GalacticAddress"].get("PlanetIndex", 0),
                                  "at": datetime.fromtimestamp(save_file.mtime).isoformat(timespec="seconds")}
        except (KeyError, TypeError):
            self.anchor = None
        combat = (((ps.get("DifficultyState") or {}).get("Settings") or {}).get("GroundCombatTimers") or {})
        self.combat_timer = combat.get("CombatTimerDifficultyOption")
        self.snapshot_file = save_file.path.name
        self.unknown_keys = len(unknown)
        self.decode_seconds = round(time.perf_counter() - started, 2)
        self.decoded_at = datetime.now().isoformat(timespec="seconds")
        await self._ensure_icons()
        await self._ensure_settlement_texts()

    # ------------------------------------------------------------------ UI

    async def action(self, action_id: str, params: dict) -> dict:
        if action_id == planets_view.PLAN_ROUTE:
            return await self.ctx.run_blocking(self._plan_route, params or {})
        if action_id == planets_view.OPEN_SYSTEM:
            key = planets_view.parse_system_key((params or {}).get("key"))
            if key is None:
                return {"ok": False, "message": "Unknown system."}
            self.selected_system = key
            return {"ok": True, "focus": planets_view.SYSTEM_MAP_ID}
        if action_id == planets_view.GALAXY_COLORS:
            mode = str((params or {}).get("color_by") or "")
            if mode not in planets_view.COLOR_MODES:
                return {"ok": False, "message": "Unknown colouring."}
            self.galaxy_colors = mode
            return {"ok": True, "focus": planets_view.GALAXY_MAP_ID}
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
        if action_id == "rebuild_names":
            await self._ensure_gamedata(force=True)
            if self.install is None:
                return {"ok": False, "message": "No Man's Sky installation not found (set NMS_GAME_DIR)."}
            if self.gamedata.error:
                return {"ok": False, "message": f"Reading the game files failed: {self.gamedata.error}"}
            return {"ok": True, "message": f"{len(self.gamedata.items):,} item names read from the game "
                                           f"({self.gamedata.language_label})."}
        if action_id == "scan_memory":
            await self._read_memory(force=True)
            if self.live.status != "ok":
                return {"ok": False, "message": self.live.error or "No Man's Sky is not running."}
            return {"ok": True, "message": f"Read {self.live.last_scan_planets} planet(s) from the game in "
                                           f"{self.live.last_scan_seconds} s."}
        if action_id == "clear_history":
            self.watcher.events.clear()
            await self.ctx.run_blocking(self._save_events)
            return {"ok": True, "message": "Save history cleared."}
        raise ValueError(f"unknown action {action_id}")

    def _item_columns(self) -> list[str]:
        if self.gamedata.ready and self.gamedata.language != "english":
            return ["Name (English)", f"Name ({self.gamedata.language_label})", "Category", "Item id", "Amount", "Max"]
        return ["Name", "Category", "Item id", "Amount", "Max"]

    def _item_rows(self, rows: list[list], ctx) -> list[list]:
        """[id, amount, max] -> [{text, icon, hint}, (local name,) category, id, amount, max]: the game's names,
        icon and category; the tooltip holds the description and, for trade goods, where they sell."""
        bilingual = self.gamedata.ready and self.gamedata.language != "english"
        out = []
        for item_id, amount, maximum in rows:
            entry = self.gamedata.lookup(item_id) or {}
            name = ctx.texts.item(item_id, entry.get("en") or item_id)
            category = ctx.texts.category(item_id)
            out.append([name, entry.get("local"), category, item_id, amount, maximum] if bilingual
                       else [name, category, item_id, amount, maximum])
        return out

    def _storage_tab(self, snap: dict, ctx, columns: list[str]) -> dict:
        """The Storage tab: one table per storage container that holds something (containers 0-9 as numbered
        in the game), and which containers are empty."""
        sections, empty = [], []
        for chest in snap.get("storage") or []:
            if chest["number"] is not None:
                custom = chest["name"] if chest["name"] and not str(chest["name"]).startswith("BLD_") else None
                title = f"Storage Container {chest['number']}" + (f": {custom}" if custom else "")
            else:
                title = f"Other storage ({chest['key'].removesuffix('Inventory')})"
            if not chest["rows"]:
                empty.append(str(chest["number"]))
                continue
            sections.append({"type": "table", "title": f"{title} - {len(chest['rows'])} stacks", "columns": columns,
                             "rows": self._item_rows(chest["rows"], ctx)})
        if empty:
            sections.append({"type": "text", "text": f"Empty storage containers: {', '.join(empty)}."})
        if not sections:
            sections.append({"type": "text", "text": "No storage container in this save holds anything."})
        return {"id": "storage", "label": "Storage", "badge": sum(1 for c in snap.get("storage") or [] if c["rows"]) or None,
                "sections": sections}

    def _overview(self, snap: dict | None, ctx) -> list[dict]:
        out: list[dict] = []
        where = planets_view.where_you_are(ctx)
        if not snap:
            out.append({"type": "text", "text": "No save has been read yet: status, location and inventories appear "
                                                "once the connector has read a save file."})
            return out + ([where] if where else [])
        loc = snap["location"]
        out.append(timers.timers_section(self.timers, getattr(self.ctx, "section_types", ()), time.time()))
        out.append({"type": "stats", "title": "Status", "items": [
            {"label": "Units", "value": _fmt_int(snap["units"])},
            {"label": "Nanites", "value": _fmt_int(snap["nanites"])},
            {"label": "Quicksilver", "value": _fmt_int(snap["quicksilver"])},
            {"label": "Health", "value": snap["health"]},
            {"label": "Shield", "value": snap["shield"]},
            {"label": "Ship health", "value": snap["ship_health"]},
            {"label": "Play time", "value": _fmt_duration(snap["play_time_s"])},
        ]})
        if where:
            out.append(where)
        out.append({"type": "kv", "title": "Location (at the last save)", "items": [
            {"label": "Galaxy", "value": loc["galaxy"]},
            {"label": "Portal address", "value": loc["portal"]},
            {"label": "Region (voxel X, Y, Z)", "value": ", ".join(str(v) for v in loc["voxel"])},
            {"label": "System index", "value": loc["system_index"]},
            {"label": "Planet index", "value": loc["planet_index"]},
            {"label": "Bases in this system", "value": ", ".join(b["name"] for b in snap["bases"] if b["here"]) or "none"},
        ]})
        out.append({"type": "kv", "title": "Fleet and companions", "items": [
            {"label": "Primary ship", "value": self._primary_ship_text()},
            {"label": "Settlements", "value": self._settlements_text()},
            {"label": "Ships", "value": len(snap["ships"])},
            {"label": "Frigates", "value": snap["frigates"]},
            {"label": "Frigate expeditions", "value": snap["expeditions"]},
            {"label": "Companions (pets)", "value": snap["pets"]},
            {"label": "Freighter", "value": self._freighter_text(snap["freighter"]["name"])},
            {"label": "Current mission", "value": self._mission_text(snap["current_mission"])},
            {"label": "Difficulty", "value": snap["difficulty"]},
        ]})
        return out

    def _primary_ship_text(self) -> str:
        """'Bang (Fighter, class C) - warp range ~320-365 ly, red and green stars' (details in Ships & bases)."""
        primary = next((s for s in self.ships if s["primary"]), None)
        if primary is None:
            return "none"
        est = ships.warp_range(primary, self.ship_tables or ships.FALLBACK)
        stars = f", {' and '.join(est['colours'])} stars" if est["colours"] else ""
        return f"{ships.ship_label(primary)} ({primary['type']}, class {primary['class']}) - warp range {ships.range_text(est)}{stars}"

    def _freighter_text(self, name: str | None) -> str:
        """'Iron Maiden - warp range ~100 ly' (the freighter's hyperdrive, estimated like a ship's)."""
        label = name or "(unnamed)"
        if not self.freighter:
            return label
        est = ships.freighter_range(self.freighter, self.ship_tables or ships.FALLBACK)
        return f"{label} (class {self.freighter['class']}) - warp range {ships.range_text(est)}"

    def _settlements_text(self) -> str:
        """'Kay City: Farm in construction, decision waiting' - one line per settlement for the Overview."""
        if not self.settlements:
            return "none"
        parts = []
        for s in self.settlements:
            bits = [f"{s['building']} in construction"] if s.get("building") else []
            if s.get("pending") and s["pending"] != "None":
                bits.append("a decision is waiting")
            parts.append(f"{s['name']}: {', '.join(bits)}" if bits else s["name"])
        return "; ".join(parts) + " (see Settlements)"

    def _mission_text(self, mission_id: str | None) -> str:
        """The current mission as the game describes it, with its id; the id alone when no text is known."""
        if not mission_id:
            return "none"
        for key in mission_text_keys(mission_id):
            entry = self.gamedata.text(key)
            if entry:
                text = entry["en"] if len(entry["en"]) <= 220 else entry["en"][:217].rsplit(" ", 1)[0] + "..."
                return f"{text} ({mission_id})"
        return mission_id

    def _inventories(self, snap: dict | None, ctx) -> list[dict]:
        if not snap:
            return [{"type": "text", "text": "Inventories appear once a save has been read."}]
        columns = self._item_columns()
        hint = {"type": "text", "text": "Hover an item's name for its description; trade goods also tell where they "
                                        "sell and whether you know such a system."}
        tabs = [{"id": "exosuit", "label": "Exosuit", "sections": [hint,
            {"type": "table", "title": "Exosuit inventory", "columns": columns,
             "rows": self._item_rows(snap["exosuit"] + snap["exosuit_cargo"], ctx), "empty": "Empty"}]}]
        primary = next((s for s in snap["ships"] if s["primary"]), None)
        if primary:
            tabs.append({"id": "starship", "label": f"Starship: {primary['name']}", "sections": [
                {"type": "table", "title": f"Starship inventory: {primary['name']}", "columns": columns,
                 "rows": self._item_rows(primary["inventory"], ctx), "empty": "Empty"}]})
        tabs.append({"id": "freighter", "label": "Freighter", "sections": [
            {"type": "table", "title": "Freighter inventory", "columns": columns,
             "rows": self._item_rows(snap["freighter"]["inventory"], ctx), "empty": "Empty"}]})
        tabs.append(self._storage_tab(snap, ctx, columns))
        return [{"type": "tabs", "id": "inventory-tabs", "tabs": tabs}]

    def _fleet(self, snap: dict | None, ctx) -> list[dict]:
        if not snap:
            return [{"type": "text", "text": "Ships and bases appear once a save has been read."}]
        return ships.ship_sections(self.ships, self.ship_tables or ships.FALLBACK, ctx.texts) + [
            {"type": "table", "title": "Bases", "columns": ["Name", "Type", "Galaxy", "Portal address", "Parts"],
             "rows": [[b["name"], b["type"], b["galaxy"], b["portal"], b["objects"]] for b in snap["bases"]]},
        ]

    def _saves(self, snap: dict | None, ctx) -> list[dict]:
        sections: list[dict] = []
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
        if self.install:
            game = f"{self.install.root} (build {self.install.build_id})" if self.install.build_id else str(self.install.root)
            source.append({"label": "Game folder", "value": game})
        if self.gamedata.ready:
            source.append({"label": "Item names", "value":
                           f"{len(self.gamedata.items):,} items in English and {self.gamedata.language_label}, "
                           f"read from the game files {self.gamedata.built_at or ''}".strip()})
        live = {"ok": "reading NMS.exe" + (f" - last scan {self.live.last_scan_iso}, {self.live.last_scan_seconds} s, "
                                           f"{self.live.last_scan_bytes / 2**30:.1f} GB, {self.live.last_scan_planets} planet(s)"
                                           if self.live.last_scan_iso else ""),
                "not-running": "the game is not running", "idle": "waiting"}.get(self.live.status, self.live.error)
        source.append({"label": "Game memory (read-only)", "value": live})
        source.append({"label": "Planets recorded", "value":
                       f"{len(self.history.planets)} in {len(self.history.systems())} system(s), "
                       f"kept in {self.history.path} (previous version: .json.bak)"})
        if self.gamedata.icon_error:
            source.append({"label": "Last icon problem", "value": self.gamedata.icon_error})
        if snap:
            source.append({"label": "Save format version", "value": snap["save_version"]})
        sections.append({"type": "kv", "title": "Source", "items": source})
        sections.append(planets_view.scan_log_section(ctx, self.history.scans))
        return sections

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
        if self.install is None and self._game_checked:
            sections.append({"type": "notice", "level": "info", "text":
                             "Item names and icons come from the game's own files, but the No Man's Sky installation "
                             "was not found in any Steam library. Set NMS_GAME_DIR to the game folder to use another one."})
        elif self.gamedata.error:
            sections.append({"type": "notice", "level": "warn", "text":
                             f"Item names and icons are unavailable: {self.gamedata.error}"})

        snap = self.snapshot
        ctx = planets_view.Context(self.live, self.history, self.visits, self.gamedata, self.combat_timer,
                                   snap["bases"] if snap else [], origin=self.save_system,
                                   save_position=self.save_position)
        sections.append({"type": "tabs", "id": "main", "tabs": [
            {"id": "overview", "label": "Overview", "sections": self._overview(snap, ctx)},
            {"id": "systems", "label": "Systems", "badge": len(ctx.keys()) or None,
             "sections": [planets_view.systems_tabs(ctx, self.selected_system, self.route_state,
                                                    ships.primary_range(self.ships, self.ship_tables or ships.FALLBACK),
                                                    self.galaxy_colors)]},
            {"id": "inventory", "label": "Inventory", "sections": self._inventories(snap, ctx)},
            {"id": "fleet", "label": "Ships & bases", "sections": self._fleet(snap, ctx)},
            {"id": "settlements", "label": "Settlements", "badge": len(self.settlements) or None,
             "sections": settlements.settlement_sections(self.settlements, self.settlement_tables or settlements.FALLBACK,
                                                         ctx.texts, time.time(), self.settlement_live.values)},
            {"id": "saves", "label": "Saves & source", "sections": self._saves(snap, ctx)},
        ]})
        return {
            "title": "No Man's Sky",
            "subtitle": "Read from your save files (updates whenever the game saves) and, while it runs, from the game.",
            "updated_at": self.decoded_at,
            "actions": [
                {"id": "rescan", "label": "Rescan", "description": "Read the newest save file again now."},
                {"id": "update_mapping", "label": "Update key mapping",
                 "description": "Download the newest mapping.json from MBINCompiler (needed after game updates)."},
                {"id": "scan_memory", "label": "Scan game now",
                 "description": "Read the planets of the current system from the running game now (read-only, ~10 s)."},
                {"id": "rebuild_names", "label": "Re-read item names",
                 "description": "Read item names and icons from the game files again (done automatically after a game update)."},
                {"id": "clear_history", "label": "Clear save history", "description": "Forget the recorded save writes.",
                 "confirm": "Clear the recorded save history?"},
            ],
            "sections": sections,
        }
