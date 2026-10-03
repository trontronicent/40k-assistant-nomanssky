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

HISTORY_VERSION = 1
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


class PlanetHistory:
    """Planets read from memory, by packed planet address; persisted as JSON."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.planets: dict[int, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if raw.get("version") == HISTORY_VERSION and isinstance(raw.get("planets"), dict):
            self.planets = {int(k): v for k, v in raw["planets"].items() if isinstance(v, dict)}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": HISTORY_VERSION, "planets": {str(k): v for k, v in self.planets.items()}},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def record(self, planets: list[dict], now: str) -> int:
        """Merge planets read from memory; returns how many are new or changed."""
        changed = 0
        for planet in planets:
            key = planet["ua"]
            old = self.planets.get(key)
            stored = {k: v for k, v in planet.items() if k not in ("ua",)}
            stored["first_seen"] = old.get("first_seen", now) if old else now
            stored["last_seen"] = now
            if old is None or {k: v for k, v in old.items() if k not in ("first_seen", "last_seen")} != \
                    {k: v for k, v in stored.items() if k not in ("first_seen", "last_seen")}:
                changed += 1
            self.planets[key] = stored
        return changed

    def systems(self) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for key, planet in self.planets.items():
            out.setdefault(planet.get("system", system_key(key)), []).append(planet)
        for planets in out.values():
            planets.sort(key=lambda p: p.get("index", 0))
        return out
