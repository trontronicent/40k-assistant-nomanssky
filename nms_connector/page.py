"""The plugin's page: the declarative view (no JavaScript) the app renders, built from the connector's state.

``ConnectorPage.view()`` returns ``{title, subtitle, updated_at, actions, sections}``: notices about what is
missing (saves, key mapping, game files), then one ``tabs`` section - Overview / Systems / Inventory / Ships & bases /
Settlements / Saves & source. The system, planet and route sections come from ``planets_view``; ships, equipment,
frigates, settlements and timers from their own modules. Item cells carry the game's icon and a tooltip
(``planets_view.Texts.item``: category, description in English and the game's language, what a technology does,
where a trade good sells). The page reads the state on every call (every 5 s poll) and keeps none of its own.
"""

from __future__ import annotations

import time

from . import equipment, frigates, planets_view, settlements, ships, timers


def fmt_int(value) -> str:
    return f"{value:,}" if isinstance(value, int) else "–"


def fmt_duration(seconds) -> str:
    """'45 s', '12 min 05 s', '3 h 07 min'; '–' when unknown."""
    if not isinstance(seconds, (int, float)):
        return "–"
    seconds = int(seconds)
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{seconds // 60} min {seconds % 60:02d} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


ACTIONS = [
    {"id": "rescan", "label": "Rescan", "description": "Read the newest save file again now."},
    {"id": "update_mapping", "label": "Update key mapping",
     "description": "Download the newest mapping.json from MBINCompiler (needed after game updates)."},
    {"id": "scan_memory", "label": "Scan game now",
     "description": "Read the planets of the current system from the running game now (read-only, ~10 s)."},
    {"id": "rebuild_names", "label": "Re-read item names",
     "description": "Read item names and icons from the game files again (done automatically after a game update)."},
    {"id": "clear_history", "label": "Clear save history", "description": "Forget the recorded save writes.",
     "confirm": "Clear the recorded save history?"},
]


class ConnectorPage:
    """Builds the view of one connector (its state is read on every call)."""

    def __init__(self, connector):
        self.connector = connector

    # ------------------------------------------------------------------ items

    def item_columns(self) -> list[str]:
        gamedata = self.connector.gamedata
        if gamedata.ready and gamedata.language != "english":
            return ["Name (English)", f"Name ({gamedata.language_label})", "Category", "Item id", "Amount", "Max"]
        return ["Name", "Category", "Item id", "Amount", "Max"]

    def item_rows(self, rows: list[list], ctx) -> list[list]:
        """[id, amount, max] -> [{text, icon, hint}, (local name,) category, id, amount, max]: the game's names,
        icon and category; the tooltip holds the description and, for trade goods, where they sell."""
        gamedata = self.connector.gamedata
        bilingual = gamedata.ready and gamedata.language != "english"
        out = []
        for item_id, amount, maximum in rows:
            entry = gamedata.lookup(item_id) or {}
            name = ctx.texts.item(item_id, entry.get("en") or item_id)
            category = ctx.texts.category(item_id)
            out.append([name, entry.get("local"), category, item_id, amount, maximum] if bilingual
                       else [name, category, item_id, amount, maximum])
        return out

    def storage_tab(self, snap: dict, ctx, columns: list[str]) -> dict:
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
                             "rows": self.item_rows(chest["rows"], ctx)})
        if empty:
            sections.append({"type": "text", "text": f"Empty storage containers: {', '.join(empty)}."})
        if not sections:
            sections.append({"type": "text", "text": "No storage container in this save holds anything."})
        return {"id": "storage", "label": "Storage", "badge": sum(1 for c in snap.get("storage") or [] if c["rows"]) or None,
                "sections": sections}

    # ------------------------------------------------------------------ tabs

    def overview(self, snap: dict | None, ctx) -> list[dict]:
        """The Overview tab: timers, status, where you are, the location at the last save, fleet and companions."""
        c = self.connector
        out: list[dict] = []
        where = planets_view.where_you_are(ctx)
        if not snap:
            out.append({"type": "text", "text": "No save has been read yet: status, location and inventories appear "
                                                "once the connector has read a save file."})
            return out + ([where] if where else [])
        loc = snap["location"]
        out.append(timers.timers_section(c.timers, getattr(c.ctx, "section_types", ()), time.time()))
        out.append({"type": "stats", "title": "Status", "items": [
            {"label": "Units", "value": fmt_int(snap["units"])},
            {"label": "Nanites", "value": fmt_int(snap["nanites"])},
            {"label": "Quicksilver", "value": fmt_int(snap["quicksilver"])},
            {"label": "Health", "value": snap["health"]},
            {"label": "Shield", "value": snap["shield"]},
            {"label": "Ship health", "value": snap["ship_health"]},
            {"label": "Play time", "value": fmt_duration(snap["play_time_s"])},
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
        text = c.describe
        out.append({"type": "kv", "title": "Fleet and companions", "items": [
            {"label": "Primary ship", "value": text.primary_ship()},
            {"label": "Settlements", "value": text.settlements()},
            {"label": "Ships", "value": len(snap["ships"])},
            {"label": "Frigates", "value": snap["frigates"]},
            {"label": "Frigate expeditions", "value": snap["expeditions"]},
            {"label": "Companions (pets)", "value": snap["pets"]},
            {"label": "Freighter", "value": text.freighter(snap["freighter"]["name"])},
            {"label": "Current mission", "value": text.mission(snap["current_mission"])},
            {"label": "Difficulty", "value": snap["difficulty"]},
        ]})
        return out

    def inventories(self, snap: dict | None, ctx) -> list[dict]:
        """The Inventory tab: exosuit, primary starship, freighter, storage containers and equipment."""
        if not snap:
            return [{"type": "text", "text": "Inventories appear once a save has been read."}]
        columns = self.item_columns()
        hint = {"type": "text", "text": "Hover an item's name for its description; trade goods also tell where they "
                                        "sell and whether you know such a system."}
        tabs = [{"id": "exosuit", "label": "Exosuit", "sections": [hint,
            {"type": "table", "title": "Exosuit inventory", "columns": columns,
             "rows": self.item_rows(snap["exosuit"] + snap["exosuit_cargo"], ctx), "empty": "Empty"}]}]
        primary = next((s for s in snap["ships"] if s["primary"]), None)
        if primary:
            tabs.append({"id": "starship", "label": f"Starship: {primary['name']}", "sections": [
                {"type": "table", "title": f"Starship inventory: {primary['name']}", "columns": columns,
                 "rows": self.item_rows(primary["inventory"], ctx), "empty": "Empty"}]})
        tabs.append({"id": "freighter", "label": "Freighter", "sections": [
            {"type": "table", "title": "Freighter inventory", "columns": columns,
             "rows": self.item_rows(snap["freighter"]["inventory"], ctx), "empty": "Empty"}]})
        tabs.append(self.storage_tab(snap, ctx, columns))
        tabs.append({"id": "equipment", "label": "Equipment",
                     "sections": equipment.equipment_sections(self.connector.equipment, ctx.texts)})
        return [{"type": "tabs", "id": "inventory-tabs", "tabs": tabs}]

    def fleet(self, snap: dict | None, ctx) -> list[dict]:
        """The Ships & bases tab: ships with their technology, frigates and bases."""
        c = self.connector
        if not snap:
            return [{"type": "text", "text": "Ships and bases appear once a save has been read."}]

        def system_label(key):
            visit = ctx.visit(key)
            return planets_view._system_label(key, visit) if visit else None

        return ships.ship_sections(c.ships, c.tables.ship_ranges, ctx.texts) + frigates.frigate_sections(
            c.frigates, c.tables.trait_names, ctx.texts, system_label) + [
            {"type": "table", "title": "Bases", "columns": ["Name", "Type", "Galaxy", "Portal address", "Parts"],
             "rows": [[b["name"], b["type"], b["galaxy"], b["portal"], b["objects"]] for b in snap["bases"]]},
        ]

    def saves(self, snap: dict | None, ctx) -> list[dict]:
        """The Saves & source tab: how often the game saves, recent writes, where the data comes from, scans."""
        c = self.connector
        sections: list[dict] = []
        stats = c.watcher.stats()
        sections.append({"type": "kv", "title": "How often the game saves (measured)", "items": [
            {"label": "Save writes recorded", "value": stats["writes"]},
            {"label": "Typical interval while playing", "value": fmt_duration(stats["median_interval_s"])},
            {"label": "Shortest / longest", "value": f"{fmt_duration(stats['shortest_interval_s'])} / {fmt_duration(stats['longest_interval_s'])}"},
        ]})
        sections.append({"type": "table", "title": "Recent save writes", "columns": ["Time", "File", "Slot", "Size (kB)", "Since previous"],
                         "rows": [[e["at"], e["file"], e["slot"], round(e["size"] / 1024), fmt_duration(e["since_previous_s"])]
                                  for e in reversed(c.watcher.events[-50:])],
                         "empty": "No save written since the connector started. Play and save (or let the game autosave)."})
        source = [
            {"label": "Save folder", "value": str(c.save_dir) if c.save_dir else "not found"},
            {"label": "Read from", "value": c.snapshot_file or "–"},
            {"label": "Read at", "value": c.decoded_at or "–"},
            {"label": "Decode time", "value": f"{c.decode_seconds} s" if c.decode_seconds is not None else "–"},
            {"label": "Key mapping", "value": f"{c.mapping_meta.get('tag', '?')} ({len(c.mapping)} keys)" if c.mapping else "–"},
        ]
        if c.install:
            game = f"{c.install.root} (build {c.install.build_id})" if c.install.build_id else str(c.install.root)
            source.append({"label": "Game folder", "value": game})
        if c.gamedata.ready:
            source.append({"label": "Item names", "value":
                           f"{len(c.gamedata.items):,} items in English and {c.gamedata.language_label}, "
                           f"read from the game files {c.gamedata.built_at or ''}".strip()})
        if c.tables.tech.ready:
            source.append({"label": "Technology stats", "value":
                           f"{len(c.tables.tech.fixed):,} technologies and {len(c.tables.tech.procedural):,} upgrade "
                           "modules, read from the game files"})
        live = {"ok": "reading NMS.exe" + (f" - last scan {c.live.last_scan_iso}, {c.live.last_scan_seconds} s, "
                                           f"{c.live.last_scan_bytes / 2**30:.1f} GB, {c.live.last_scan_planets} planet(s)"
                                           if c.live.last_scan_iso else ""),
                "not-running": "the game is not running", "idle": "waiting"}.get(c.live.status, c.live.error)
        source.append({"label": "Game memory (read-only)", "value": live})
        source.append({"label": "Planets recorded", "value":
                       f"{len(c.history.planets)} in {len(c.history.systems())} system(s), "
                       f"kept in {c.history.path} (previous version: .json.bak)"})
        if c.gamedata.icon_error:
            source.append({"label": "Last icon problem", "value": c.gamedata.icon_error})
        if snap:
            source.append({"label": "Save format version", "value": snap["save_version"]})
        sections.append({"type": "kv", "title": "Source", "items": source})
        sections.append(planets_view.scan_log_section(ctx, c.history.scans))
        return sections

    def settings_sections(self) -> list[dict]:
        """The Settings tab: the persona's codeword and Single Context Per Question (settings.py)."""
        s = self.connector.settings
        return [{"type": "form", "id": "plugin-settings", "title": "Plugin persona", "action": "save_settings",
                 "submit_label": "Save",
                 "description": "How the No Man's Sky Plugin Persona is addressed and how much of the conversation it "
                                "keeps. In the app's desktop overlay, switched to No Man's Sky (right-click -> Show), "
                                "the Codeword and Live call buttons start talking to it by voice.",
                 "fields": [
                     {"id": "codeword", "label": "Codeword", "type": "text", "max_length": 40, "value": s.codeword,
                      "placeholder": "e.g. Atlas",
                      "hint": "The word that starts a spoken question to the persona in Live Comms' Codeword mode, "
                              "e.g. \"Atlas, how much copper do I have?\". The overlay's Codeword button sets it in "
                              "the app. Choose a word you rarely say otherwise."},
                     {"id": "single_context", "label": "Single Context Per Question", "type": "checkbox",
                      "value": s.single_context, "hint": "Helps saving VRAM"}]},
                {"type": "text", "text": "Single Context Per Question: the persona answers each question on its own, "
                                         "without the earlier turns of the conversation. Its game data is fresh with "
                                         "every question, so little is lost, and the model needs less video memory "
                                         "while the game runs (needs the 40k Assistant 3.11.0)."}]

    def notices(self) -> list[dict]:
        """What is missing or wrong, above the tabs."""
        c = self.connector
        out: list[dict] = []
        if c.save_dir is None:
            out.append({"type": "notice", "level": "warn", "text":
                        "No No Man's Sky saves found. Expected under %APPDATA%\\HelloGames\\NMS (Windows) "
                        "or the Steam Proton folder (Linux); set NMS_SAVE_DIR to override."})
        if c.mapping is None:
            out.append({"type": "notice", "level": "warn" if c.mapping_error else "info", "text":
                        f"Key mapping not available yet ({c.mapping_error})." if c.mapping_error
                        else "Downloading the key mapping (mapping.json) from MBINCompiler…"})
        if c.unknown_keys:
            out.append({"type": "notice", "level": "warn", "text":
                        f"{c.unknown_keys} save keys are unknown to the current mapping (probably a game "
                        "update). Press 'Update key mapping'."})
        if c.error:
            out.append({"type": "notice", "level": "error", "text": c.error})
        if c.install is None and c.game_checked:
            out.append({"type": "notice", "level": "info", "text":
                        "Item names and icons come from the game's own files, but the No Man's Sky installation "
                        "was not found in any Steam library. Set NMS_GAME_DIR to the game folder to use another one."})
        elif c.gamedata.error:
            out.append({"type": "notice", "level": "warn", "text":
                        f"Item names and icons are unavailable: {c.gamedata.error}"})
        return out

    def view(self) -> dict:
        """The whole page: notices, then the main tabs, with the page's buttons (ACTIONS)."""
        c = self.connector
        snap = c.snapshot
        ctx = c.context()
        sections = self.notices()
        sections.append({"type": "tabs", "id": "main", "tabs": [
            {"id": "overview", "label": "Overview", "sections": self.overview(snap, ctx)},
            {"id": "systems", "label": "Systems", "badge": len(ctx.keys()) or None,
             "sections": [planets_view.systems_tabs(ctx, c.selected_system, c.route_state, c.primary_range(),
                                                    c.galaxy_colors, c.planet_query)]},
            {"id": "inventory", "label": "Inventory", "sections": self.inventories(snap, ctx)},
            {"id": "fleet", "label": "Ships & bases", "sections": self.fleet(snap, ctx)},
            {"id": "settlements", "label": "Settlements", "badge": len(c.settlements) or None,
             "sections": settlements.settlement_sections(c.settlements, c.tables.settlement_rules,
                                                         ctx.texts, time.time(), c.settlement_live.values)},
            {"id": "saves", "label": "Saves & source", "sections": self.saves(snap, ctx)},
            {"id": "settings", "label": "Settings", "sections": self.settings_sections()},
        ]})
        return {
            "title": "No Man's Sky",
            "subtitle": "Read from your save files (updates whenever the game saves) and, while it runs, from the game.",
            "updated_at": c.decoded_at,
            "actions": ACTIONS,
            "sections": sections,
        }
