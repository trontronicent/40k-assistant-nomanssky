---
tags: [reference, stars, spectral class, planets, biomes, galaxy map]
---

# No Man's Sky Star Classes and Planet Classes

What the game means by a system's **spectral class** and by a planet's **class**, and which worlds a star
class generates. Sources are named per section: the game's own files (build 25732212, read 2026-10-21), a
measurement against a 2,673-planet save, and the community wikis where the files say nothing. Anything the
files do not confirm is marked as unconfirmed.

## Spectral Class Of A System

### Where does the game show a system's spectral class?
On the **galaxy map's analysis panel**, as "Class" plus the class string. The game's own text keys are
`GLXY_SPECTRAL` = "SPECTRAL" and `GLXY_ANALYSIS_SPECTRAL` = "Class %PROCSPEC%" (game files, read
2026-10-21). The class string is built at display time: neither the save file nor the galaxy map's star
record holds it. What is stored is the star **type** - one of five colours.

### What do the class letters mean?
| Star colour | Spectral class starts with | Hyperdrive upgrade needed | What is special about its planets |
|---|---|---|---|
| Yellow | F or G | none (base hyperdrive) | Lush worlds twice as likely as other types |
| Red | K or M | Cadmium Drive | red exotic worlds only here; lava worlds twice as likely |
| Green | E | Emeril Drive | green exotic worlds only here; swamp worlds twice as likely |
| Blue | O or B | Indium Drive | blue exotic worlds only here |
| Purple | X or Y | Atlantid Drive (Worlds Part II mission "In Stellar Multitudes") | the only star type whose world list includes water worlds |

The colour-to-drive column is from the game's own item descriptions (`HDRIVEBOOST1-4`: "rare-class red /
green / blue stellar bodies", "purple stellar bodies"). The **letters are not in the game files** - they are
the community's reading of the class strings the game displays (No Man's Sky wiki, NMS Discoveries wiki, read
2026-10-21). Treat them as a convention, not as a measured fact.

### What do the digit and the suffix mean?
The class string carries a digit 0-9 and sometimes a suffix such as `f`, `p` or `pf` (for example `G2f`,
`K3p`). Both are borrowed from real stellar classification, are rolled per system, and **no source confirms
any effect in play**. The community wikis disagree on whether the suffixes mean anything at all; only the
first letter, which is the colour, is known to matter - it decides which hyperdrive upgrade you need.

### Can the plugin show the full class string?
No. The plugin reads the star **type** out of the galaxy map's star record
(`GcGalaxyStarAttributesData.Type`) or predicts it from the generation rules, so it shows the colour and the
class letters of that colour. The digit and the suffix would have to be reproduced from the system seed, and
that derivation is not known.

## Which Worlds A Star Class Generates

### Where do the biome weights come from?
From the game's own table `METADATA/SIMULATION/SOLARSYSTEM/BIOMES/BIOMELISTPERSTARTYPE.MBIN`, decoded on
2026-10-21 into `research/star_classes.json` (seven rows of 2 x 17 weights: one row per star type in the
game's own order, plus two extra yellow rows for lush and for empty galaxies; each row holds the weights for
normal planets and for prime planets). A weight of 0 means the type is not in that star's list, 1 is
ordinary, 2 is twice as likely.

### Which planet types belong to which star class?
- The six ordinary types - **lush, toxic, scorched, irradiated, frozen, barren** - are generated at every
  star class, at weight 1, except that lush worlds weigh 2 at yellow stars and 4 in a lush galaxy.
- **Red, green and blue exotic worlds** occur only at a star of that colour (weight 1 as a normal planet, 3
  as a prime planet) - and, at a low weight (0.66), at purple stars.
- **Swamp and lava worlds** are generated as **prime planets** only: swamp at green stars (weight 2),
  yellow and blue stars (1); lava at red stars (2), yellow and blue stars (1). Purple stars are the
  exception - they carry both as ordinary planets too, at a low weight (0.2).
- **Water worlds** appear only in the purple star's list (weight 0.66).
- In an **empty galaxy** the yellow row raises dead worlds to weight 4; in a **lush galaxy** it raises lush
  worlds to 4 and drops dead worlds to 0.5. Harsh galaxies have no row of their own.

### How well does the table match a real save?
Measured on 2026-10-21 against 2,673 recorded planets of one save, 1,623 of them in systems whose star
record had been read (`research/star_classes.json`, section `save_cross_check`):

- Everything colour-specific agrees: red exotic worlds only at red stars (9 of 9), green only at green (20
  of 20), blue only at blue (22 of 22); swamp and lava worlds stay at ~2% (prime planets only); lush worlds
  are the most common type at yellow stars (19.9%).
- **Two slots disagree.** `Dead` carries weight 2 at every colour, yet **not one** of the 2,673 planets is a
  dead world. `Exotic` is weight 0 for yellow stars in a normal galaxy, yet 10% of the planets at yellow
  stars are exotic. Gas giants and water worlds are missing from the table altogether but do occur.
- So the generator decides dead and exotic worlds somewhere else than in this table, and the table should
  not be read as a complete account. The plugin's tooltips therefore never promise a dead or an exotic world
  from these weights.

## Planetary Class Of A Planet

### What is a planet's class?
Two things the game shows together. The **type name** the analysis visor and the discovery page give
("Noxious Planet", "Frozen Moon"), and the **size class** inside it: the game's own words are
`PLANETCLASS1` = "Planet", `PLANETCLASS2` = "Moon", `PLANETCLASS3` = "Planetoid" (game files, read
2026-10-21), substituted into the type name through the `%PLANETCLASS%` token. The plugin shows the type
name in the game's language next to English, and records the size class separately (Large, Medium, Small,
Moon, Giant).

### What else does a planet record hold?
The world type (biome), the weather, the sub-biome number (1-27, shared by all biomes), the resources, the
flora and fauna levels and the sentinel level. The world types themselves, with their own type names and
weathers in the game's language, are described in this library's one document per world type (airless,
barren, frozen, irradiated, lush, scorched, toxic, exotic, ocean, volcanic, swamp, gas giant).

### Does the star class change what is on a planet?
It changes **which types of planet are generated** (the table above), not what a given type is like: a
frozen world at a blue star has the same weather, resources and dangers as a frozen world at a yellow star.
What differs per star colour is the **stellar metal** you mine there (copper, cadmium, emeril, indium,
quartzite - see the resources reference) and, in a galaxy of another kind, the generation of planets as a
whole.
