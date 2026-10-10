---
tags: [companions, pets, creature battles, xeno arena, holo-arena, abilities, affinity, traits, eggs, guide]
language: en
---

# No Man's Sky Companions and Creature Battles

How companions (pets) behave while you explore, and how Creature Battles (the Xeno Arena / Holo-Arena) work: the
three battle stats, the nine affinities, the ability types, and what is not known.

**How this was checked (2026-10-10):** the official Xeno Arena update page and the Cosmos 7.0 page on nomanssky.com;
guides from TheGamer, GameRant, KeenGamer, PlayerAuctions and dtgre; player reports on Steam; and the **installed
game's own files** (build 25732212, Cosmos 7.04/7.05) and a real save. Labels used below: **(official)** = quoted
from Hello Games; **(game files)** = read from the installed game; **(save)** = seen in a real save; **(two sources)**
= found in at least two independent guides; **(single source)** = one source only; **(unconfirmed)** = said by
players, could not be checked; **(disputed)** = sources disagree. The battle system arrived with the **Xeno Arena
update (6.3, April 2026)**; the Cosmos 7.0 notes (September 2026) contain no creature-battle changes, so the 6.3
rules are assumed to still hold **(presumed)**.

## Companions while you explore

- **Three trait pairs, each a percentage** **(two sources)**: industriousness (helpful or playful), aggressiveness
  (gentle or aggressive), independence (devoted or independent). A companion has only one side of each pair. A save
  stores exactly three signed numbers per companion **(save)**, which fits; which number is which pair, and what the
  sign means, is **(unconfirmed)**. Independence is said to decide how far and how often a companion wanders
  **(single source)**.
- **What they do** **(two sources)**: scout and point you to unscanned wildlife and distress signals, mark points of
  interest, dig up and fetch resources, scan, leave harvestable droppings, warn of hazards, hunt on command and ward
  off predators. Which of these a given animal does depends on its traits. You cannot command their actions
  directly; the quick menu calls them to you.
- **Is it worth it?** **(disputed)** One long Steam thread says "pets don't do anything useful"; others reply that
  some animals reliably fetch things. Treat the usefulness as varying by animal.
- **Harvest** **(game files)**: every creature type has its own harvest text and product in the game's language
  files, for example a cow gives *Fresh Milk* (and *Raw Steak* as meat). The Companions tab of the plugin lists each
  of your companions' harvest. Milk-type products are cooking ingredients.
- **Riding** **(two sources)**: some companions can be ridden. They have a stamina meter, cannot jump, you cannot use
  your mining laser while riding (the visor works), and riding does not protect you from damage. One player says
  sentinels ignore you while mounted **(single source)**.
- **Equipment** **(single source)**: armour, torch, laser, cargo pack or satellite change what a companion can do; a
  laser lets it fight small attackers.
- **Trust** **(game files / save)**: a companion has a trust value from 0 to 1. A hatched egg starts at 0.7 and an
  adopted wild animal around 0.6 **(single source, matches the 0.70 seen on eggs in a save)**. Feeding and care raise
  it **(single source)**.
- **Changing a companion** **(official)**: the Egg Sequencer on the Space Anomaly changes genetics, and since the Xeno
  Arena update it can upgrade the agility, health and battle traits.

## Creature Battles: the basics

- **3 against 3, turn based** **(two sources)**; one creature of your team is active at a time, and you may swap the
  active creature on your turn to use a type advantage.
- **Five abilities per creature**, one chosen per turn; stronger moves have a cooldown **(two sources)**. Each
  creature has its own set, influenced by its species and its home climate **(official)**. A creature's abilities
  are stored in the save as five template ids, for example `ATTACK_DUST` ("Direct damage of one affinity")
  **(save, game files)**.
- **Turn order** follows **Agility**: the creature with the higher Agility acts first **(two sources)**. Agility also
  affects the chance that an opponent's attack misses **(single source)**.
- **Holo-Arena** tables were added to the Space Anomaly **(official)**. The game also has an *Arena League*: the local
  champion of a system can invite you to a battle, and your wins are counted as *Holo-Arena Victories*
  **(game files)**. The standing tiers the game names are *Untested*, *Station Champion* and *Stellar Phenomenon*
  **(game files)**.
