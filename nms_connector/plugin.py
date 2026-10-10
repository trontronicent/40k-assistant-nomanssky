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
import contextlib
import gc
import json
import time
import urllib.request
from datetime import datetime
from functools import cached_property
from pathlib import Path

from . import codex_sync, discoveries, equipment, frigates, galaxy, hgpak, logs, memory, planet_search, planets_view, positions, route, saves, settlements, ships, starmap, timers, trade
from .companion import PluginCompanion
from .describe import StateText
from .game_install import GameInstall, find_game
from .gamedata import GameData
from .history import PlanetHistory, visits_from_save
from .live import LiveMemory
from .page import ConnectorPage
from .settings import PluginSettings
from .summary import mission_text_keys, summarize
from .store import TableStore
from .tables import GameTables
from .watcher import SaveWatcher

POLL_S = 5
SAVE_SETTINGS = "save_settings"   # the Settings tab's form
SET_SETTING = "set_setting"       # one on/off setting from the app's overlay ({id, value})
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


def _on_off(flag: bool) -> str:
    return "on" if flag else "off"


class NmsConnector:
    """The plugin instance the app creates (``create_plugin``): state, work loop, actions; view and chat are
    delegated (see the module docstring)."""

    def __init__(self, ctx):
        self.ctx = ctx
        logs.bind(ctx.logger)        # every module logs through the host's plugin logger (category tag)
        self.data_dir: Path = ctx.data_dir
        self._heavy_load = False                # set by a pass over the game files; the next collect resets it
        self.mapping_path = self.data_dir / "mapping.json"
        self.events_path = self.data_dir / "save_events.json"
        self.watcher = SaveWatcher(events=self._load_events())
        self.mapping: dict[str, str] | None = None
        self.mapping_meta: dict = {}
        self.mapping_error: str | None = None
        self._last_mapping_attempt = 0.0
        self.save_dir: Path | None = None
        self.tables = GameTables(TableStore(self.data_dir))                # timers, frigate traits, warp range, settlements, tech stats
        self.settlement_live = settlements.LiveSettlements(self.data_dir / "settlement_screen.json")  # screen values
        self.galaxy_colors = "kind"               # how the galaxy map colours systems (planets_view.COLOR_MODES)
        self.planet_query = ""                    # Systems -> Planets search (planet_search)
        self.settings_path = self.data_dir / "settings.json"
        self.settings = PluginSettings.load(self.settings_path)   # Settings tab: single context, codeword
        self.error: str | None = None
        self.gamedata = GameData(self.data_dir, getattr(ctx, "assets_dir", None))
        self.install: GameInstall | None = None
        self.codex_publisher = codex_sync.CodexPublisher(self.data_dir)   # the generated Codex documents (app 3.15.0)
        self._game_checked = 0.0
        self._game_failed = 0.0
        self.history = PlanetHistory(self.data_dir / "planet_history.json")
        galaxy.set_positions(self.history.positions)
        # PROTOTYPE: star positions from the galaxy map camera (positions.py), named by the user on the page.
        self.camera = positions.CameraReader()
        self.star_fixer = positions.StarFixer(self.history.star_fixes)
        self.starmap = starmap.StarmapReader()        # the galaxy map's star records around you (game memory)
        self.live = LiveMemory(self.history)
        self._reset_save_state()
        self.route_path = self.data_dir / "route.json"
        self.route_state: dict = self._load_route()
        self._live_checked = 0.0
        self.selected_system: int | None = None   # clicked in the visited-systems table
        self._planet_icons_ready = False          # names/icons of the recorded planets ensured since the last build
        self._force = asyncio.Event()
        self.describe = StateText(self)
        self.page = ConnectorPage(self)
        self.companion = PluginCompanion(self)

    def _reset_save_state(self) -> None:
        """Everything derived from the newest save, empty: at the start, and when the plugin lets go of its memory."""
        self.snapshot: dict | None = None
        self.visits: dict[int, dict] = {}
        self.timers: list[dict] = []              # settlement constructions, expeditions (timers.py)
        self.settlements: list[dict] = []         # your settlements' economy (settlements.py)
        self.ships: list[dict] = []               # your starships (ships.py)
        self.freighter: dict | None = None        # your freighter's technology (ships.freighter_from_save)
        self.equipment: equipment.Equipment | None = None   # exosuit, multi-tools, exocraft, freighter technology
        self.frigates: list[dict] = []            # your frigates (frigates.py)
        self.anchor: bytes | None = None
        self.save_system: int | None = None
        self.save_position: dict | None = None    # {system, planet, at} of the newest save (where_you_are)
        self.combat_timer: str | None = None
        self.snapshot_file: str | None = None
        self.decoded_at: str | None = None
        self.decode_seconds: float | None = None
        self.unknown_keys = 0
        self.degraded: dict[str, str] = {}        # parts of the newest save that could not be read: name -> reason
        self._book: tuple = (None, discoveries.DiscoveryBook(None))   # (the snapshot it was built for, its book)

    # ------------------------------------------------------------------ shared views of the state

    @property
    def discovery_book(self) -> discoveries.DiscoveryBook:
        """The newest snapshot's discoveries as a book; built once per snapshot (the page and the persona both ask)."""
        snap = self.snapshot
        if self._book[0] is not snap:
            self._book = (snap, discoveries.DiscoveryBook((snap or {}).get("discoveries")))
        return self._book[1]

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
        ctx = planets_view.Context(self.live, self.history, self.visits, self.gamedata, self.combat_timer,
                                   bases=snap["bases"] if snap else [], origin=self.save_system,
                                   save_position=self.save_position)
        # The planet search also knows each planet by its world type's names ("stickige" -> every airless planet).
        ctx.world_words = self.tables.worlds.biome_words() if self.tables.worlds.worlds else {}
        return ctx

    def primary_range(self) -> dict | None:
        """The primary ship's warp-range estimate (route planner default, galaxy map reach)."""
        return ships.primary_range(self.ships, self.tables.ship_ranges)

    # ------------------------------------------------------------------ lifecycle

    async def _write_codex(self) -> dict:
        """Action 'write_codex' (and the automatic write): the item and world-type documents, both languages, through
        the app's Codex channel (codex_sync). The app marks the files, keeps what you edited, keeps what you deleted
        deleted, and indexes everything in one pass - nothing to sync by hand."""
        channel = getattr(self.ctx, "codex", None)         # None: an app before 3.15.0, or the permission is missing
        if channel is None:
            return {"ok": False, "message": "This app cannot keep Codex documents for the plugin (it needs app 3.15.0 "
                                            "and the permission 'keeps its own documents in your Codex')."}
        reason = self.codex_publisher.ready(self.tables, self.gamedata)
        if reason:
            return {"ok": False, "message": f"Codex documents not written: {reason}."}
        docs = await self.ctx.run_blocking(codex_sync.generated_documents, self.tables, self.gamedata.lookup)
        try:
            counts = await channel.write(docs, owner=codex_sync.OWNER, adopt=codex_sync.ADOPT,
                                         adopt_dirs=codex_sync.legacy_folders(self.tables.terms))
        except Exception as exc:        # a refused request (CodexError) or a folder that cannot be written
            self.codex_publisher.failed(time.time())
            self.ctx.logger.warning("[NMS] Codex documents not written: %s: %s", type(exc).__name__, exc)
            return {"ok": False, "message": f"Codex documents not written: {exc}"}
        await self.ctx.run_blocking(self.codex_publisher.remember, codex_sync.stamp_of(self.install, self.ctx.version))
        self.ctx.logger.info("[NMS] Codex documents: %s", counts)
        return {"ok": True, "message": codex_sync.describe(counts)}

    async def _publish_codex(self) -> None:
        """Work-loop stage: write the generated documents when they are due (a new game build or plugin version)."""
        if getattr(self.ctx, "codex", None) is None or self.install is None:
            return
        stamp = codex_sync.stamp_of(self.install, self.ctx.version)
        if not self.codex_publisher.due(stamp, time.time()) or self.codex_publisher.ready(self.tables, self.gamedata):
            return
        result = await self._write_codex()
        if not result["ok"]:
            raise RuntimeError(result["message"])

    async def start(self) -> None:
        self.ctx.spawn(self._run(), "save-watch")
        self.ctx.spawn(self._camera_loop(), "map-camera")

    async def stop(self) -> None:
        await self.ctx.run_blocking(self._save_events)
        await self.ctx.run_blocking(self.live.close)
        self.release_memory()

    def release_memory(self) -> None:
        """Let go of everything the plugin holds in RAM: the item database and texts, the game-file tables, the save
        snapshot and its derived lists, the recorded planets and the module caches. All of it is on disk (or re-read from
        the game files) when the plugin starts again; the app unloads the plugin's modules on stop/update, and this makes
        sure nothing a task or the app still references keeps ~30-60 MB alive. Safe to call twice."""
        self.gamedata.release()
        self.tables = GameTables(TableStore(self.data_dir))
        self.gamedata.tech, self.gamedata.recipes, self.gamedata.terms = self.tables.tech, self.tables.recipes, self.tables.terms
        self._reset_save_state()
        self.history.planets.clear()
        starmap.clear_predictions()
        galaxy.clear_positions()
        self.starmap.release()
        gc.collect()

    def _load_route(self) -> dict:
        """The last route request (target, portal, range) and its result - kept across restarts."""
        data = logs.read_json(self.route_path, "The saved route")
        return data if isinstance(data, dict) else {}

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
                logs.warn_once(f"camera:{type(exc).__name__}", "Map camera sample failed (logged again in a few "
                               "minutes if it keeps failing): %s: %s", type(exc).__name__, exc)
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
        events = logs.read_json(self.events_path, "The save-write log")
        return events if isinstance(events, list) else []

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
            meta = logs.read_json(self.mapping_path.with_name("mapping_meta.json"), "The key mapping info")
            self.mapping_meta = meta if isinstance(meta, dict) else {}
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
                await self._tick()      # sets / clears self.error itself
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                self.ctx.logger.warning("[NMS] Watch cycle failed: %s", self.error)
            with contextlib.suppress(asyncio.TimeoutError):      # no action asked for a cycle: just the next poll
                await asyncio.wait_for(self._force.wait(), POLL_S)
            self._force.clear()

    async def _ensure_gamedata(self, force: bool = False) -> None:
        """Find the game and (re)build the item database when the build or language changed. The whole pass shares one
        pak session: each pak's file index is built once and freed at the end (hgpak.session)."""
        with hgpak.session():
            await self._ensure_gamedata_inner(force)
        if self._heavy_load:
            self._heavy_load = False
            gc.collect()        # the table/item passes leave cyclic garbage and a fragmented heap: collect once

    async def _ensure_gamedata_inner(self, force: bool) -> None:
        now = time.time()
        if not force and now - self._game_checked < GAME_CHECK_S:
            return
        self._game_checked = now
        self.install = await self.ctx.run_blocking(find_game)
        if self.tables.needs_load(self.install):
            self._heavy_load = True
            for warning in await self.ctx.run_blocking(self.tables.load, self.install):
                self.ctx.logger.warning("[NMS] %s", warning)
            self.gamedata.tech = self.tables.tech       # Texts.modifiers: what each technology does
            self.gamedata.recipes = self.tables.recipes     # Texts.how_to_get: an item tooltip's recipes
            self.gamedata.terms = self.tables.terms
            await self._ensure_texts()
        if self.install is None:
            # No game files (another drive, an offline library): the stored copy of the item database keeps names,
            # values and categories; the tables came from tables.json above.
            if not self.gamedata.ready and await self.ctx.run_blocking(self.gamedata.load_stored):
                self.ctx.logger.warning("[NMS] Game files not found: item database of build %s taken from the "
                                        "stored copy (%d items)", self.gamedata.build_id, len(self.gamedata.items))
                await self.ctx.run_blocking(self.gamedata.load_stored_alt_names)
            return
        if self.gamedata.matches(self.install) and not force:
            await self._ensure_alt_names()
            return
        if not force and self.gamedata.error and now - self._game_failed < GAME_RETRY_S:
            return
        await self.ctx.run_blocking(self.gamedata.load, self.install, force)
        self._heavy_load = True
        self._planet_icons_ready = False
        if self.gamedata.error:
            self._game_failed = now
            self.ctx.logger.warning("[NMS] Item names unavailable: %s", self.gamedata.error)
        else:
            self.ctx.logger.info("[NMS] Item database: %d items, %s (build %s, %s s)", len(self.gamedata.items),
                                 self.gamedata.language_label, self.gamedata.build_id, self.gamedata.build_seconds)
            await self._ensure_icons()
            await self._ensure_alt_names()

    async def _ensure_alt_names(self) -> None:
        """The item names in French, Italian, Spanish, Portuguese and Dutch (once per game build; a cache file)."""
        if self.install and self.gamedata.ready and self.gamedata.alt_build != self.install.build_id:
            await self.ctx.run_blocking(self.gamedata.load_alt_names, self.install)

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
        """One watch cycle. The stages are independent: a failing table read must not stop the save from being read,
        nor a failing save the memory scan. Each failure is logged once per few minutes (it would otherwise repeat
        every 5 s) and shown on the page; the cycle never raises (CancelledError aside)."""
        self.error = None
        failures: list[str] = []
        await self._stage("key mapping", self._ensure_mapping, failures)
        await self._stage("game files", self._ensure_gamedata, failures)
        await self._stage("codex documents", self._publish_codex, failures)
        await self._stage("save", self._tick_saves, failures)
        # After the save: the memory reader needs the save's anchor to find the player state.
        await self._stage("game memory", self._read_memory, failures)
        if failures:
            self.error = "; ".join(([self.error] if self.error else []) + failures)

    async def _stage(self, name: str, step, failures: list[str]) -> None:
        try:
            await step()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            failures.append(f"{name}: {reason}")
            logs.warn_once(f"stage:{name}:{reason}", "The %s step failed (the other steps go on): %s", name, reason)

    def _extract(self, name: str, default, fn, *args):
        """Read one optional part of a save; if it fails, the rest of the save is still used, `default` stands in
        for it, and the page says what is missing (`degraded`)."""
        try:
            value = fn(*args)
        except Exception as exc:
            self.degraded[name] = f"{type(exc).__name__}: {exc}"
            logs.warn_once(f"extract:{name}:{self.degraded[name]}", "Could not read %s from the save: %s",
                           name, self.degraded[name])
            return default
        self.degraded.pop(name, None)
        return value

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
            try:
                await self.ctx.run_blocking(self._save_events)
            except OSError as exc:      # a full disk must not stop the save from being read
                logs.warn_once("write:events", "The save-write log could not be saved: %s: %s", type(exc).__name__, exc)
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
        self.snapshot = await self.ctx.run_blocking(summarize, readable)       # essential: a failure ends this read
        self.visits = await self.ctx.run_blocking(self._extract, "visited systems", {}, visits_from_save, readable)
        self.settlements = self._extract("settlements", [], settlements.settlements_from_save, readable)
        self.timers = self._extract("timers", [], lambda: sorted(
            timers.timers_from_save(readable, self.tables.timer_durations)
            + settlements.decision_timers(self.settlements, self.tables.settlement_rules), key=lambda t: t["ends_at"]))
        self.ships = self._extract("ships", [], ships.ships_from_save, readable)
        self.freighter = self._extract("the freighter", None, ships.freighter_from_save, readable)
        self.equipment = self._extract("equipment", None, equipment.Equipment.from_save, readable)
        self.frigates = self._extract("frigates", [], frigates.frigates_from_save, readable)
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
        with hgpak.session():           # icons and texts of a new save may need two paks: open each once
            await self._ensure_icons()
            await self._ensure_texts()

    # ------------------------------------------------------------------ UI

    @cached_property
    def _actions(self) -> dict:
        """action id -> async handler(params); one small method per action instead of one long if-chain."""
        return {
            planets_view.PLAN_ROUTE: self._act_plan_route,
            planets_view.OPEN_SYSTEM: self._act_open_system,
            planets_view.GALAXY_COLORS: self._act_galaxy_colors,
            planets_view.SEARCH_PLANETS: self._act_search_planets,
            planets_view.NAME_FIX: self._act_name_fix,
            "rescan": self._act_rescan,
            "update_mapping": self._act_update_mapping,
            "write_codex": lambda params: self._write_codex(),
            "rebuild_names": self._act_rebuild_names,
            "scan_memory": self._act_scan_memory,
            "clear_history": self._act_clear_history,
            SAVE_SETTINGS: self._act_save_settings,
            SET_SETTING: self._act_set_setting,
        }

    async def action(self, action_id: str, params: dict) -> dict:
        """Run one of the page's actions (buttons, forms, row clicks); params are untrusted input."""
        handler = self._actions.get(action_id)
        if handler is None:
            raise ValueError(f"unknown action {action_id}")
        return await handler(params or {})

    async def _act_plan_route(self, params: dict) -> dict:
        return await self.ctx.run_blocking(self._plan_route, params)

    async def _act_name_fix(self, params: dict) -> dict:
        return await self.ctx.run_blocking(self._name_fix, params)

    async def _act_open_system(self, params: dict) -> dict:
        key = planets_view.parse_system_key(params.get("key"))
        if key is None:
            return {"ok": False, "message": "Unknown system."}
        self.selected_system = key
        return {"ok": True, "focus": planets_view.SYSTEM_MAP_ID}

    async def _act_galaxy_colors(self, params: dict) -> dict:
        mode = str(params.get("color_by") or "")
        if mode not in planets_view.COLOR_MODES:
            return {"ok": False, "message": "Unknown colouring."}
        self.galaxy_colors = mode
        return {"ok": True, "focus": planets_view.GALAXY_MAP_ID}

    async def _act_search_planets(self, params: dict) -> dict:
        # Untrusted form value: a string, cut to the field's length.
        self.planet_query = str(params.get("query") or "").strip()[:planet_search.MAX_QUERY_CHARS]
        if not self.planet_query:
            return {"ok": True, "message": "Planet search cleared."}
        found = len(planets_view.planet_index(self.context()).search(self.planet_query))
        return {"ok": True, "focus": planets_view.PLANET_SEARCH_ID,
                "message": f"{found} planet(s) match \"{self.planet_query}\"."}

    async def _act_rescan(self, params: dict) -> dict:
        self._read_save_again()
        return {"ok": True, "message": "Reading the newest save again."}

    async def _act_update_mapping(self, params: dict) -> dict:
        await self._ensure_mapping(force=True)
        if self.mapping_error:
            return {"ok": False, "message": f"Download failed: {self.mapping_error}"}
        self._read_save_again()
        return {"ok": True, "message": f"Key mapping {self.mapping_meta.get('tag')} downloaded."}

    def _read_save_again(self) -> None:
        """Forget the decoded snapshot and wake the work loop: the newest save is read at once."""
        self.snapshot = None
        self._force.set()

    async def _act_rebuild_names(self, params: dict) -> dict:
        await self._ensure_gamedata(force=True)
        if self.install is None:
            return {"ok": False, "message": "No Man's Sky installation not found (set NMS_GAME_DIR)."}
        if self.gamedata.error:
            return {"ok": False, "message": f"Reading the game files failed: {self.gamedata.error}"}
        return {"ok": True, "message": f"{len(self.gamedata.items):,} item names read from the game "
                                       f"({self.gamedata.language_label})."}

    async def _act_scan_memory(self, params: dict) -> dict:
        await self._read_memory(force=True)
        if self.live.status != "ok":
            return {"ok": False, "message": self.live.error or "No Man's Sky is not running."}
        return {"ok": True, "message": f"Read {self.live.last_scan_planets} planet(s) from the game in "
                                       f"{self.live.last_scan_seconds} s."}

    async def _act_clear_history(self, params: dict) -> dict:
        self.watcher.events.clear()
        await self.ctx.run_blocking(self._save_events)
        return {"ok": True, "message": "Save history cleared."}

    async def _act_save_settings(self, params: dict) -> dict:
        problem = self.settings.update(params)
        if problem:
            return {"ok": False, "message": problem}
        await self.ctx.run_blocking(self.settings.save, self.settings_path)
        return {"ok": True, "message": f"Settings saved: codeword \"{self.settings.codeword}\", single context per "
                                       f"question {_on_off(self.settings.single_context)}."}

    async def _act_set_setting(self, params: dict) -> dict:
        problem = self.settings.set_switch(params)
        if problem:
            return {"ok": False, "message": problem}
        await self.ctx.run_blocking(self.settings.save, self.settings_path)
        return {"ok": True, "message": f"Single context per question {_on_off(self.settings.single_context)}."}

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

    def overlay(self) -> dict:
        """What the app's desktop overlay shows in this plugin's mode (see companion.py; app 3.11.0)."""
        return self.companion.overlay()
