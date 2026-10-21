# Companion egg timers — what the save and the game files hold

Measured 2026-10-21 on the real save (`save.hg` / `save2.hg`, 23 companions and 4 eggs) and the installed game
(Steam build 25732212). Supersedes the earlier claim in `pets.py` and `CLAUDE.md` that "the egg cooldown is not
in the game files": `gccreatureglobals.mbin` exists and lives in **`NMSARC.globals.pak`** (not in any hinted pak,
so a plain read opens nine paks before finding it).

## The save's three fields

| Field | On a **pet** | On an **egg** |
|---|---|---|
| `BirthTime` | when the companion was born or hatched | **when the egg was laid** |
| `LastEggTime` | **when it last produced an egg** | its **parent's** `BirthTime` |
| `Trust` | 0.60–0.85 across the roster | 0.70 on all four eggs |

An egg record is otherwise a copy of its parent's record (same seeds, traits, treats, battle record).

**How the two readings were pinned.** All four eggs in the save pair with a pet whose `BirthTime` equals the egg's
`LastEggTime`, and in each pair the pet's `LastEggTime` is 2–12 s before the egg's `BirthTime` — the game writes
both in the same action:

| Egg | laid (`BirthTime`) | parent's `LastEggTime` | gap |
|---|---|---|---|
| Cat (Wolverine) | 1792567712 | 1792567705 | 7 s |
| Cow (Unzy Bunzy Bowa) | 1791140250 | 1791140239 | 11 s |
| Protoroller (Strixy) | 1791575628 | 1791575626 | 2 s |
| Triceratops (Hidippo) | 1791582198 | 1791582194 | 4 s |

`LastTrustIncreaseTime` sits a few seconds before `LastEggTime` on both fresh pairs: the player fed the companion
and the egg followed.

## The constants

* **Hatching: 24 h after the egg was laid.** *Confirmed in the game by the player* (2026-10-21). The game's own
  strings are `UI_PET_EGG_DESC_NOT_READY` = "ready to hatch in [button]%TIME%." and `UI_PET_EGG_DESC_READY` =
  "ready to hatch!"; `UI_OPEN_PET_EGG_NOT_READY` = "EGG STILL DEVELOPING". Eggs do **not** hatch by themselves —
  three eggs in this save are 11–17 days old and still eggs.
* **First egg at 28 days old (2,419,200 s).** *Measured, strong.* Every pet younger than 28 days has
  `LastEggTime == BirthTime` exactly (two cases: 14.2 d and 0.08 d old). Every pet at or past 28 days that has
  never been milked for an egg has `LastEggTime == BirthTime + 2,419,200` **exactly** — 14 pets, ages 28.1 to
  47.7 days. The decisive one is an unnamed `^GRUNT` that crossed 28 days three hours before the save: it is
  stamped at birth + 28 d, not at "now", so the game computes the gate from `BirthTime` rather than from the
  moment it noticed. The game's refusal string is `UI_PET_EGG_COST_AGE` = "Too young to lay eggs".
* **Between two eggs: 14 days (1,209,600 s) — candidate, not confirmed.** It is the only other duration in
  `gccreatureglobals.mbin` (whose durations are int32: four `86400` at 0x1E90, 0x1EA4, 0x1F24, 0x1FC0, one
  `1209600` at 0x1EFC, plus a bare `28` at 0x24DC). An mbin carries no field names, so nothing in the file says
  which field is which; the plugin therefore labels this interval an estimate wherever it is shown. To settle it:
  with a companion whose `LastEggTime` is 14+ days old and which is fed and in its own climate, read whether the
  Companion panel says "ready to lay an egg" (`UI_EGGCARE_DETAIL_DESC`) or "Gestating…"
  (`UI_PET_EGG_COST_TIME`).

## What no save can tell you

The game's other refusals are runtime state: `UI_PET_EGG_COST_PENDING` "Another egg nearby",
`UI_PET_EGG_COST_SLOTS` "Cannot carry more eggs", `UI_PET_EGG_COST_HUNGRY` "Feeling hungry",
`UI_PET_EGG_COST_LONELY` "Feeling sad", `UI_PET_EGG_COST_BIOME` "Not in native climate",
`UI_PET_EGG_COST_TREAT` "Requires additional nutrition". Only the first is derivable (an egg of that parent is
still unhatched); the rest must be named to the player as possible reasons rather than silently ignored.

## One open anomaly

`^SPIDER` "Zushetto" had its `LastEggTime` set one hour before the save at an age of **13.5 days**, under the
28-day gate, and no Zushetto egg exists in the save. Its `LastTrustIncreaseTime` is 9 s earlier, so the player
had just fed it. Either feeding or harvesting a gift also stamps `LastEggTime`, or a path other than laying
writes it. Consequence for the plugin: `lay_at` takes the **later** of the age gate and the cooldown, so such a
record still reads "Too young" rather than promising an egg.
