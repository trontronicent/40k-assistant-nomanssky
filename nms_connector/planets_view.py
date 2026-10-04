"""View sections for the current system, visited systems and planets, and system maps (pure)."""

from __future__ import annotations

from . import galaxy, route, trade
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
GALAXY_MAP_ID = "galaxy-map"
NEAREST_ID = "nearest-resources"
PLAN_ROUTE = "plan_route"
ROUTE_FORM_ID = "route-form"
ROUTE_RESULT_ID = "route-result"
DEFAULT_RANGE_LY = 1000
ROUTE_WIP_NOTE = ("Work in progress: the route planner is very much work in progress. Distances are estimated from "
                  "regions (about 400 ly per step, not yet checked against the game), the exact position of a system "
                  "inside its region is unknown, and routes have not been tested in the game yet. Use them as a rough "
                  "guide and check the jumps on the in-game galaxy map.")
POINT_COLORS = {"resources": "#5fbf6a", "save": "#8fa3b8", "bases": "#7ad7ff"}
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
        self.trade_hint = None          # set by Context: where a trade good sells (needs your economies)

    @staticmethod
    def both(en, local) -> str | None:
        if not en:
            return local or None
        return en if not local or local == en else f"{en} ({local})"

    def key(self, key: str | None, sibling: str | None = None) -> str | None:
        """A localisation key -> text; strings that are not keys (already translated) pass through.

        ``sibling`` (the planet's fauna key for its flora and vice versa) decides between the meanings of a
        translated value that has several (GameData.text_like)."""
        if not key:
            return None
        entry = self.gamedata.text(key)
        if not entry and sibling and not key.isupper():
            entry = self.gamedata.text_like(key, sibling)
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

    def category(self, item_id: str | None) -> str | None:
        """The category the game shows under an item's name ('Trade Goods (Construction) / Handelsgüter (Bau)':
        a slash, since categories often carry brackets themselves)."""
        entry = (self.gamedata.lookup(item_id) or {}) if item_id else {}
        en, local = entry.get("cat_en"), entry.get("cat_local")
        return f"{en} / {local}" if en and local and local != en else (en or local or None)

    def hint(self, item_id: str | None) -> str | None:
        """Tooltip of an item: category, description and - for trade goods - where they sell."""
        if not item_id:
            return None
        entry = self.gamedata.lookup(item_id) or {}
        lines = []
        if self.category(item_id):
            lines.append(f"Category: {self.category(item_id)}")
        if entry.get("desc_en"):
            lines.append(entry["desc_en"])
        trade_lines = self.trade_hint(item_id) if self.trade_hint else None
        if trade_lines:
            lines.append(trade_lines)
        return "\n\n".join(lines) or None

    def item(self, item_id: str | None, text: str | None = None):
        """An item id -> table cell with the game's icon, name (id when unknown) and tooltip."""
        if not item_id:
            return None
        label = text or self.name(item_id)
        cell = {"text": label}
        icon = self.gamedata.icon_name(item_id)
        if icon:
            cell["icon"] = icon
        hint = self.hint(item_id)
        if hint:
            cell["hint"] = hint
        return cell if len(cell) > 1 else label

    def items(self, ids) -> str | None:
        names = [(self.gamedata.lookup(i) or {}).get("en") or i for i in ids or []]
        return ", ".join(names) or None


def _system_label(key: int, visit: dict | None) -> str:
    """The uploaded name, else the generated one the game shows, else 'System <portal address>'."""
    name = (visit or {}).get("name") or (visit or {}).get("generated_name")
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
            texts.items(planet.get("extra")), texts.item(planet_gas(planet)), texts.key(info.get("flora"), info.get("fauna")),
            texts.key(info.get("fauna"), info.get("flora")), texts.key(_sentinel(planet, sentinel_index))]
    return row


