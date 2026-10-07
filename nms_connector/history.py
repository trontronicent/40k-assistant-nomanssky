"""Visited systems and planets: what the save knows plus what memory reading recorded.

The save lists the systems you visited (``VisitedSystems``, packed addresses)
and your discoveries (systems, planets, flora, fauna, minerals) with any names
that were uploaded. It does not contain planet resources: the game generates
those from the planet's seed when you arrive. So resources are recorded from
the game's memory whenever you are in a system, and kept in
``planet_history.json`` - systems visited before the plugin ran have names and
discovery counts, but no resources until you return.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import logs
from .memory import system_key

HISTORY_VERSION = 2
DISCOVERY_COUNTED = {"Flora": "flora", "Animal": "fauna", "Mineral": "minerals"}


def _packed(value) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        except ValueError:
            return None
    return None


def visits_from_save(save: dict) -> dict[int, dict]:
    """{system key: {"name", "named_by", "visited", "discovered_at", "planets": {index: {...}}}} from a save."""
    ps = (save.get("BaseContext") or {}).get("PlayerStateData") or {}
    systems: dict[int, dict] = {}

    def system(key: int) -> dict:
        return systems.setdefault(key, {"name": None, "named_by": None, "visited": False, "discovered_at": None,
                                        "planets": {}})

    for value in ps.get("VisitedSystems") or []:
        packed = _packed(value)
        if packed is not None:
            system(system_key(packed))["visited"] = True
    records = (((save.get("DiscoveryManagerData") or {}).get("DiscoveryData-v1") or {}).get("Store") or {}).get("Record") or []
    for record in records:
        dd = record.get("DD") or {}
        packed = _packed(dd.get("UA"))
        kind = dd.get("DT")
        if packed is None or not kind:
            continue
        entry = system(system_key(packed))
        planet_index = (packed >> 52) & 0xF
        name = (record.get("DM") or {}).get("CN")
        owner = (record.get("OWS") or {}).get("USN")
        stamp = (record.get("OWS") or {}).get("TS")
        when = datetime.fromtimestamp(stamp).isoformat(timespec="seconds") if isinstance(stamp, int) and stamp > 0 else None
        if kind == "SolarSystem":
            entry["name"], entry["named_by"], entry["discovered_at"] = name or entry["name"], owner if name else entry["named_by"], when
        elif kind == "Planet" and planet_index:
            planet = entry["planets"].setdefault(planet_index - 1, {})
            if name:
                planet["name"], planet["named_by"] = name, owner
        elif kind in DISCOVERY_COUNTED and planet_index:
            planet = entry["planets"].setdefault(planet_index - 1, {})
            planet[DISCOVERY_COUNTED[kind]] = planet.get(DISCOVERY_COUNTED[kind], 0) + 1
    return systems


# Records from before 0.4.0 carry no seed; for them a rename is judged from what the planet is made of.
SAME_PLANET_FIELDS = ("index", "biome", "common", "uncommon", "rare")


def is_renamed(old: dict, planet: dict, current_system: int | None) -> bool:
    """True when `planet` is the recorded `old` planet under a new name (renamed in the game, or an
    uploaded name arrived).

    The generation seed decides: it is fixed per planet. A different planet in a reused slot can share the
    address, index, biome and all three resources (same star colour, same biome), so for an old record
    without a seed those fields only count when the record's address names the system you are in - a
    reused slot carries the *previous* system's address.
    """
    if old.get("ua") != planet.get("ua") or old.get("name") == planet.get("name"):
        return False
    if old.get("seed") and planet.get("seed"):
        return old["seed"] == planet["seed"]
    return current_system is not None and planet.get("system") == current_system         and all(old.get(f) == planet.get(f) for f in SAME_PLANET_FIELDS)


def planet_id(planet: dict) -> str:
    """Identity of a recorded planet: the address its record carried plus its name.

    The address alone is not enough: when the game reuses a planet slot for the
    next system, the record can keep the previous planet's address (seen
    2026-10-03: after a warp every planet of the old system was replaced by one
    of the new system). Generated names are fixed per planet, so two records
    with one address and different names are two planets.
    """
    return f"{planet['ua']:x}:{planet.get('name') or '?'}"


def _valid_fix(fix) -> bool:
    """A stored star fix as positions.StarFixer writes it (anything else is dropped on load)."""
    return (isinstance(fix, dict) and isinstance(fix.get("id"), int) and isinstance(fix.get("position"), list)
            and len(fix["position"]) == 3 and all(isinstance(c, (int, float)) for c in fix["position"])
            and (fix.get("system") is None or isinstance(fix.get("system"), str)))


class PlanetHistory:
    """Every planet read from memory, persisted as JSON - only ever added to or refreshed, never replaced.

    Each scan is merged *differentially*: a planet already recorded (same id) is
    refreshed, a new one is added, nothing is removed. A record whose address
    names another system than the one you are in, while that address already
    belongs to a different planet, carries a stale address: it is filed under
    the system you are in. The previous file is kept as ``.bak`` and the last
    MAX_SCANS scans are logged (what was read, what was new, what was moved).
    """

    MAX_SCANS = 50

    def __init__(self, path: Path):
        self.path = Path(path)
        self.planets: dict[str, dict] = {}
        self.scans: list[dict] = []
        self.economies: dict[int, dict] = {}       # system key -> star attributes (economy, wealth, conflict, race)
        self.system_names: dict[int, str] = {}     # system key -> generated name from the galaxy map's cache
        # PROTOTYPE (positions.py): star fixes from the galaxy map's camera, named by the user -> exact positions.
        self.star_fixes: list[dict] = []
        # Positions recorded before 0.10.0 from the map camera's eye - wrong (they were never star positions); kept
        # in the file for research, never used.
        self.positions_discarded: dict[str, list] = {}
        self.load()

    def load(self) -> None:
        """Load the history file (the .bak copy when the main file is damaged), migrating version 1 files."""
        for path in (self.path, self.path.with_suffix(".json.bak")):
            raw = logs.read_json(path, "The planet history")
            if raw is None:
                continue
            if not isinstance(raw, dict) or not isinstance(raw.get("planets"), dict):
                continue
            if raw.get("version") == 1:   # keyed by address only
                for key, value in raw["planets"].items():
                    if isinstance(value, dict) and str(key).isdigit():
                        value["ua"] = int(key)
                        self.planets[planet_id(value)] = value
            elif raw.get("version") == HISTORY_VERSION:
                self.planets = {k: v for k, v in raw["planets"].items() if isinstance(v, dict) and isinstance(v.get("ua"), int)}
                self.scans = [x for x in raw.get("scans") or [] if isinstance(x, dict)][-self.MAX_SCANS:]
                self.economies = {int(k, 16): v for k, v in (raw.get("economies") or {}).items() if isinstance(v, dict)}
                self.system_names = {int(k, 16): v for k, v in (raw.get("system_names") or {}).items()
                                     if isinstance(v, str) and v}
                self.positions_discarded = {str(k): v for k, v in
                                            {**(raw.get("positions_discarded") or {}), **(raw.get("positions") or {})}.items()
                                            if isinstance(v, list) and len(v) == 3}
                self.star_fixes = [f for f in raw.get("star_fixes") or [] if _valid_fix(f)]
            else:
                continue
            return

    @property
    def positions(self) -> dict[int, tuple]:
        """{system key: exact position} of the named star fixes (PROTOTYPE)."""
        from .positions import named_positions
        return named_positions(self.star_fixes)

    def save(self) -> None:
        """Write the history atomically, keeping the previous file as .json.bak."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": HISTORY_VERSION, "planets": self.planets, "scans": self.scans,
                                   "economies": {f"{k:x}": v for k, v in self.economies.items()},
                                   "system_names": {f"{k:x}": v for k, v in self.system_names.items()},
                                   "star_fixes": self.star_fixes, "positions_discarded": self.positions_discarded},
                                  ensure_ascii=False), encoding="utf-8")
        if self.path.exists():
            self.path.replace(self.path.with_suffix(".json.bak"))
        tmp.replace(self.path)

    def record(self, planets: list[dict], now: str, current_system: int | None = None) -> int:
        """Merge planets read from memory; returns how many are new or changed. Logs the scan."""
        changed = new = moved = renamed = 0
        names_at = {}                                   # address -> names already recorded there
        for stored in self.planets.values():
            names_at.setdefault(stored["ua"], set()).add(stored.get("name"))
        by_place = {(v.get("system"), v.get("index"), v.get("name")): k for k, v in self.planets.items()}
        seen: dict[int, list[str]] = {}
        for planet in planets:
            stored = {k: v for k, v in planet.items()}
            known = self.planets.get(planet_id(planet))
            previous_name = None
            if known is None:
                # Renamed in the game (or an uploaded name arrived): the same planet under a new name. Its old
                # entry is taken over - same filing, same first_seen - instead of staying behind as a duplicate.
                old_key = next((k for k, v in self.planets.items() if is_renamed(v, planet, current_system)), None)
                if old_key is not None:
                    known = self.planets.pop(old_key)
                    previous_name = known.get("name")
                    names_at.get(planet["ua"], set()).discard(previous_name)
                    by_place.pop((known.get("system"), known.get("index"), previous_name), None)
                    renamed += 1
            system = planet["system"]
            if known is not None:
                system = known.get("system", system)    # seen before: stays where it was filed
            elif current_system is not None and system != current_system \
                    and names_at.get(planet["ua"], set()) - {planet.get("name")}:
                system = current_system                 # stale address: another planet owns it
            stored["system"] = system
            key = by_place.get((system, planet.get("index"), planet.get("name"))) or planet_id(planet)
            old = self.planets.get(key)
            if old is None and previous_name is not None:
                old = known
                stored["previous_names"] = list(dict.fromkeys((known.get("previous_names") or []) + [previous_name]))
            elif old is not None and old.get("previous_names"):
                stored["previous_names"] = old["previous_names"]
            # Confirmed: read while you were in its system. Unconfirmed copies of the same planet filed
            # elsewhere (an earlier stale address with nothing to contradict it) are then dropped.
            stored["confirmed"] = (old or {}).get("confirmed", False) or system == current_system
            if stored["confirmed"]:
                for other in [k for k, v in self.planets.items() if k != key and not v.get("confirmed")
                              and v.get("name") == planet.get("name") and v.get("index") == planet.get("index")
                              and v.get("system") != system]:
                    del self.planets[other]
            if old is None and previous_name is None:
                new += 1
                moved += system != planet["system"]
            stored["first_seen"] = old.get("first_seen", now) if old else now
            stored["last_seen"] = now
            if old is None or {k: v for k, v in old.items() if k not in ("first_seen", "last_seen")} != \
                    {k: v for k, v in stored.items() if k not in ("first_seen", "last_seen")}:
                changed += 1
            self.planets[key] = stored
            names_at.setdefault(planet["ua"], set()).add(planet.get("name"))
            by_place[(system, planet.get("index"), planet.get("name"))] = key
            seen.setdefault(system, []).append(planet.get("name"))
        self.scans.append({"at": now, "system": current_system, "planets": len(planets), "new": new,
                           "changed": changed, "moved": moved, "renamed": renamed,
                           "systems": {f"{k:x}": names for k, names in seen.items()}})
        del self.scans[:-self.MAX_SCANS]
        return changed

    def record_economies(self, found: dict[int, dict], now: str, source: str | None = None) -> int:
        """Store star attributes read from memory; returns how many systems are new or changed. `source` says
        where they were read ("galaxy map": a star record traced through its planets' seeds, starmap.py)."""
        changed = 0
        for key, attrs in found.items():
            entry = {**attrs, "read_at": now, **({"source": source} if source else {})}
            old = self.economies.get(key)
            if old is None or {k: v for k, v in old.items() if k not in ("read_at", "source")} != attrs:
                changed += 1
            self.economies[key] = entry
        return changed

    def record_system_names(self, found: dict[int, str]) -> int:
        """Store generated system names read from memory; returns how many are new or changed. Names are kept
        once read: the game only caches the systems around you."""
        changed = 0
        for key, name in found.items():
            if self.system_names.get(key) != name:
                self.system_names[key] = name
                changed += 1
        return changed

    def systems(self) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for planet in self.planets.values():
            out.setdefault(planet.get("system", system_key(planet["ua"])), []).append(planet)
        for planets in out.values():
            planets.sort(key=lambda p: (p.get("index", 0), p.get("name") or ""))
        return out
