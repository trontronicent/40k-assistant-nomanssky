"""View sections for the current system, visited systems and planets, and system maps (pure)."""

from __future__ import annotations

from .summary import address_portal, galaxy_name, unpack_address

# GcPlanetInfo.SentinelsPerDifficulty is indexed by the ground combat timer setting.
COMBAT_TIMERS = {"Off": 0, "Slow": 1, "Normal": 2, "Fast": 3}

# What an atmosphere harvester collects, by the planet's biome (the game decides by biome; the
# planet record has no gas field). Sulphurine on hot, barren and volcanic worlds, radon on
# irradiated and frozen ones, nitrogen on lush and toxic ones, oxygen on exotic ones. Dead worlds
# have no atmosphere; water worlds, gas giants and test biomes are left out rather than guessed.
GAS_BY_BIOME = {"Lush": "GAS3", "Swamp": "GAS3", "Toxic": "GAS3",
                "Scorched": "GAS1", "Barren": "GAS1", "Lava": "GAS1",
                "Radioactive": "GAS2", "Frozen": "GAS2",
                "Exotic": "OXYGEN", "Exotic (red)": "OXYGEN", "Exotic (green)": "OXYGEN", "Exotic (blue)": "OXYGEN"}

# Colours of the system map (by biome) and relative planet sizes (by the generator's size class).
BIOME_COLORS = {"Lush": "#5fbf6a", "Swamp": "#4f8f5a", "Toxic": "#b5c93a", "Scorched": "#e07a3a", "Lava": "#ff5a2a",
                "Radioactive": "#9be04a", "Frozen": "#a8d8ff", "Barren": "#c2a77a", "Dead": "#8a8a8a",
                "Exotic": "#d36bd8", "Exotic (red)": "#e0505a", "Exotic (green)": "#4fe0a0", "Exotic (blue)": "#5a7cff",
                "Waterworld": "#3a7fd6", "Gas giant": "#d8b07a"}
SIZE_SCALE = {"Giant": 2.2, "Large": 1.5, "Medium": 1.15, "Small": 0.9, "Moon": 0.6}
STAR_COLOR = "#ffd27a"
PURPLE_STAR = "#b77cff"

# System indices with a fixed meaning in every region (community findings, stable across updates):
# 0x79 holds the region's black hole, 0x7A an Atlas interface; purple stars (Worlds Part II) use 0x3E8-0x429.
BLACK_HOLE_SYSTEM = 0x79
ATLAS_SYSTEM = 0x7A
PURPLE_SYSTEMS = range(0x3E8, 0x42A)

PLANET_COLUMNS = ["Planet", "Type", "Weather", "Resource 1", "Resource 2", "Resource 3", "Plants", "Gas", "Flora",
                  "Fauna", "Sentinels"]
OPEN_SYSTEM = "open_system"
SYSTEM_MAP_ID = "system-map"
CURRENT_MAP_ID = "current-map"


def planet_gas(planet: dict) -> str | None:
    """The gas an atmosphere harvester collects on this planet (item id), when its biome tells."""
    return GAS_BY_BIOME.get(planet.get("biome") or "")


def info_keys(planets) -> set[str]:
    """Every localisation key in the planets' summaries (to resolve them in one pass)."""
    keys: set[str] = set()
    for p in planets:
        info = p.get("info") or {}
        for key, value in info.items():
            keys.update(v for v in (value if isinstance(value, list) else [value]) if v)
    return keys


def resource_ids(planets) -> list[str]:
    ids: list[str] = []
    for p in planets:
        ids += [p.get("common"), p.get("uncommon"), p.get("rare"), planet_gas(p)] + list(p.get("extra") or [])
    return list(dict.fromkeys(i for i in ids if i))


def system_key_text(key: int) -> str:
    """A system key as the row key / action parameter (hex, no prefix)."""
    return f"{key:x}"


def parse_system_key(text) -> int | None:
    try:
        return int(str(text), 16)
    except (TypeError, ValueError):
        return None