class Context:
    """Everything the system and planet sections are built from."""

    def __init__(self, live, history, visits: dict, gamedata, combat_timer: str | None, bases=None, origin=None,
                 save_position: dict | None = None):
        self.live, self.history, self.visits = live, history, visits
        self.save_position = save_position     # {system, planet (save layout: 0 = space), at} of the newest save
        self.texts = Texts(gamedata)
        self.sentinel_index = COMBAT_TIMERS.get(combat_timer or "Normal", 2)
        self.recorded = history.systems()
        self.bases = bases or []
        # Where distances are measured from: the system you are in, else where you were at the last save.
        self.origin = live.current_system if getattr(live, "current_system", None) is not None else origin
        self.economies = getattr(history, "economies", {}) or {}
        self.system_names = getattr(history, "system_names", {}) or {}
        self.trading = getattr(gamedata, "trading", None) or trade.FALLBACK
        self.trading_source = getattr(gamedata, "trading_source", "built-in")
        self.texts.trade_hint = self.trade_hint

    def trade_hint(self, item_id: str | None) -> str | None:
        """For a trade good: which economies pay well for it and whether you know such a system (nearest first),
        and where it is cheap to buy. None for anything else."""
        category = trade.category_of(item_id)
        if category is None:
            return None
        buyers = [e for e, t in self.trading.items() if t.get("needs") == category]
        sellers = [e for e, t in self.trading.items() if t.get("sells") == category]
        lines = []
        if buyers:
            low, high = (self.trading[buyers[0]].get("buys_at") or ("?", "?"))[:2]
            lines.append(f"Sell at: {', '.join(self.economy_name(e) for e in buyers)} economies "
                         f"(they pay x{low}-{high} of the value).")
            known = self._nearest_economy(buyers)
            if known:
                lines.append(f"Known system that buys it: {known}.")
                more = sum(1 for e in self.economies.values() if e.get("economy") in buyers) - 1
                if more > 0:
                    lines.append(f"({more} more known; see Systems -> Trade.)")
            else:
                lines.append("You have not found such a system yet (a system's economy is read while you visit it "
                             "with the game running).")
        if sellers:
            known = self._nearest_economy(sellers)
            lines.append(f"Cheap to buy at: {', '.join(self.economy_name(e) for e in sellers)} economies"
                         + (f" - nearest known: {known}." if known else "."))
        return "\n".join(lines) or None

    def _nearest_economy(self, economy_classes: list[str]) -> str | None:
        """'Name - 1,200 ly away (Wealthy)' for the nearest known system with one of these economies."""
        keys = [k for k, e in self.economies.items() if e.get("economy") in economy_classes]
        if not keys:
            return None

        def rank(k):
            d = galaxy.distance_ly(self.origin, k) if self.origin is not None else None
            return (k != self.origin, d is None, d or 0.0, k)
        key = min(keys, key=rank)
        where = ("you are there" if key == self.origin else galaxy.distance_text(galaxy.distance_ly(self.origin, key)))\
            if self.origin is not None and galaxy.distance_ly(self.origin, key) is not None else "distance unknown"
        wealth = self.economies[key].get("wealth")
        return f"{_system_label(key, self.visit(key))} - {where}" + (f" ({wealth})" if wealth else "")

    # --- economy texts (the game's names, English and game language)

    def economy_name(self, economy: str | None) -> str | None:
        if not economy:
            return None
        key = trade.ECONOMY_KEYS.get(economy)
        entry = self.texts.gamedata.text(key) if key else None
        return self.texts.both(entry["en"], entry["local"]) if entry else trade.ECONOMY_FALLBACK_NAMES.get(economy, economy)

    def conflict_name(self, conflict: str | None) -> str | None:
        if not conflict:
            return None
        key = trade.CONFLICT_KEYS.get(conflict)
        entry = self.texts.gamedata.text(key) if key else None
        return self.texts.both(entry["en"], entry["local"]) if entry else conflict

    def economy_summary(self, key: int) -> str | None:
        """'Trading (Average)' for a system with a recorded economy, else None."""
        e = self.economies.get(key)
        if not e:
            return None
        return f"{self.economy_name(e.get('economy'))} ({e.get('wealth')})"

    def goods_text(self, category: str | None) -> str | None:
        if not category:
            return None
        names = [self.texts.name(g) for g in trade.goods(category)]
        return f"{trade.CATEGORY_NAMES.get(category, category)}: " + ", ".join(n for n in names if n)

    def economy_items(self, key: int) -> list[dict]:
        """Economy, wealth, conflict, race and the trade goods to buy and sell there (for a details panel)."""
        e = self.economies.get(key)
        if not e:
            return [{"label": "Economy", "value": "not read yet - visit the system while the game runs"}]
        t = self.trading.get(e.get("economy"), {})
        lo, hi = (t.get("sells_at") or (None, None))
        blo, bhi = (t.get("buys_at") or (None, None))
        return [
            {"label": "Economy", "value": self.economy_name(e.get("economy"))},
            {"label": "Wealth", "value": e.get("wealth")},
            {"label": "Conflict", "value": self.conflict_name(e.get("conflict"))},
            {"label": "Dominant race", "value": e.get("race")},
            {"label": f"Cheap to buy here (x{lo}-{hi})" if lo else "Cheap to buy here", "value": self.goods_text(t.get("sells"))},
            {"label": f"Sells well here (x{blo}-{bhi})" if blo else "Sells well here", "value": self.goods_text(t.get("needs"))},
        ]

    def keys(self) -> set[int]:
        return set(self.visits) | set(self.recorded)

    def visit(self, key: int) -> dict | None:
        """What the save says about a system, plus its generated name when the game's memory showed it."""
        visit = self.visits.get(key)
        generated = self.system_names.get(key)
        if not generated:
            return visit
        return {**(visit or {}), "generated_name": generated}

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
    visit = ctx.visit(key)
    addr = unpack_address(key) or {}
    index = ctx.current_planet_index()
    here = next((p for p in ctx.recorded.get(key, []) if p.get("index") == index), None) if index is not None else None
    exact = getattr(ctx.live, "current_source", "player") == "player"
    saved = ctx.save_position if not exact and ctx.save_position and ctx.save_position.get("system") == key else None
    if here:
        planet = _planet_name(here, visit)
    elif saved:
        # The game saves about once a minute while you play: in the same system, the save's planet is the best
        # answer when memory has no exact position (it may be a minute old, so the time is shown).
        on = saved.get("planet") or 0
        there = next((p for p in ctx.recorded.get(key, []) if p.get("index") == on - 1), None) if on else None
        name = _planet_name(there, visit) if there else (f"planet {on}" if on else "in space")
        planet = f"{name} (at the last save, {saved.get('at')})"
    elif not exact:
        planet = "unknown (your exact position cannot be read right now)"
    else:
        planet = "in space" if index is None else f"planet {index + 1}"
    return {"type": "kv", "title": "Where you are now", "items": [
        {"label": "System", "value": _system_label(key, visit)},
        *([{"label": "Generated name", "value": visit["generated_name"]}]
          if visit and visit.get("name") and visit.get("generated_name") not in (None, visit.get("name")) else []),
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
    ] + ctx.economy_items(key)
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
            {"label": "Flora", "value": texts.key(info.get("flora"), info.get("fauna"))},
            {"label": "Fauna", "value": texts.key(info.get("fauna"), info.get("flora")) + (" (special fauna)" if planet.get("special_fauna") else "")
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
    visit = ctx.visit(key) or {}
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
    visit = ctx.visit(key)
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
    return last or (ctx.visit(key) or {}).get("discovered_at") or ""


def visited_systems_sections(ctx: Context, selected: int | None) -> list[dict]:
    entries = []
    for key in ctx.keys():
        visit = ctx.visit(key) or {}
        addr = unpack_address(key) or {}
        planets = ctx.recorded.get(key, [])
        named = sum(1 for p in (visit.get("planets") or {}).values() if p.get("name"))
        row = [_system_label(key, visit), address_portal(addr), galaxy_name(addr.get("RealityIndex")),
               len(planets) or None, named or None, visit.get("named_by"), _last_seen(key, ctx) or None,
               "yes" if key == ctx.live.current_system else "",
               ctx.economy_summary(key), ctx.conflict_name((ctx.economies.get(key) or {}).get("conflict"))]
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
                            "Named by", "Last seen / discovered", "Here", "Economy", "Conflict"],
                "rows": [row for row, _ in entries], "row_action": OPEN_SYSTEM,
                "row_keys": [system_key_text(key) for _, key in entries],
                "selected_key": system_key_text(shown) if shown is not None else None,
                "row_hint": "Click a system to show its star and planets in the map above.",
                "empty": "No visited systems in the save yet."})
    return out


