# Pet battle tiers: what determines a companion's C/B/A/S

Status as of 2026-10-20. The machine-readable record is `pet_classes.json`; this file is the
readable account of what is settled, what is not, and how it was established. Codeword for this
line of work: **"pet feature"**.

## The answer, in one line

```
SpeciesSeed + GenusSeed  ->  PetBattlerSeed  ->  rolled against CoreStatClassRollTable  ->  C/B/A/S per stat
```

and that roll table weights **C, B and A equally at about 30% each, with S alone rare at about 7%**.
A single shared table rolls all three stats.

## What is settled

**The two inputs.** The tier is a joint function of `SpeciesSeed` and `GenusSeed`, and of nothing
else in the pet record. Established by writing pets into the save and reading the game's own
verdict back: clones of one donor taking a single field from another donor changed tiers only for
those two fields. `BoneScaleSeed`, `CreatureSecondarySeed`, `ColourBaseSeed`, `Descriptors`,
`CreatureID` and `Traits` were each eliminated individually.

**Neither input alone suffices.** Donor's own pair gives B/B/C; swapping only the species seed
gives B/A/B; only the genus seed gives C/C/A; both gives the source's S/S/S. So the two seeds are
not alternatives and neither dominates.

**The function is a mixed hash.** Single-bit flips of either seed avalanche: 8 flips moved 19 of 24
stat slots (79%, against 75% expected if a flip simply redrew every stat) and produced 8 distinct
triples. No bit's role can be isolated, so **probing cannot map the function** — that route is
closed, not merely unfinished.

**The mechanism is named.** From `NMS.exe`'s reflection strings: `PetBattlerSeed`,
`CoreStatClassRollTable`, `CoreStatClassRangeTable`, `CoreStatClassPerLevelBoosts`,
`CoreStatScaleVarianceMul`, `PetMaxLevel`. `PetBattlerSeed` is a serialised field of
`cGcGameTablePetData` but is **not** among the save pet struct's 35 keys, so for a wild creature it
is derived at runtime.

**The table's shape.** Uniform rolling is rejected (chi2 19.70 on 3 df at n=132, critical value
7.81). Equal-C/B/A-with-rare-S fits almost exactly: at n=132 the counts are C 40, B 42, A 39, S 11.

**One table rolls all three stats.** Homogeneity across combat, agility and health: chi2 4.76 on
6 df (critical 12.59) at n=36 per stat.

**Nothing outside the two seeds matters, tested jointly.** Two "noise" pets carrying randomised
`CreatureSeed`, `BoneScaleSeed`, `CreatureSecondarySeed`, `ColourBaseSeed`, `Scale`, `Traits`,
`Moods` and `Trust` read B/C/B and S/C/C — one of them rolled an S. This corroborates batch 2's
one-field-at-a-time eliminations jointly. **At n=6 symbols it is a sanity check, not a statistical
result**; cite it as reassurance that nothing is systematically broken, no more.

**Derived quantities** (unchanged from earlier work): `Overall = ceil((combat+agility+health)/3)`
with C=0, B=1, A=2, S=3; treats order is (Health, Agility, Combat Effectiveness), cap 10;
`size_m = round(Scale,1)` and `weight_kg = round(40*Scale,1)`. A tier is a **rate of return on
treats**, not a cap — which the existence of `CoreStatClassPerLevelBoosts` independently supports.

## What is not settled

**S's exact share — the single open parameter.** These candidate tables all fit the 78 chosen-input
symbols and are not distinguishable from each other:

S is **about 8%** [CI 4.7-14.3], down to two leading candidates. At n=132:

| table | S share | chi2 (3 df) |
|---|---|---|
| **4:4:4:1** | 7.7% | **0.19** |
| **3:3:3:1** | 10% | **0.53** |
| 5:5:5:1 | 6.25% | 1.09 |
| 7:7:7:3 | 12.5% | 2.22 |
| 6:6:6:1 | 5.3% | 2.61 |
| 2:2:2:1 | 14.3% | 3.94 |
| 8:8:8:1 | 4% | 6.57 (nearly rejected) |
| uniform | 25% | 19.70 REJECTED |