class Texts:
    """Turns ids and localisation keys into 'English (game language)' strings."""

    def __init__(self, gamedata):
        self.gamedata = gamedata

    @staticmethod
    def both(en, local) -> str | None:
        if not en:
            return local or None
        return en if not local or local == en else f"{en} ({local})"

    def key(self, key: str | None) -> str | None:
        """A localisation key -> text; strings that are not keys (already translated) pass through."""
        if not key:
            return None
        entry = self.gamedata.text(key)
        return self.both(entry["en"], entry["local"]) if entry else key

    def description(self, info: dict) -> str | None:
        desc, kind = self.gamedata.text(info.get("description")), self.gamedata.text(info.get("type"))
        if not desc:
            return self.key(info.get("description"))
        kind = kind or {"en": "Planet", "local": "Planet"}
        return self.both(desc["en"].replace("%PLANETCLASS%", kind["en"]),
                         desc["local"].replace("%PLANETCLASS%", kind["local"]))

    def name(self, item_id: str | None) -> str | None:
        if not item_id:
            return None
        entry = self.gamedata.lookup(item_id) or {}
        return self.both(entry.get("en"), entry.get("local")) or item_id

    def item(self, item_id: str | None):
        """A resource id -> table cell with the game's icon and name (id when unknown)."""
        if not item_id:
            return None
        label = self.name(item_id)
        icon = self.gamedata.icon_name(item_id)
        return {"text": label, "icon": icon} if icon else label

    def items(self, ids) -> str | None:
        names = [(self.gamedata.lookup(i) or {}).get("en") or i for i in ids or []]
        return ", ".join(names) or None


def _system_label(key: int, visit: dict | None) -> str:
    name = (visit or {}).get("name")
    return name or f"System {address_portal(unpack_address(key) or {}) or hex(key)}"


def _planet_name(planet: dict, visit: dict | None) -> str:
    saved = (((visit or {}).get("planets") or {}).get(planet.get("index")) or {}).get("name")
    name = planet.get("name") or "?"
    return f"{saved} ({name})" if saved and saved != name else name


def _sentinel(planet: dict, sentinel_index: int):
    sentinels = (planet.get("info") or {}).get("sentinels") or []
    return sentinels[sentinel_index] if 0 <= sentinel_index < len(sentinels) else None


def _planet_row(texts: Texts, planet: dict, visit: dict | None, sentinel_index: int, system_cell=None) -> list:
    info = planet.get("info") or {}
    row = [] if system_cell is None else [system_cell]
    row += [_planet_name(planet, visit), texts.description(info) or planet.get("biome"), texts.key(info.get("weather")),
            texts.item(planet.get("common")), texts.item(planet.get("uncommon")), texts.item(planet.get("rare")),
            texts.items(planet.get("extra")), texts.item(planet_gas(planet)), texts.key(info.get("flora")),
            texts.key(info.get("fauna")), texts.key(_sentinel(planet, sentinel_index))]
    return row


class Context:
    """Everything the system and planet sections are built from."""

    def __init__(self, live, history, visits: dict, gamedata, combat_timer: str | None, bases=None):
        self.live, self.history, self.visits = live, history, visits
        self.texts = Texts(gamedata)
        self.sentinel_index = COMBAT_TIMERS.get(combat_timer or "Normal", 2)
        self.recorded = history.systems()
        self.bases = bases or []

    def keys(self) -> set[int]:
        return set(self.visits) | set(self.recorded)

    def current_planet_index(self) -> int | None:
        """Index of the planet you are on (0-based), None in space or when unknown."""
        on = ((self.live.current or {}).get("GalacticAddress") or {}).get("PlanetIndex", 0)
        return on - 1 if on else None


def live_notices(live) -> list[dict]:
    if live.status == "not-running":
        return [{"type": "notice", "level": "info", "text":
                 "Start No Man's Sky to read live data: the planets of the system you are in (resources, weather, "
                 "sentinels) are then read from the game's memory, read-only, and remembered."}]
    if live.status in ("error", "unsupported"):
        return [{"type": "notice", "level": "warn", "text": f"Live data unavailable: {live.error}"}]
    return []


