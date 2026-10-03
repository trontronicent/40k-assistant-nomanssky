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


def planet_id(planet: dict) -> str:
    """Identity of a recorded planet: the address its record carried plus its name.

    The address alone is not enough: when the game reuses a planet slot for the
    next system, the record can keep the previous planet's address (seen
    2026-10-03: after a warp every planet of the old system was replaced by one
    of the new system). Generated names are fixed per planet, so two records
    with one address and different names are two planets.
    """
    return f"{planet['ua']:x}:{planet.get('name') or '?'}"


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
        self.load()

    def load(self) -> None:
        for path in (self.path, self.path.with_suffix(".json.bak")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
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
            else:
                continue
            return

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": HISTORY_VERSION, "planets": self.planets, "scans": self.scans},
                                  ensure_ascii=False), encoding="utf-8")
        if self.path.exists():
            self.path.replace(self.path.with_suffix(".json.bak"))
        tmp.replace(self.path)

    def record(self, planets: list[dict], now: str, current_system: int | None = None) -> int:
        """Merge planets read from memory; returns how many are new or changed. Logs the scan."""
        changed = new = moved = 0
        names_at = {}                                   # address -> names already recorded there
        for stored in self.planets.values():
            names_at.setdefault(stored["ua"], set()).add(stored.get("name"))
        by_place = {(v.get("system"), v.get("index"), v.get("name")): k for k, v in self.planets.items()}
        seen: dict[int, list[str]] = {}
        for planet in planets:
            stored = {k: v for k, v in planet.items()}
            known = self.planets.get(planet_id(planet))
            system = planet["system"]
            if known is not None:
                system = known.get("system", system)    # seen before: stays where it was filed
            elif current_system is not None and system != current_system \
                    and names_at.get(planet["ua"], set()) - {planet.get("name")}:
                system = current_system                 # stale address: another planet owns it
            stored["system"] = system
            key = by_place.get((system, planet.get("index"), planet.get("name"))) or planet_id(planet)
            old = self.planets.get(key)
            # Confirmed: read while you were in its system. Unconfirmed copies of the same planet filed
            # elsewhere (an earlier stale address with nothing to contradict it) are then dropped.
            stored["confirmed"] = (old or {}).get("confirmed", False) or system == current_system
            if stored["confirmed"]:
                for other in [k for k, v in self.planets.items() if k != key and not v.get("confirmed")
                              and v.get("name") == planet.get("name") and v.get("index") == planet.get("index")
                              and v.get("system") != system]:
                    del self.planets[other]
            if old is None:
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
                           "changed": changed, "moved": moved,
                           "systems": {f"{k:x}": names for k, names in seen.items()}})
        del self.scans[:-self.MAX_SCANS]
        return changed

    def systems(self) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for planet in self.planets.values():
            out.setdefault(planet.get("system", system_key(planet["ua"])), []).append(planet)
        for planets in out.values():
            planets.sort(key=lambda p: (p.get("index", 0), p.get("name") or ""))
        return out