def visited_planets_section(ctx: Context) -> dict:
    planet_rows = []
    for key, planets in ctx.recorded.items():
        visit = ctx.visit(key)
        label = _system_label(key, visit)
        for planet in planets:
            planet_rows.append(_planet_row(ctx.texts, planet, visit, ctx.sentinel_index, system_cell=label))
    planet_rows.sort(key=lambda r: (str(r[0]), str(r[1])))
    return {"type": "table", "title": f"Visited planets with resources ({len(planet_rows)})",
            "columns": ["System"] + PLANET_COLUMNS, "rows": planet_rows,
            "empty": "No planets recorded yet. Resources are read from the game's memory while you play, so "
                     "every system you visit from now on appears here."}


def _galaxy_point(key: int, ctx: Context) -> dict:
    visit = ctx.visit(key) or {}
    planets = ctx.recorded.get(key, [])
    addr = unpack_address(key) or {}
    bases = [b["name"] for b in ctx.bases if b.get("system") == key]
    x, y, z = galaxy.map_position(key)
    dist = galaxy.distance_ly(ctx.origin, key) if ctx.origin is not None else None
    point = {"key": system_key_text(key), "label": _system_label(key, visit), "sublabel": address_portal(addr),
             "x": round(x, 3), "y": round(y, 3), "z": round(z, 3),
             "items": [
                 {"label": "Portal address", "value": address_portal(addr)},
                 {"label": "Region (voxel X, Y, Z)", "value": ", ".join(str(v) for v in galaxy.region(key))},
                 {"label": "Distance from you", "value": galaxy.distance_text(dist, key == ctx.origin) if ctx.origin is not None else "unknown"},
                 {"label": "Economy", "value": ctx.economy_summary(key) or "not read yet"},
                 {"label": "Planets with resources", "value": len(planets) or None},
                 {"label": "Named by", "value": visit.get("named_by")},
                 {"label": "Your bases here", "value": ", ".join(bases) or None},
                 {"label": "Last seen / discovered", "value": _last_seen(key, ctx) or None},
             ]}
    if key == ctx.live.current_system:
        point["marker"] = "current"
    elif key == ctx.origin:
        point["marker"] = "target"
    elif bases:
        point["color"] = POINT_COLORS["bases"]
    else:
        point["color"] = POINT_COLORS["resources"] if planets else POINT_COLORS["save"]
    if bases:
        point["size"] = 1.3
    return point


