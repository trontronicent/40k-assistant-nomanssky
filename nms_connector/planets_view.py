"""View sections for the current system and all visited systems and planets (pure)."""

from __future__ import annotations

from .summary import address_portal, galaxy_name, unpack_address

# GcPlanetInfo.SentinelsPerDifficulty is indexed by the ground combat timer setting.
COMBAT_TIMERS = {"Off": 0, "Slow": 1, "Normal": 2, "Fast": 3}


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
        ids += [p.get("common"), p.get("uncommon"), p.get("rare")] + list(p.get("extra") or [])
    return list(dict.fromkeys(i for i in ids if i))


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

    def item(self, item_id: str | None):
        """A resource id -> table cell with the game's icon and name (id when unknown)."""
        if not item_id:
            return None
        entry = self.gamedata.lookup(item_id) or {}
        label = self.both(entry.get("en"), entry.get("local")) or item_id
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


def _planet_row(texts: Texts, planet: dict, visit: dict | None, sentinel_index: int, system_cell=None) -> list:
    info = planet.get("info") or {}
    sentinels = info.get("sentinels") or []
    sentinel = sentinels[sentinel_index] if 0 <= sentinel_index < len(sentinels) else None
    row = [] if system_cell is None else [system_cell]
    row += [_planet_name(planet, visit), texts.description(info) or planet.get("biome"), texts.key(info.get("weather")),
            texts.item(planet.get("common")), texts.item(planet.get("uncommon")), texts.item(planet.get("rare")),
            texts.items(planet.get("extra")), texts.key(info.get("flora")), texts.key(info.get("fauna")),
            texts.key(sentinel)]
    return row


PLANET_COLUMNS = ["Planet", "Type", "Weather", "Resource 1", "Resource 2", "Resource 3", "Plants", "Flora", "Fauna",
                  "Sentinels"]


def sections(live, history, visits: dict, gamedata, combat_timer: str | None) -> list[dict]:
    texts = Texts(gamedata)
    sentinel_index = COMBAT_TIMERS.get(combat_timer or "Normal", 2)
    recorded = history.systems()
    out: list[dict] = []

    # --- live status / current system
    if live.status == "not-running":
        out.append({"type": "notice", "level": "info", "text":
                    "Start No Man's Sky to read live data: the planets of the system you are in (resources, weather, "
                    "sentinels) are then read from the game's memory, read-only, and remembered."})
    elif live.status in ("error", "unsupported"):
        out.append({"type": "notice", "level": "warn", "text": f"Live data unavailable: {live.error}"})
    if live.current_system is not None:
        visit = visits.get(live.current_system)
        planets = recorded.get(live.current_system, [])
        addr = unpack_address(live.current_system) or {}
        title = f"Current system: {_system_label(live.current_system, visit)}"
        out.append({"type": "table", "title": title + " (live from the game)", "columns": PLANET_COLUMNS,
                    "rows": [_planet_row(texts, p, visit, sentinel_index) for p in planets],
                    "empty": "No planet of this system has been generated yet - fly closer, the next scan picks it up."})
        on = (live.current or {}).get("GalacticAddress", {}).get("PlanetIndex", 0)
        here = next((p for p in planets if p.get("index") == on - 1), None) if on else None
        out.append({"type": "kv", "title": "Where you are now", "items": [
            {"label": "System", "value": _system_label(live.current_system, visit)},
            {"label": "Portal address", "value": address_portal(addr)},
            {"label": "Galaxy", "value": galaxy_name(addr.get("RealityIndex"))},
            {"label": "Planet", "value": _planet_name(here, visit) if here else ("in space" if not on else f"planet {on}")},
        ]})

    # --- all visited systems
    keys = set(visits) | set(recorded)
    rows = []
    for key in keys:
        visit = visits.get(key) or {}
        addr = unpack_address(key) or {}
        planets = recorded.get(key, [])
        last = max((p.get("last_seen") or "" for p in planets), default="") or None
        named = sum(1 for p in (visit.get("planets") or {}).values() if p.get("name"))
        rows.append([_system_label(key, visit), address_portal(addr), galaxy_name(addr.get("RealityIndex")),
                     len(planets) or None, named or None, visit.get("named_by"), last or visit.get("discovered_at"),
                     "yes" if key == live.current_system else ""])
    # Current system first, then systems with recorded resources, each newest first (sorts are stable).
    rows.sort(key=lambda r: r[6] or "", reverse=True)
    rows.sort(key=lambda r: (r[7] != "yes", r[3] is None))
    out.append({"type": "table", "title": f"Visited systems ({len(rows)})",
                "columns": ["System", "Portal address", "Galaxy", "Planets with resources", "Named planets",
                            "Named by", "Last seen / discovered", "Here"],
                "rows": rows, "empty": "No visited systems in the save yet."})

    # --- all recorded planets with resources
    planet_rows = []
    for key, planets in recorded.items():
        visit = visits.get(key)
        label = _system_label(key, visit)
        for planet in planets:
            planet_rows.append(_planet_row(texts, planet, visit, sentinel_index, system_cell=label))
    planet_rows.sort(key=lambda r: (str(r[0]), str(r[1])))
    out.append({"type": "table", "title": f"Visited planets with resources ({len(planet_rows)})",
                "columns": ["System"] + PLANET_COLUMNS[:-1] + ["Sentinels"],
                "rows": planet_rows,
                "empty": "No planets recorded yet. Resources are read from the game's memory while you play, so "
                         "every system you visit from now on appears here."})
    return out