- **Wild creatures show their potential:** the binocular scan of a wild creature shows *Trait Potential*, and a
  tamed one shows *Battle Abilities* **(game files)**.

## The three battle stats

Each creature has three stats, each with a class **S, A, B or C** (the class sets how high the stat can go; weak
classes cannot become top tier) **(single source)**:

| Stat | What it does |
|---|---|
| **Combat Effectiveness** | raw damage of offensive abilities **(game files, two sources)** |
| **Health** | damage the creature can take before the next one steps in |
| **Agility** | turn order, and the chance to be missed |

Moves can also change four more stats during a fight: **accuracy, critical hit chance, dodge chance and defensive
strength** **(game files)**. A save stores the three classes in the order Combat Effectiveness, Health, Agility
**(save)**.

## The nine affinities

Physical, Fire, Frost, Tropical, Desert, Toxic, Radioactive, Mechanical and Anomalous **(game files)**.

**Who is strong against whom is not in the game files** (there is no affinity table among them; the rules live in
the program), so this comes from guides. Two internally consistent cycles are described by two guides
**(two sources)**:

- **Fire -> Frost -> Desert -> Radioactive -> Fire** (each is strong against the next one)
- **Toxic -> Tropical -> Anomalous -> Mechanical -> Toxic**
- **Physical** is neutral.

**(disputed)** One published table also lists *Radioactive weak to Toxic* and *Anomalous weak to Desert*. Those two
entries cross from one cycle into the other, do not fit the reciprocal pattern of the other six, and the same guide
warns that cross-cycle matchups are less predictable. Treat cross-cycle effectiveness as **unconfirmed** and test
it in the arena.

A move of the wrong affinity is shown as *Ineffective* in the ability description, a good match as *Strong*
**(game files)**.

## Ability types

The game's table of 61 ability templates **(game files)** groups them like this:

- **Attacks:** a plain attack, a fixed-affinity attack for each affinity, and attacks of the creature's own
  affinity (single hit, barrage, multi-hit, ramp that strengthens with each use, charge-up, delayed).
- **Damage over time:** damage every turn, a bomb that explodes later, an attack that also leaves a burn.
- **Healing and defence:** heal, heal over time, shield, reflect, absorb (turn incoming damage into health), team
  versions of these.
- **Buffs and debuffs:** raise your damage, accuracy, critical chance, speed or dodge; lower the enemy's damage,
  accuracy or defence.
- **Control:** stun (the target cannot act), dispel (remove the opponent's buffs or your own debuffs), reset your
  cooldowns, change affinity.
- **Special:** burrow, enrage (more damage or critical chance for a cost), sacrifice, revive, and a few moves that
  appear to belong to champion fights only.

## Strategy that two or more guides agree on

- **Speed decides a lot** **(two sources)**: the creature that acts first can stun or buff before the other moves,
  so a high Agility class is valuable. Stuns and buff removal are strong utility.
- **Build a team with different affinities** **(two sources)** and swap to the one that is strong against the active
  opponent, rather than leading with your best creature every time.
- **Mind the cooldowns** **(two sources)**: a strong move is not available every turn; plan the turn before.
- **Anomalous creatures** are praised for unusual status effects and buff removal, and **Radioactive** creatures with
  high Health as anchors against Fire **(single source, an early April 2026 tier list; the meta may have changed)**.

## What is not known

- The exact effectiveness numbers and the cross-cycle matchups (see above).
- What the three trait numbers mean, and which sign is which side of a pair.
- How long a companion's egg takes to be ready again (the game files hold no constant).
- The species name the game shows for a creature: it is generated from the creature's seeds and is not in any text
  table, so the plugin shows none rather than guessing.
- Whether a Cosmos-era patch changed battle balance (an unconfirmed report mentions an experimental-branch fix for
  creatures surviving too long).

## Sources

Official: nomanssky.com Xeno Arena update; nomanssky.com Cosmos. Guides: TheGamer (creature battles, companions),
GameRant (Holo-Arena), KeenGamer (companions), PlayerAuctions (affinities), dtgre (6.3 meta guide). Player reports:
Steam discussions "Functions of companions?" and "Pet traits?". Game files and save: read from the player's own
installation and save; nothing is copied from them into this document except the ability and stat names.