def galaxy_sections(ctx: Context, selected: int | None) -> list[dict]:
    """The galaxy map of every known system (in the galaxy you are in) and the nearest planet per resource."""
    keys = sorted(ctx.keys())
    if not keys:
        return [{"type": "text", "text": "No systems known yet: they come from your save and from the game while it runs."}]
    here = galaxy.galaxy_of(ctx.origin) if ctx.origin is not None else max(
        {galaxy.galaxy_of(k) for k in keys}, key=lambda g: sum(1 for k in keys if galaxy.galaxy_of(k) == g))
    shown = [k for k in keys if galaxy.galaxy_of(k) == here]
    elsewhere = len(keys) - len(shown)
    gname = galaxy_name(here)
    out = [{
        "type": "starmap", "id": GALAXY_MAP_ID, "title": f"Galaxy map: {gname} ({len(shown)} systems)",
        "points": [_galaxy_point(k, ctx) for k in shown], "action": OPEN_SYSTEM, "action_label": "Open system map",
        "selected_key": system_key_text(selected) if selected in shown else None,
        "center": {"label": "Galaxy centre", "x": 0, "y": 0, "z": 0}, "bounds": galaxy.GALAXY_BOUNDS,
        "legend": [{"label": "You are here", "color": "#ffd27a"},
                   {"label": "Planets with resources", "color": POINT_COLORS["resources"]},
                   {"label": "Known from the save only", "color": POINT_COLORS["save"]},
                   {"label": "Your bases", "color": POINT_COLORS["bases"]}],
        "empty": "No systems in this galaxy yet.",
    }]
    notes = ["Systems of one region sit on a small circle around the region's point; the save holds no finer "
             "position. Distances are measured between regions (~400 ly per step) and are approximate."]
    if elsewhere:
        notes.append(f"{elsewhere} known system(s) lie in other galaxies and are not on this map.")
    out.append({"type": "text", "text": " ".join(notes)})

    nearest = galaxy.nearest_by_resource({k: ctx.recorded[k] for k in ctx.recorded}, ctx.origin, planet_gas)
    rows, keys_out = [], []
    for e in sorted(nearest, key=lambda e: (e["distance"] is None, e["system"] != ctx.origin, e["distance"] or 0,
                                            ctx.texts.name(e["resource"]) or "")):
        visit = ctx.visit(e["system"])
        rows.append([ctx.texts.item(e["resource"]), _planet_name(e["planet"], visit), _system_label(e["system"], visit),
                     galaxy.distance_text(e["distance"], e["system"] == ctx.origin) if ctx.origin is not None else "unknown",
                     e["count"]])
        keys_out.append(system_key_text(e["system"]))
    out.append({"type": "table", "id": NEAREST_ID, "title": "Nearest planet with each resource",
                "columns": ["Resource", "Nearest planet", "System", "Distance from you", "Planets there"],
                "rows": rows, "row_action": OPEN_SYSTEM, "row_keys": keys_out,
                "row_hint": "Among the planets whose resources were read. Click a row to open that system's map.",
                "empty": "No planet resources read yet: they are read from the game while you play."})
    return out