def where_you_are(ctx: Context) -> dict | None:
    key = ctx.live.current_system
    if key is None:
        return None
    visit = ctx.visits.get(key)
    addr = unpack_address(key) or {}
    index = ctx.current_planet_index()
    here = next((p for p in ctx.recorded.get(key, []) if p.get("index") == index), None) if index is not None else None
    exact = getattr(ctx.live, "current_source", "player") == "player"
    if here:
        planet = _planet_name(here, visit)
    elif not exact:
        planet = "unknown (your exact position cannot be read right now)"
    else:
        planet = "in space" if index is None else f"planet {index + 1}"
    return {"type": "kv", "title": "Where you are now", "items": [
        {"label": "System", "value": _system_label(key, visit)},
        {"label": "Portal address", "value": address_portal(addr)},
        {"label": "Galaxy", "value": galaxy_name(addr.get("RealityIndex"))},
        {"label": "Planet", "value": planet},
        {"label": "Found by", "value": "your position in the game's memory" if exact else
         "the planets the game holds in memory (the exact position is only readable around saves and loads)"},
    ]}


def _star(key: int, visit: dict, planets: list[dict], ctx: Context) -> dict:
    addr = unpack_address(key) or {}
    index = addr.get("SolarSystemIndex")
    color, special = STAR_COLOR, None
    if index == BLACK_HOLE_SYSTEM:
        special = "the region's black hole system"
    elif index == ATLAS_SYSTEM:
        special = "an Atlas interface system"
    elif index in PURPLE_SYSTEMS:
        color, special = PURPLE_STAR, "purple star"
    known = {p.get("index") for p in planets} | set((visit.get("planets") or {}))
    last = max((p.get("last_seen") or "" for p in planets), default="") or None
    bases = [b["name"] for b in ctx.bases if b.get("system") == key]
    items = [
        {"label": "Portal address", "value": address_portal(addr)},
        {"label": "Galaxy", "value": galaxy_name(addr.get("RealityIndex"))},
        {"label": "Region (voxel X, Y, Z)", "value": f"{addr.get('VoxelX')}, {addr.get('VoxelY')}, {addr.get('VoxelZ')}"},
        {"label": "System index", "value": f"{index} (0x{index:03X})" if isinstance(index, int) else None},
        {"label": "Planets known", "value": f"{len(known)} ({len(planets)} with resources)" if known else "none yet"},
        {"label": "Named by", "value": visit.get("named_by")},
        {"label": "Discovered", "value": visit.get("discovered_at")},
        {"label": "Resources last read", "value": last},
        {"label": "Your bases here", "value": ", ".join(bases) or "none"},
    ]
    if special:
        items.insert(4, {"label": "Special", "value": special})
    if key == ctx.live.current_system:
        items.insert(0, {"label": "You are", "value": "in this system now"})
    sublabel = "Star system" + (f" · {special}" if special else "")
    return {"label": _system_label(key, visit), "sublabel": sublabel, "color": color, "size": 1, "items": items}


