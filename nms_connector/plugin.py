"""The No Man's Sky connector: watches the save folder and the running game and holds what it read.

Runs inside the 40k Assistant backend (plugin API 2). Reads save files, the game's own data files (item names,
icons, tables) and - while the game runs - its memory (planets and resources of the current system), all
read-only; never writes anything into the game or its folders. Network use: downloading the key mapping
(mapping.json) from MBINCompiler's GitHub releases.

``NmsConnector`` owns the state and the work loop (a tick every 5 s: key mapping, game files, newest save, game
memory) and the page's actions. Presenting it is delegated:

* ``page.ConnectorPage`` - the view (tabs, tables, notices);
* ``companion.PluginCompanion`` - the persona it brings and the game data for each of its chat replies;
* ``describe.StateText`` - one-line summaries both of them use;
* ``tables.GameTables`` - the game-file tables (timers, frigate traits, warp range, settlements, technology stats).
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from . import equipment, frigates, galaxy, memory, planets_view, positions, route, saves, settlements, ships, starmap, timers, trade
from .companion import PluginCompanion
from .describe import StateText
from .game_install import GameInstall, find_game
from .gamedata import GameData
from .history import PlanetHistory, visits_from_save
from .live import LiveMemory
from .page import ConnectorPage
from .summary import mission_text_keys, summarize
from .tables import GameTables
from .watcher import SaveWatcher

POLL_S = 5
CAMERA_EVERY_S = 1         # PROTOTYPE star fixes: how often the galaxy map camera is sampled while the game runs
MAPPING_RELEASE_API = "https://api.github.com/repos/monkeyman192/MBINCompiler/releases/latest"
MAPPING_RECHECK_S = 24 * 3600
HTTP_TIMEOUT_S = 20
GAME_CHECK_S = 60          # how often to look for the game / a new game build
GAME_RETRY_S = 300         # after a failed item-database build
LIVE_EVERY_S = 5           # how often to look at the game's memory (a full scan only when needed, see live.py)
USER_AGENT = "40k-assistant-nomanssky (https://github.com/trontronicent/40k-assistant-nomanssky)"


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
    """The plugin instance the app creates (``create_plugin``): state, work loop, actions; view and chat are
    delegated (see the module docstring)."""

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
        self.tables = GameTables()                # timers, frigate traits, warp range, settlements, tech stats
        self.timers: list[dict] = []              # settlement constructions, expeditions (timers.py)
        self.settlements: list[dict] = []         # your settlements' economy (settlements.py)
        self.settlement_live = settlements.LiveSettlements(self.data_dir / "settlement_screen.json")  # screen values
        self.ships: list[dict] = []               # your starships (ships.py)
        self.freighter: dict | None = None        # your freighter's technology (ships.freighter_from_save)
        self.equipment: equipment.Equipment | None = None   # exosuit, multi-tools, exocraft, freighter technology
        self.frigates: list[dict] = []            # your frigates (frigates.py)
        self.galaxy_colors = "kind"               # how the galaxy map colours systems (planets_view.COLOR_MODES)
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
        galaxy.set_positions(self.history.positions)
        # PROTOTYPE: star positions from the galaxy map camera (positions.py), named by the user on the page.
        self.camera = positions.CameraReader()
        self.star_fixer = positions.StarFixer(self.history.star_fixes)
        self.starmap = starmap.StarmapReader()        # the galaxy map's star records around you (game memory)
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
        self.describe = StateText(self)
        self.page = ConnectorPage(self)
        self.companion = PluginCompanion(self)

    # ------------------------------------------------------------------ shared views of the state

    @property
    def game_checked(self) -> bool:
        """True once the game installation has been looked for (until then 'not found' would be premature)."""
        return bool(self._game_checked)

    def here(self) -> int | None:
        """The system you are in: live from the game, else where the newest save was written."""
        return self.live.current_system if self.live.current_system is not None else self.save_system

    def context(self) -> planets_view.Context:
        """Everything the system, planet and item sections are built from, as of now."""
        snap = self.snapshot
        return planets_view.Context(self.live, self.history, self.visits, self.gamedata, self.combat_timer,
                                    snap["bases"] if snap else [], origin=self.save_system,
                                    save_position=self.save_position)

    def primary_range(self) -> dict | None:
        """The primary ship's warp-range estimate (route planner default, galaxy map reach)."""
        return ships.primary_range(self.ships, self.tables.ship_ranges)

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self.ctx.spawn(self._run(), "save-watch")
        self.ctx.spawn(self._camera_loop(), "map-camera")

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

    def _sample_camera(self, now: float) -> list[dict]:
        """PROTOTYPE: one galaxy-map camera sample; new or refined star fixes are saved (blocking)."""
        changed = self.star_fixer.feed(self.camera.read(self.live.reader, now))
        if changed:
            self.history.save()
            for fix in changed:
                self.ctx.logger.info("[NMS] Star fix %d (prototype): %s from %d lines of sight, miss %.2f LJ",
                                     fix["id"], fix["position"], fix["rays"], fix["miss_ly"])
        return changed

    async def _camera_loop(self) -> None:
        """PROTOTYPE: sample the galaxy map camera every CAMERA_EVERY_S while the game is read; a lock seen from
        two directions becomes a star fix (positions.StarFixer). 0x260 bytes per sample; never dies."""
        while True:
            try:
                if self.live.reader is not None and self.live.status == "ok":
                    await self.ctx.run_blocking(self._sample_camera, time.time())
            except asyncio.CancelledError:
                raise
            except OSError as exc:      # the game closed mid-read: the next sample reopens nothing, LiveMemory does
                self.ctx.logger.debug("[NMS] Map camera not read: %s", exc)
            except Exception as exc:
                self.ctx.logger.warning("[NMS] Map camera sample failed: %s: %s", type(exc).__name__, exc)
            await asyncio.sleep(CAMERA_EVERY_S)

    def _name_fix(self, params: dict) -> dict:
        """PROTOTYPE action: name a star fix as a system (or forget it). Params are untrusted input."""
        try:
            fix_id = int(str(params.get("fix") or "").strip())
        except ValueError:
            return {"ok": False, "message": "Choose a star fix."}
        fix = next((f for f in self.history.star_fixes if f["id"] == fix_id), None)
        if fix is None:
            return {"ok": False, "message": f"Star fix {fix_id} does not exist (any more)."}
        if params.get("forget") is True or str(params.get("system") or "") == positions.FORGET:
            self.history.star_fixes.remove(fix)
            message = f"Star fix {fix_id} forgotten."
        else:
            key = planets_view.parse_system_key(params.get("system"))
            if key is None:
                return {"ok": False, "message": "Choose the system this star is."}
            key = memory.system_key(key)
            for other in self.history.star_fixes:      # one fix per system: the newer naming wins
                if other is not fix and other.get("system") == f"{key:x}":
                    other["system"] = None
            fix["system"] = f"{key:x}"
            message = f"Star fix {fix_id} is now {planets_view._system_label(key, self.context().visit(key))} (prototype)."
        galaxy.set_positions(self.history.positions)
        self.history.save()
        return {"ok": True, "message": message, "focus": planets_view.STAR_FIX_ID}

    def _follow_route(self) -> bool:
        """Plan the stored route again from where you are now, when you moved since it was planned.

        A route shrinks as you fly it, and in the target system it says you arrived. Without this the page kept
        'From: <the system you planned in> (you)' after travelling (seen 2026-10-04). True when it changed.
        """
        request, result = self.route_state.get("request"), self.route_state.get("result") or {}
        origin = self.here()
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
        origin = self.here()
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
                ctx = self.context()
                estimate = self.primary_range()
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
        """Load the save-key mapping, and download it when missing, forced or stale (unknown keys, at most
        daily); after a failure it waits 60 s before trying again."""
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
        """The work loop: a tick every POLL_S seconds, or at once when an action asks (``_force``); never dies."""
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
        if self.tables.needs_load(self.install):
            for warning in await self.ctx.run_blocking(self.tables.load, self.install):
                self.ctx.logger.warning("[NMS] %s", warning)
            self.gamedata.tech = self.tables.tech       # Texts.modifiers: what each technology does
            await self._ensure_texts()
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

    async def _ensure_texts(self) -> None:
        """The game texts the page and the persona need beyond item names - perk names, the current mission,
        frigate traits, technology stat names, exocraft names - and the settlement/frigate icons (cached by GameData
        after the first time)."""
        if not ((self.settlements or self.snapshot) and self.tables.loaded and self.install and self.gamedata.ready):
            return
        keys = settlements.text_keys(self.settlements, self.tables.settlement_rules)
        keys |= set(mission_text_keys((self.snapshot or {}).get("current_mission")))
        keys |= frigates.text_keys(self.frigates, self.tables.trait_names)
        keys |= self.tables.tech.text_keys() | {k for k in equipment.VEHICLE_KEYS if k}
        await self.ctx.run_blocking(self.gamedata.resolve_texts, self.install, keys)
        await self.ctx.run_blocking(self.gamedata.ensure_icons, self.install,
                                    settlements.item_ids(self.settlements) + settlements.icon_ids()
                                    + list(frigates.icon_textures()))

    async def _ensure_icons(self) -> None:
        if self.snapshot and self.install and self.gamedata.ready:
            tech = [t["id"] for s in self.ships for t in s["technology"]]
            tech += self.equipment.item_ids() if self.equipment else []
            await self.ctx.run_blocking(self.gamedata.ensure_icons, self.install, _snapshot_item_ids(self.snapshot) + tech)

    def _substances(self) -> set[str] | None:
        """Substance ids (the planet scan validates resources against them), when the item database is ready."""
        if not self.gamedata.ready:
            return None
        return {k for k, v in self.gamedata.items.items() if "SUBSTANCE" in (v.get("icon") or "")} or None

    async def _read_memory(self, force: bool = False) -> None:
        """Read the running game (every LIVE_EVERY_S): position and planets (LiveMemory), the route, the
        exact system position, the galaxy map's star records, the settlement screen and new planets' texts."""
        now = time.time()
        if not force and now - self._live_checked < LIVE_EVERY_S:
            return
        self._live_checked = now
        if force:
            self.live.last_scan_at = None
        changed = await self.ctx.run_blocking(self.live.tick, self.anchor, self._substances(), now)
        await self.ctx.run_blocking(self._follow_route)
        if self.live.reader is not None and self.live.status == "ok" and self.live.current_system is not None                 and self.starmap.due(now):
            try:
                found = await self.ctx.run_blocking(self.starmap.scan, self.live.reader, self.live.current_system)
                changed = self.history.record_economies(found, datetime.now().isoformat(timespec="seconds"), "galaxy map")
                if changed:
                    await self.ctx.run_blocking(self.history.save)
                self.ctx.logger.info("[NMS] Galaxy map: %d star records read (%d new or changed) in %s s",
                                     len(found), changed, self.starmap.last_scan_seconds)
            except OSError as exc:      # the game closed mid-read
                self.ctx.logger.debug("[NMS] Galaxy map not read: %s", exc)
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
        """Find the save folder, record new save writes and decode the newest settled save."""
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
        """Read one save file into the connector's state: snapshot, visits, settlements and timers, ships,
        equipment, frigates, the memory anchor and where you were; then icons and texts."""
        started = time.perf_counter()
        try:
            readable, unknown = await self.ctx.run_blocking(saves.read_save, save_file.path, self.mapping)
        except saves.SaveFormatError as exc:
            self.error = f"{save_file.path.name}: {exc}"
            return
        self.snapshot = await self.ctx.run_blocking(summarize, readable)
        self.visits = await self.ctx.run_blocking(visits_from_save, readable)
        self.settlements = settlements.settlements_from_save(readable)
        self.timers = sorted(timers.timers_from_save(readable, self.tables.timer_durations)
                             + settlements.decision_timers(self.settlements, self.tables.settlement_rules),
                             key=lambda t: t["ends_at"])
        self.ships = ships.ships_from_save(readable)
        self.freighter = ships.freighter_from_save(readable)
        self.equipment = equipment.Equipment.from_save(readable)
        self.frigates = frigates.frigates_from_save(readable)
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
        await self._ensure_texts()

    # ------------------------------------------------------------------ UI

    async def action(self, action_id: str, params: dict) -> dict:
        """Run one of the page's actions (buttons, forms, row clicks); params are untrusted input."""
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
        if action_id == planets_view.NAME_FIX:
            return await self.ctx.run_blocking(self._name_fix, params or {})
        if action_id == "clear_history":
            self.watcher.events.clear()
            await self.ctx.run_blocking(self._save_events)
            return {"ok": True, "message": "Save history cleared."}
        raise ValueError(f"unknown action {action_id}")

    # ------------------------------------------------------------------ what the app calls

    def view(self) -> dict:
        """The page (see page.py)."""
        return self.page.view()

    def personas(self) -> list[dict]:
        """The persona this plugin brings (see companion.py; app 3.9.0)."""
        return self.companion.personas()

    def chat_context(self, question: str) -> dict:
        """The game data for one chat reply of a persona that draws on this plugin (see companion.py)."""
        return self.companion.chat_context(question)