def trade_sections(ctx: Context) -> list[dict]:
    """The Trade tab: the economies of your systems and, per kind of trade goods, where to buy and where to sell."""
    known = sorted(ctx.economies, key=lambda k: (k != ctx.origin, galaxy.distance_ly(ctx.origin, k) if ctx.origin is not None
                                                  and galaxy.distance_ly(ctx.origin, k) is not None else 1e12, k))
    rows, keys = [], []
    for key in known:
        e = ctx.economies[key]
        t = ctx.trading.get(e.get("economy"), {})
        dist = galaxy.distance_ly(ctx.origin, key) if ctx.origin is not None else None
        rows.append([_system_label(key, ctx.visit(key)), ctx.economy_name(e.get("economy")), e.get("wealth"),
                     ctx.conflict_name(e.get("conflict")), e.get("race"),
                     trade.CATEGORY_NAMES.get(t.get("sells"), t.get("sells")),
                     trade.CATEGORY_NAMES.get(t.get("needs"), t.get("needs")),
                     galaxy.distance_text(dist, key == ctx.origin) if ctx.origin is not None else "unknown"])
        keys.append(system_key_text(key))
    out = [{"type": "table", "id": "economies", "title": f"Economies of your systems ({len(rows)})",
            "columns": ["System", "Economy", "Wealth", "Conflict", "Race", "Cheap to buy here", "Sells well here",
                        "Distance from you"],
            "rows": rows, "row_action": OPEN_SYSTEM, "row_keys": keys,
            "row_hint": "Click a system to open its map; its star lists the trade goods to buy and sell there.",
            "empty": "No economy read yet: it is read from the game for every system you visit while it runs."}]

    route_rows, route_keys = [], []
    for r in trade.routes(ctx.economies, ctx.trading, ctx.origin):
        def place(key):
            if key is None:
                return None
            return f"{_system_label(key, ctx.visit(key))} ({ctx.economy_name(ctx.economies[key].get('economy'))})"
        sellers = [e for e, t in ctx.trading.items() if t.get("sells") == r["category"]]
        buyers = [e for e, t in ctx.trading.items() if t.get("needs") == r["category"]]
        route_rows.append([
            trade.CATEGORY_NAMES.get(r["category"], r["category"]),
            ", ".join(n for n in (ctx.texts.name(g) for g in trade.goods(r["category"])) if n),
            place(r["buy"]) or f"not found yet - look for: {', '.join(ctx.economy_name(e) for e in sellers)}",
            place(r["sell"]) or f"not found yet - look for: {', '.join(ctx.economy_name(e) for e in buyers)}",
            galaxy.distance_text(r["between"], r["buy"] == r["sell"]) if r["between"] is not None else None,
            galaxy.distance_text(r["buy_distance"], r["buy"] == ctx.origin) if r["buy_distance"] is not None else None,
        ])
        route_keys.append(system_key_text(r["buy"]) if r["buy"] is not None else None)
    out.append({"type": "table", "id": "trade-routes", "title": "Trade routes between your systems",
                "columns": ["Goods", "Trade goods (tier 1-5)", "Buy cheap at", "Sell well at", "Between them",
                            "From you to the seller"],
                "rows": route_rows, "row_action": OPEN_SYSTEM, "row_keys": route_keys,
                "row_hint": "Buy where the economy sells the goods, sell where it needs them. Click a row to open the "
                            "system to buy in."})
    sample = ctx.trading.get("Mining", {})
    out.append({"type": "text", "text":
                f"Each economy sells one kind of trade goods cheaply (stations ask x{sample.get('sells_at', ('?', '?'))[0]}-"
                f"{sample.get('sells_at', ('?', '?'))[1]} of the value) and pays well for another "
                f"(x{sample.get('buys_at', ('?', '?'))[0]}-{sample.get('buys_at', ('?', '?'))[1]}); the table comes from "
                f"the {ctx.trading_source}. A system's economy is read from the game's galaxy map data while you are "
                "there with the game running; systems visited before show theirs after your next visit. Prices also "
                "move with what you buy and sell, and wealthier systems trade the higher tiers."})
    return out