def _body(planet: dict | None, index: int, saved: dict, visit: dict, ctx: Context, here: bool) -> dict:
    texts = ctx.texts
    planet = planet or {}
    info = planet.get("info") or {}
    biome = planet.get("biome")
    if planet:
        label = _planet_name(planet, visit)
    else:
        label = saved.get("name") or f"Planet {index + 1}"
    sublabel = " · ".join(v for v in (biome, planet.get("size")) if v) or "not scanned yet"
    gas = planet_gas(planet)
    items = []
    if here:
        items.append({"label": "You are", "value": "on this planet now"})
    if planet:
        weather = texts.key(info.get("weather"))
        items += [
            {"label": "Type", "value": texts.description(info) or biome},
            {"label": "Weather", "value": f"{weather} (extreme)" if weather and planet.get("extreme_weather") else weather},
            {"label": "Resources", "value": ", ".join(n for n in (texts.name(planet.get(k)) for k in ("common", "uncommon", "rare")) if n)},
            {"label": "Plants", "value": texts.items(planet.get("extra"))},
            {"label": "Gas (atmosphere harvester)", "value": texts.name(gas) or ("none" if biome == "Dead" else "unknown")},
            {"label": "Flora", "value": texts.key(info.get("flora"))},
            {"label": "Fauna", "value": texts.key(info.get("fauna")) + (" (special fauna)" if planet.get("special_fauna") else "")
             if info.get("fauna") else None},
            {"label": "Sentinels", "value": texts.key(_sentinel(planet, ctx.sentinel_index))},
            {"label": "Resources last read", "value": planet.get("last_seen")},
        ]
    else:
        items.append({"label": "Resources", "value": "not read yet - visit this planet's system while the game runs"})
    counts = ", ".join(f"{saved[k]} {k}" for k in ("flora", "fauna", "minerals") if saved.get(k))
    if counts:
        items.append({"label": "Your discoveries", "value": counts})
    if saved.get("name"):
        items.append({"label": "Uploaded name", "value": f"{saved['name']}" + (f" by {saved['named_by']}" if saved.get("named_by") else "")})
    badges = [texts.item(planet.get(k)) for k in ("common", "uncommon", "rare")] + \
             [texts.item(i) for i in planet.get("extra") or []] + [texts.item(gas)]
    body = {"label": label, "sublabel": sublabel, "size": SIZE_SCALE.get(planet.get("size"), 1),
            "items": items, "badges": [b for b in badges if b]}
    if biome in BIOME_COLORS:
        body["color"] = BIOME_COLORS[biome]
    if biome == "Gas giant" or planet.get("size") == "Giant":
        body["ring"] = True
    return body


def system_map(key: int, ctx: Context, section_id: str, title_prefix: str) -> dict:
    """An orbit section: the star with what is known about the system, and every known planet."""
    visit = ctx.visits.get(key) or {}
    planets = ctx.recorded.get(key, [])
    by_index = {p.get("index"): p for p in planets}
    saved = visit.get("planets") or {}
    here = ctx.current_planet_index() if key == ctx.live.current_system else None
    bodies = [_body(by_index.get(i), i, saved.get(i) or {}, visit, ctx, i == here)
              for i in sorted(set(by_index) | set(saved), key=lambda i: (i is None, i))]
    return {"type": "orbit", "id": section_id, "title": f"{title_prefix}: {_system_label(key, visit)}",
            "center": _star(key, visit, planets, ctx), "bodies": bodies,
            "empty": "No planet of this system is known yet: resources are read while you are in the system with "
                     "the game running, names come from your discoveries."}


def current_system_sections(ctx: Context) -> list[dict]:
    key = ctx.live.current_system
    if key is None:
        return [{"type": "text", "text": "Not in a known system right now: live data appears while No Man's Sky runs."}]
    visit = ctx.visits.get(key)
    planets = ctx.recorded.get(key, [])
    return [
        system_map(key, ctx, CURRENT_MAP_ID, "Current system"),
        {"type": "table", "title": f"Planets of {_system_label(key, visit)} (live from the game)", "columns": PLANET_COLUMNS,
         "rows": [_planet_row(ctx.texts, p, visit, ctx.sentinel_index) for p in planets],
         "empty": "No planet of this system has been generated yet - fly closer, the next scan picks it up."},
    ]


def _shown_system(ctx: Context, selected: int | None) -> int | None:
    """The system the map of the visited-systems tab shows: the clicked one, else where you are, else the newest."""
    keys = ctx.keys()
    if selected in keys:
        return selected
    if ctx.live.current_system in keys:
        return ctx.live.current_system
    newest = max(keys, key=lambda k: _last_seen(k, ctx), default=None)
    return newest


def _last_seen(key: int, ctx: Context) -> str:
    planets = ctx.recorded.get(key, [])
    last = max((p.get("last_seen") or "" for p in planets), default="")
    return last or (ctx.visits.get(key) or {}).get("discovered_at") or ""


