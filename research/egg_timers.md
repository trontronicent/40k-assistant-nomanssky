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
* **There is no 28-day age gate — the pattern is real, its meaning is not known.** 13 pets carry
  `LastEggTime == BirthTime + 2,419,200` (28.0000 d) *to the second*, and the split looked decisive: all 13 are
  older than 28 days, both pets younger than 28 days have `LastEggTime == BirthTime`, and an unnamed `^GRUNT` that
  crossed 28 days four hours before a save was stamped at birth + 28 d rather than at "now" — so the game does
  compute that value from `BirthTime`. It was first read as "a companion lays its first egg at 28 days old", and
  the game does have the refusal `UI_PET_EGG_COST_AGE` "Too young to lay eggs".

  **It is wrong.** The player's `^SPIDER` "Zushetto" produced an egg at **13.4 days old** — it carries a real
  `LastEggTime` from that moment and no egg in the save matches it, because the player gave that egg to another
  player. Whatever the game writes at 28 days, it is not a precondition for laying, and no row may show "too
  young" because of it. Candidates worth testing: an adulthood or growth milestone, or a one-off write when a
  companion is first summoned after that age.

  Consequence for the plugin: `lay_at` is simply `LastEggTime + 24 h`. A companion that never laid carries its
  birth time in the field and so reads ready 24 h after birth, which happens to be what a 1-day age gate would
  give — and `86400` is one of the four durations in the globals file.
* **Between two eggs: 24 h.** *Confirmed in the game by the player* (2026-10-21): right after Hidippo laid, the
  game said the next egg induction can be started in 24 h. This is one of the four `86400` ints in
  `gccreatureglobals.mbin` (0x1E90, 0x1EA4, 0x1F24, 0x1FC0). The earlier guess of 14 days — its `1209600` at
  0x1EFC, plus a bare `28` at 0x24DC — was **wrong**; that constant belongs to something else. An mbin carries no
  field names, which is why a save-side reading or an in-game check decides, never the file alone. Nearly every
  mature companion in the save is therefore *ready* at any time: the interval is short and an egg has to be
  induced by the player, so "ready" means "go and induce one", not "an egg is waiting".
* **An unhatched egg does not block the next one.** *Measured 2026-10-21*: Hidippo laid a second Triceratops egg
  while its first, eleven days old, was still in the player's hands — the save then held two eggs whose
  `LastEggTime` both point at Hidippo's `BirthTime`. So `UI_PET_EGG_COST_PENDING` "Another egg nearby" is about
  an egg lying in the world, not one in the player's inventory, and nothing may suppress a companion's countdown
  because it already has an egg out. `parent_of` is many eggs to one pet.

## What no save can tell you

The game's other refusals are runtime state: `UI_PET_EGG_COST_PENDING` "Another egg nearby",
`UI_PET_EGG_COST_SLOTS` "Cannot carry more eggs", `UI_PET_EGG_COST_HUNGRY` "Feeling hungry",
`UI_PET_EGG_COST_LONELY` "Feeling sad", `UI_PET_EGG_COST_BIOME` "Not in native climate",
`UI_PET_EGG_COST_TREAT` "Requires additional nutrition". None of them is derivable from a save — the first one is about the world, not the player's eggs — so they must
be named to the player as possible reasons rather than silently ignored.

## Resolved: the egg with no egg

`^SPIDER` "Zushetto" had a `LastEggTime` from an hour before the save with no matching egg anywhere in it. The
player resolved it: **that egg was given to another player.** An egg handed over leaves the save while the
parent's timestamp stays, so a `LastEggTime` without a matching egg is normal and means nothing is wrong. It is
also the reading that disproved the 28-day gate above, since Zushetto was 13.4 days old at the time. (Eggs
carry `SenderData` — `LID`/`UID`/`USN`/`PTK`/`TS`, empty on all of this save's own eggs — which is how a
*received* egg records who sent it; the game has `UI_PET_EGG_DESC_GIFT` for that case.)

The open point is narrower now, and it is the same stamp: a companion stamped at birth + 28 d within the last
24 h reads "in 19 h", because `lay_at` treats every stamp as a last egg. If that write is only a milestone, such
a companion is ready the moment it turns 28 days old. It affects one companion for one day at a time — the
unnamed `^GRUNT` (28.17 d old, stamped four hours before the save) is the case to read in game.