def route_nodes(ctx: Context) -> list[int]:
    """Every system the route planner may use as a stop: visited, discovered, recorded or with a known economy."""
    return sorted(ctx.keys() | set(ctx.economies))


def _region_text(region: tuple[int, int, int]) -> str:
    x, y, z = region
    return f"region {x}, {y}, {z}"


def route_sections(ctx: Context, state: dict | None) -> list[dict]:
    """The Route tab: the form (target, portal address, jump range) and the last planned route."""
    state = state or {}
    request = state.get("request") or {}
    out: list[dict] = [{"type": "notice", "level": "warn", "text": ROUTE_WIP_NOTE}]
    if ctx.origin is None:
        out.append({"type": "notice", "level": "info", "text":
                    "Where you are is not known yet (no save read and no live data), so routes cannot start anywhere."})
    here = galaxy.galaxy_of(ctx.origin) if ctx.origin is not None else None
    options = sorted(((_system_label(k, ctx.visit(k)), k) for k in route_nodes(ctx)
                      if here is None or galaxy.galaxy_of(k) == here), key=lambda o: o[0].lower())
    out.append({
        "type": "form", "id": ROUTE_FORM_ID, "title": "Plan a route", "action": PLAN_ROUTE, "submit_label": "Plan route",
        "description": "From where you are to a known system, or to any system by its portal address. A jump costs one "
                       "warp cell however far it goes within your range, so the route has the fewest jumps; your known "
                       "systems are used as stops where they cost no extra jump.",
        "fields": [
            {"id": "target", "label": "Target system", "type": "select",
             "options": [{"value": system_key_text(k), "label": f"{label} ({address_portal(unpack_address(k) or {})})"}
                         for label, k in options] or [{"value": "", "label": "no known systems yet"}],
             "value": request.get("target"), "hint": "One of the systems you know (visited, discovered or read)."},
            {"id": "portal", "label": "or portal address", "type": "text", "max_length": 14, "placeholder": "e.g. 006202925E80",
             "value": request.get("portal") or "", "hint": "12 portal glyphs as hex digits; when set it is used instead of the list."},
            {"id": "range", "label": "Jump range (light years)", "type": "number", "min": 50, "max": 20000, "step": 50,
             "value": request.get("range") or DEFAULT_RANGE_LY,
             "hint": "Your hyperdrive's range (see the ship's hyperdrive in the game). Leave some margin: distances are approximate."},
        ]})
    result = state.get("result")
    if not result:
        return out
    def label(key):
        return _system_label(key, ctx.visit(key))

    if result.get("arrived"):
        out.append({"type": "notice", "level": "info", "text": f"You have arrived at {label(result['target'])}."})
        return out
    if not result.get("ok"):
        out.append({"type": "notice", "level": "warn", "text": f"No route: {result.get('reason')}"})
        return out

    legs = result["legs"]
    target = legs[-1]["to"]
    out.append({"type": "kv", "id": ROUTE_RESULT_ID, "title": f"Route to {label(target)}", "items": [
        {"label": "From", "value": f"{label(legs[0]['from'])} (you)"},
        {"label": "To", "value": f"{label(target)} - portal {address_portal(unpack_address(target) or {})}"},
        {"label": "Jumps", "value": f"{result['jumps']}" + (f" ({result['unknown_jumps']} of them into unknown space)" if result["unknown_jumps"] else " (all to known systems)")},
        {"label": "Distance", "value": galaxy.distance_text(result["distance"])},
        {"label": "Straight line", "value": f"{galaxy.distance_text(result['direct_distance'])}, {result['direct_jumps']} jump(s)"},
        {"label": "Jump range used", "value": f"{result['range']:,.0f} ly"},
        {"label": "Economy at the target", "value": ctx.economy_summary(target) or "not read yet"},
    ]})
    rows = []
    for i, leg in enumerate(legs, 1):
        if leg["jumps"] == 1:
            how = "one jump"
        else:
            way = leg["waypoints"]
            shown = way if len(way) <= 6 else way[:3] + [None] + way[-1:]
            aims = " -> ".join("..." if w is None else _region_text(w) for w in shown)
            more = f" ({len(way)} regions in all, ~{galaxy.distance_text(leg['distance'] / leg['jumps'])[1:]} per jump)" if len(way) > 6 else ""
            how = f"{leg['jumps']} jumps through unknown space: aim for {aims}, then the target{more}"
        rows.append([i, label(leg["from"]), label(leg["to"]), galaxy.distance_text(leg["distance"]), leg["jumps"], how])
    out.append({"type": "table", "title": "Legs", "columns": ["#", "From", "To", "Distance", "Jumps", "How"], "rows": rows})

    # The route on a map: stops (you, known systems, target) and the regions to aim for in between.
    points, line = [], []
    for i, leg in enumerate(legs):
        for key in ([leg["from"]] if i == 0 else []):
            x, y, z = galaxy.map_position(key)
            points.append({"key": system_key_text(key), "label": label(key), "x": x, "y": y, "z": z, "marker": "current"})
            line.append([x, y, z])
        step = max(1, len(leg["waypoints"]) // 50)          # at most ~50 drawn per leg; the table has the count
        for j, w in [(j, w) for j, w in enumerate(leg["waypoints"], 1) if j % step == 0]:
            points.append({"key": f"wp-{i}-{j}", "label": f"Jump {j} of leg {i + 1}", "sublabel": _region_text(w),
                           "x": w[0], "y": w[1], "z": w[2], "color": "#8fa3b8", "size": 0.6})
            line.append(list(w))
        x, y, z = galaxy.map_position(leg["to"])
        stop = {"key": system_key_text(leg["to"]), "label": label(leg["to"]), "x": x, "y": y, "z": z}
        if leg["to"] == target:
            stop["marker"] = "target"
        else:
            stop["color"] = POINT_COLORS["resources"]
        points.append(stop)
        line.append([x, y, z])
    out.append({"type": "starmap", "title": "The route", "points": points, "lines": [{"points": line, "label": "Route"}],
                "action": OPEN_SYSTEM, "action_label": "Open system map",
                "legend": [{"label": "You", "color": "#ffd27a"}, {"label": "Target", "color": "#ff7a7a"},
                           {"label": "Known stop", "color": POINT_COLORS["resources"]},
                           {"label": "Region to aim for", "color": "#8fa3b8"}]})
    return out


def systems_tabs(ctx: Context, selected: int | None, route_state: dict | None = None) -> dict:
    """The Systems tab's sub-tabs: current system, visited systems (with the map), visited planets."""
    planets = visited_planets_section(ctx)
    return {"type": "tabs", "id": "systems-tabs", "tabs": [
        {"id": "current", "label": "Current system", "sections": live_notices(ctx.live) + current_system_sections(ctx)},
        {"id": "visited", "label": "Visited systems", "badge": len(ctx.keys()),
         "sections": visited_systems_sections(ctx, selected)},
        {"id": "planets", "label": "Planets", "badge": len(planets["rows"]), "sections": [planets]},
        {"id": "galaxy", "label": "Galaxy", "sections": galaxy_sections(ctx, selected)},
        {"id": "trade", "label": "Trade", "badge": len(ctx.economies) or None, "sections": trade_sections(ctx)},
        {"id": "route", "label": "Route", "sections": route_sections(ctx, route_state)},
    ]}


def scan_log_section(ctx: Context, scans: list[dict]) -> dict:
    """The last memory scans, newest first: where you were, what was read, what was new or re-filed."""
    rows = []
    for scan in reversed(scans):
        here = scan.get("system")
        found = []
        for key_text, names in (scan.get("systems") or {}).items():
            key = parse_system_key(key_text)
            label = _system_label(key, ctx.visit(key)) if key is not None else key_text
            found.append(f"{label}: {len(names)}")
        rows.append([scan.get("at"), _system_label(here, ctx.visit(here)) if here is not None else "unknown",
                     scan.get("planets"), scan.get("new"), scan.get("changed"), scan.get("moved") or None,
                     ", ".join(found) or None])
    return {"type": "table", "title": f"Memory scans (last {len(rows)})",
            "columns": ["Time", "You were in", "Planets read", "New", "Changed", "Filed under your system",
                        "Planets in memory by system"],
            "rows": rows, "empty": "No scan of the game's memory yet."}