def visited_systems_sections(ctx: Context, selected: int | None) -> list[dict]:
    entries = []
    for key in ctx.keys():
        visit = ctx.visits.get(key) or {}
        addr = unpack_address(key) or {}
        planets = ctx.recorded.get(key, [])
        named = sum(1 for p in (visit.get("planets") or {}).values() if p.get("name"))
        row = [_system_label(key, visit), address_portal(addr), galaxy_name(addr.get("RealityIndex")),
               len(planets) or None, named or None, visit.get("named_by"), _last_seen(key, ctx) or None,
               "yes" if key == ctx.live.current_system else ""]
        entries.append((row, key))
    # Current system first, then systems with recorded resources, each newest first (sorts are stable).
    entries.sort(key=lambda e: e[0][6] or "", reverse=True)
    entries.sort(key=lambda e: (e[0][7] != "yes", e[0][3] is None))
    shown = _shown_system(ctx, selected)
    out = []
    if shown is not None:
        out.append(system_map(shown, ctx, SYSTEM_MAP_ID, "System map"))
    out.append({"type": "table", "title": f"Visited systems ({len(entries)})",
                "columns": ["System", "Portal address", "Galaxy", "Planets with resources", "Named planets",
                            "Named by", "Last seen / discovered", "Here"],
                "rows": [row for row, _ in entries], "row_action": OPEN_SYSTEM,
                "row_keys": [system_key_text(key) for _, key in entries],
                "selected_key": system_key_text(shown) if shown is not None else None,
                "row_hint": "Click a system to show its star and planets in the map above.",
                "empty": "No visited systems in the save yet."})
    return out


def visited_planets_section(ctx: Context) -> dict:
    planet_rows = []
    for key, planets in ctx.recorded.items():
        visit = ctx.visits.get(key)
        label = _system_label(key, visit)
        for planet in planets:
            planet_rows.append(_planet_row(ctx.texts, planet, visit, ctx.sentinel_index, system_cell=label))
    planet_rows.sort(key=lambda r: (str(r[0]), str(r[1])))
    return {"type": "table", "title": f"Visited planets with resources ({len(planet_rows)})",
            "columns": ["System"] + PLANET_COLUMNS, "rows": planet_rows,
            "empty": "No planets recorded yet. Resources are read from the game's memory while you play, so "
                     "every system you visit from now on appears here."}


def systems_tabs(ctx: Context, selected: int | None) -> dict:
    """The Systems tab's sub-tabs: current system, visited systems (with the map), visited planets."""
    planets = visited_planets_section(ctx)
    return {"type": "tabs", "id": "systems-tabs", "tabs": [
        {"id": "current", "label": "Current system", "sections": live_notices(ctx.live) + current_system_sections(ctx)},
        {"id": "visited", "label": "Visited systems", "badge": len(ctx.keys()),
         "sections": visited_systems_sections(ctx, selected)},
        {"id": "planets", "label": "Planets", "badge": len(planets["rows"]), "sections": [planets]},
    ]}


def scan_log_section(ctx: Context, scans: list[dict]) -> dict:
    """The last memory scans, newest first: where you were, what was read, what was new or re-filed."""
    rows = []
    for scan in reversed(scans):
        here = scan.get("system")
        found = []
        for key_text, names in (scan.get("systems") or {}).items():
            key = parse_system_key(key_text)
            label = _system_label(key, ctx.visits.get(key)) if key is not None else key_text
            found.append(f"{label}: {len(names)}")
        rows.append([scan.get("at"), _system_label(here, ctx.visits.get(here)) if here is not None else "unknown",
                     scan.get("planets"), scan.get("new"), scan.get("changed"), scan.get("moved") or None,
                     ", ".join(found) or None])
    return {"type": "table", "title": f"Memory scans (last {len(rows)})",
            "columns": ["Time", "You were in", "Planets read", "New", "Changed", "Filed under your system",
                        "Planets in memory by system"],
            "rows": rows, "empty": "No scan of the game's memory yet."}