The low-S candidates are falling away and a no-S table is excluded outright (S has been observed 11
times). **Separating 3:3:3:1 from 4:4:4:1 would need several hundred more symbols** — far beyond what
the oracle supplies at 9 pets per load. Treat S as ~8% and stop measuring.

**Patterns in the data (2026-10-21).** Three groups of natural pets share a seed pair, and all three
have identical tiers — about a 1-in-75,000 coincidence otherwise, so the pair is the whole input. A
pet's three stats behave as independent draws (triple shapes and Overall match independent rolling;
no pairwise correlation beyond noise). No simple arithmetic of the seeds (mod 10/13, nibbles, xor/sum,
popcount) tracks any stat. Together: a function of the pair seeds an RNG that draws three times
against one weighted table.

**That model was then searched directly and failed.** 368,640 seeded-RNG constructions — ten
combiners, eight RNGs including xorshift128+/xoroshiro128+ seeded with the pair, weighted 3:3:3:1 and
4:4:4:1 tables, skipped draws, every stat and tier order — scored at best 77 of 186 symbols, squarely
inside the 74-79 that the same search finds on shuffled labels. The game's construction is outside
every standard family.

**The function itself.** Predicting a *specific* creature's tiers from its scanned seeds remains
impossible. Probing is closed, and the roll table is compiled into `NMS.exe` — every shipped archive
was checked (all ~95 NMSARC paks' manifests read, `audio.pak` excepted) and none contains a
core-stat table. The only pet-battler data files in the game are UI textures and
`metadata/simulation/gametables/petbattler/petbattlermoves(set)stable.mbin`, i.e. moves, not stats.
Recovering the function would need static analysis of the binary.

**Why a lookup cache cannot substitute.** `SpeciesSeed` is distinct across all 524 Animal discovery
records, so every creature has a unique seed pair. A table of observed pairs would never hit twice.

## What this is good for

For an unscanned or unTamed creature the correct prior is now known, which answers "is this worth
taming":

- about **38%** chance a given stat is A or better
- a **triple-S** creature is roughly **1 in 1,700** at S=8.3%, the CI spanning about 1 in 350 to
  1 in 9,600

## Selection bias — read this before using any frequency

The 21 tamed pets were chosen by hunting for the best ones. They show S at **33%** against a natural
**7.4%**: a 4x over-representation created entirely by the player's selection. **Never derive
frequencies from the tamed pets.** Distributional claims come only from chosen-input oracle batches,
where the seeds were picked by us.

This is also the retrospective verdict on the hunting: it worked, and measurably so.

## Method: the save oracle

Observation alone got this wrong for a day. `BoneScaleSeed` is byte-identical to `CreatureSeed` in
**21 of 21** natural pets, so the two are perfectly confounded observationally, and the apparently
decisive pair of pets shared both. The earlier conclusion "the tier is a function of `CreatureSeed`
alone" was **falsified by experiment** and is retained in `pet_classes.json` as superseded rather
than deleted.

Converting the problem from observation to experiment answered in three game loads what 21
observations had got backwards. Write pets into the free save slots with chosen seeds, load, read
the game's own tier display back.

### Procedure, including the parts that cost us a load

- Build each batch from the **newest** save, so the session's progress is not rolled back.
- **A running game destroys the write.** Batch 4's install landed at 12:14 and the game overwrote it
  at 12:16. Copy only with the game fully closed, then launch.
- **Both `save.hg` and `save2.hg` are loadable entries.** Installing to one only means the player may
  load the other and read stale pets. Copy to both, and verify the test pet names in game before
  reading any values.
- Each test pet is a `deepcopy` of a live pet with fields overwritten — never a hand-built dict (the
  struct has 35 keys, and an empty slot carries the same key set). Give each a distinct `BirthTime`.
- Always include a control, or names that prove installation. A plain clone of the donor reproducing
  the donor's tiers is what makes a negative result trustworthy; `testCTRL`, `testCTRL2` and
  `testCTRL3` each did so.
- **Exclude any tamed pet from distributional statistics**, including a control that is a real pet.
  `testCTRL3` is the donor himself and carries the player's bias.
- Judge batches by the homogeneity test, not by eye: batch 4 (A 15%) and batch 5 (A 44%) looked
  wildly different, but chi2 across three batches is 10.53 on 6 df (critical 12.59) — consistent.
- Readings are **(combat, agility, health)**; Overall is derived, not read. This is provable rather
  than assumed: a C Overall requires all three stats to be C, so readings like `c,b,b` and `c,s,b`
  rule out any Overall-first interpretation.
- The game **normalises nothing** on load: what is written is what is used.

## Statistical discipline

**A nine-pet batch is three looks at three stats**, so it throws up a nominally significant pattern
roughly one time in four by chance. Batch 6's agility read C in 6 of 9 (binomial p = 0.032) and
looked like a low-weighted agility stat; pooled, agility's C rate is 40.7% [24.5-59.3] against a
34.6% overall rate, and the per-stat homogeneity test is clean. Check such dips, but expect them,
and do not re-chase this one.

A blind bit-field search over the seeds drowns in multiple comparisons — shuffled-label controls won
90-93% of the time, so such hits were correctly rejected. Route 2 (standard hash constructions) was
likewise a clean negative: the best of 134,400 constructions scored 43 of 90 symbols (47.8%) against
a 25% chance baseline, which is ~5 sigma on a single test but sits at the top of a smooth
multiplicity tail where the expected maximum is already ~4.5 sigma. A correct construction would
score at or near 90/90.

That search failed for a *structural* reason worth remembering: it assumed three uniform 2-bit
fields plus a permutation, i.e. every tier equally likely. A weighted roll table is not in that
space, so the true function was never a candidate.

A **named** hypothesis, by contrast, carries no multiplicity at all.

## Supporting work: the HGPAK v2 extractor

The game's archives use an undocumented `HGPAK` format. A complete working description is in
`pet_classes.json` under `hgpak_format`, with the extractor kept at
`J:/nms-save-backups/oracle-batches/hgpak5.py`. Validated by extracting every shipped pak, including
49,948 files from `NMSARC.MetadataEtc.pak`.

The two non-obvious parts: file-table offsets index the **decompressed** stream, and **file 0 is a
plaintext manifest naming all the other files** — which is why a raw ASCII scan of a `.pak` finds
nothing readable. The per-chunk size table proved unreliable (shifted by one); take frame boundaries
by scanning for the zstd magic `28 B5 2F FD` instead, whose count matched the header's chunk count in
every archive tested.

## Files

| what | where |
|---|---|
| machine-readable record | `research/pet_classes.json` |
| batch builders, plans, saves, analysis | `J:/nms-save-backups/oracle-batches/` |
| verified backup of the real save | `J:/nms-save-backups/2026-10-20_095912_pre-test-pets/` (+ `checksums_*.md5`) |
| game install | `J:/SteamLibrary/steamapps/common/No Man's Sky` (the `F:` copy is a stale 2023 one with no PCBANKS) |

Test pet naming: `W` = batch 4, `X` = batch 5. Nine test pets currently occupy slots 18-23 and
27-29; they can be deleted in game to reclaim the slots, or overwritten by the next batch.

## Next steps

1. ~~Pin S's share~~ — **done to the limit of this method** at n=132. Further loads cannot separate
   3:3:3:1 from 4:4:4:1; stop here.
3. **Static analysis of `NMS.exe`** for the compiled-in `CoreStatClassRollTable` default, and for the
   function deriving `PetBattlerSeed`. Now a well-posed search: the inputs are known.
4. **Unspent experiment**: set `PetBattlerUseCoreStatClassOverrides` true with `[S,S,S]` to find out
   what that inert save field actually does.
5. **Scan-then-tame validation** — confirm scanner tiers equal companion tiers before pooling
   `scanned_readings` with `observations`.
