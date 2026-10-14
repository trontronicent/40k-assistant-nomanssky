"""Which guild's envoy a space station holds (pure).

Every inhabited space station has an envoy of one guild - Merchants, Explorers or Mercenaries -
who hands out free rewards at the right standing. Which guild it is is **region-specific**: the
systems of one voxel region share it, so recording it once answers it for every system of that
region (community finding; nomansskyresources.com/guilds, and the Steam discussions behind it).

It is not in the game's data. A pass over every pak on 2026-10-14 (build 25732212) found the
``guildshop`` models, the three guilds' UI icons (``tradeguild``, ``explorerguild``,
``warriorguild``) and their textures - and no table that maps an economy, a race or anything else
to a guild. The running game's memory was not searched for it yet; the state of that research is
in ``research/guilds.json``.

So the user records what the station showed (one action), and every known system of that region
is answered from it, marked as inferred when the record came from a sibling system.
"""

from __future__ import annotations

from . import galaxy

#: Guild id -> the name the game uses. ``none`` is a real answer: a region can hold no envoy.
GUILD_NAMES = {
    "merchants": "Merchants Guild",
    "explorers": "Explorers Guild",
    "mercenaries": "Mercenaries Guild",
    "none": "No envoy here",
}


def region_id(key: int) -> str:
    """'3, -2, 17' - the voxel region of a system key, the id a guild record is filed under."""
    return ", ".join(str(v) for v in galaxy.region(key))


def with_record(guilds: dict, key: int, guild: str, now: str) -> dict:
    """A copy of the records with this system's region set to this guild. Unknown guild -> unchanged.

    The newest naming wins: a region holds one guild, and a user correcting an earlier mistake must
    not have to delete anything first."""
    if guild not in GUILD_NAMES:
        return dict(guilds)
    return {**guilds, region_id(key): {"guild": guild, "system": f"{key:x}", "at": now}}


def for_system(guilds: dict, key: int) -> dict | None:
    """What is known about this system's guild envoy, or None when its region holds no record.

    ``inferred`` is True when the record was made in another system of the same region - the guild
    is the region's, so that is an answer, just not one read at this station."""
    entry = (guilds or {}).get(region_id(key))
    if not isinstance(entry, dict) or entry.get("guild") not in GUILD_NAMES:
        return None
    return {**entry, "name": GUILD_NAMES[entry["guild"]], "inferred": entry.get("system") != f"{key:x}"}


def text(entry: dict | None, label_of=None) -> str | None:
    """'Merchants Guild - recorded in this region, at Ulebsk' for a system's details panel.

    None when nothing is recorded, so the caller can say what to do instead."""
    if not entry:
        return None
    if not entry.get("inferred"):
        return f"{entry['name']} - recorded here"
    where = None
    if label_of is not None:
        try:
            where = label_of(int(str(entry.get("system")), 16))
        except (TypeError, ValueError):
            where = None
    return f"{entry['name']} - recorded in this region" + (f", at {where}" if where else "")


def cell(entry: dict | None) -> str | None:
    """'Merchants Guild' / 'Merchants Guild (region)' for a table cell, None when unknown."""
    if not entry:
        return None
    return entry["name"] + (" (region)" if entry.get("inferred") else "")


def options() -> list[dict]:
    """The select options of the recording form, in the order the station's UI lists the guilds."""
    return [{"value": guild, "label": name} for guild, name in GUILD_NAMES.items()]
