# Experimental features and the savegame editor

Date: 2026-10-20
Plugin: `nomanssky` (No Man's Sky)
Status: approved design, not yet implemented

## Goal

Add the plugin's first *experimental* feature: a savegame editor that can change inventory
and technology slots in a No Man's Sky save. Experimental features are off by default and
must be switched on in the plugin's own Settings tab. Every write backs the save up first
and is validated before and after it is written.

Scope decided with the user: **all containers**, **substances, products and technology**,
staged changes with a review step, backup plus read-back verification plus a restore list.

## Two findings that shape the design

### The de-obfuscated tree cannot be written back

`saves.decode_bytes` decodes the decompressed JSON with `errors="replace"`. The save
genuinely contains strings that are not UTF-8, so that decode is **lossy** - harmless for
reading, fatal for a round trip. `saves.deobfuscate` is also not invertible: unknown keys
keep their obfuscated name, and nothing guarantees that the values in `mapping.json` are
unique.

Therefore the editor **edits the raw, obfuscated tree and never re-obfuscates**. The
mapping is used in one direction only, to translate a readable path into an obfuscated
path. `saves.py` stays read-only and untouched, as its docstring promises, so every
existing caller and test keeps the code it has today.

### `mf_*.hg` is opaque, and does not bind the save (settled 2026-10-20)

`mf_save.hg` is 432 bytes with no magic and high entropy (encrypted metadata). Whether the
game validates `save.hg` against it could not be determined by reading, so it was settled by
experiment: `save3.hg` was rewritten through this module with one edited value and
`mf_save3.hg` deliberately left stale, and the game **loaded it and showed the edited
value**. So the editor writes `save*.hg` only and never touches `mf_*.hg`.

## Modules

### `nms_connector/lz4.py` - `compress_block(data) -> bytes`

A greedy single-candidate matcher over a hash table of 4-byte sequences. A literals-only
encoder was tried first - correct by construction, no match finding - but measured **4.1x**
the game's own file size on the real saves (1,435,843 -> 5,561,391 bytes), which is a real
regression for the player's disk and their Steam Cloud quota. The matcher gives **0.95x**
the game's size at 0.47 s per save, payload byte-identical.

The format's end rules are honoured, because the game's decompressor is real LZ4 and may
reject what this module's lenient `decompress_block` accepts: the last sequence is literals
only and no match starts in the final 12 bytes. `tests/test_save_write.py` carries an
independent strict reader (`strict_block_problem`) that is itself proved to reject a
malformed block, and every chunk of every real save passes it (34 chunks, 0 malformed).

### `nms_connector/save_write.py` - the only module that writes a save

- `read_raw(path) -> RawSave` - the obfuscated tree plus what is needed to put it back
  byte-faithfully: the JSON text decoded with `errors="surrogateescape"`, and the trailing
  NUL padding that `decode_bytes` strips.
- `encode_bytes(json_text, tail) -> bytes` - chunk into 512 KiB pieces, each with a
  `<MAGIC, csize, usize, 0>` header, restoring the original tail exactly.
- `write_save(path, raw_save)` - temp file plus `os.replace`.
- `obfuscated_path(readable_path, mapping)` - readable key names to obfuscated ones;
  raises when a name is unknown or ambiguous.

### `nms_connector/save_edit.py` - pure, no I/O

`Change` dataclass: `container` (`exosuit`, `exosuit:tech`, `ship:<n>`, `ship:<n>:tech`,
`multitool:<n>`, `freighter`, `freighter:tech`, `chest:<n>`, and the other keys
`summary.OTHER_STORAGE` already enumerates), `slot` (x, y), `op`
(`set_amount` | `add` | `remove`), `item_id`, `amount`.

`validate(change, raw_tree, catalogue) -> str | None` returns why a change was refused, the
idiom `PluginSettings.update` already uses. It checks:

- the container exists in this save;
- the slot is in that container's own `ValidSlotIndices`, so a slot the player has not
  bought is never written;
- the slot's type matches the item's type (substance, product, technology);
- `item_id` exists in the catalogue read from the installed game (`gamedata` / `hgpak`);
- the amount is within `1..stack cap` for that item and container kind;
- `add` targets an empty slot; `remove` and `set_amount` target a filled one.

`apply(raw_tree, changes) -> (new_tree, report)` is pure. A technology entry is edited in
place, preserving every field the editor does not own (damage, install state, upgrade
seed), so a tech edit changes the id and amount and nothing else.

Pending changes live in `ctx.data_dir/editor/pending.json`, keyed by save directory and
save number, so a changeset survives the standalone page's 5 s poll and a restart.

## Commit pipeline

`save_edit.commit`, in order, aborting on the first failure with nothing written:

1. the experimental master switch and `save_editor` are both on (re-checked server-side);
2. No Man's Sky is not running **at all** - not merely "not in that save". Measured
   2026-10-20: two writes were destroyed within minutes by a running game, one of them
   while it sat at the main menu. A live game owns its save files and rewrites them from
   memory whenever it chooses;
3. `mapping.json` is present;
4. the save's mtime and size still match what they were when the changeset was staged - if
   the game saved in the meantime the changeset is discarded rather than applied to a tree
   it was never validated against;
5. every change is re-validated against the tree as it is now;
6. backup: `save*.hg` and `mf_*.hg` copied to
   `ctx.data_dir/editor/backups/<iso-timestamp>/`, the last 10 kept;
7. `apply`, then `encode_bytes`, then temp plus `os.replace`;
8. read-back: the written file is decoded again and the tree compared with the intended
   tree;
9. on any failure in step 7 or 8 the backup is restored and the failure reported.

The save on disk is therefore only ever the old one or a verified new one. Read-back catches
the editor's own bugs; the restore list catches the game's opinion, which read-back cannot.

## Gating

`settings.json` grows:

```json
"experimental": {"enabled": false, "features": {"save_editor": false}}
```

Both default off, both driven through the existing `PluginSettings.SWITCHES` /
`set_switch` path so the Settings form and the app overlay stay in sync. The master
toggle's hint carries the warning; the per-feature toggle is refused while the master is
off. The editor tab and all its actions are **absent** from the view unless both are on,
and `action()` re-checks every write - a stale page cannot POST after the switch goes off.

The manifest gains a `write-game-files` permission, so the app's permission list, manifest
schema and trust copy change in the same commit and `app.min_version` rises to that app
version. The standalone host does not enforce permissions and needs only the settings
panel.

## UI

A new `Editor` tab built from existing section types only (`tabs`, `table`, `form`,
`notice`), so no new type has to be added to `standalone/context.SECTION_TYPES` or
`standalone/web/sections.js`:

- a notice: experimental, and the game must be closed;
- a save-slot picker that names the two files per slot the way the game's own load screen
  does - **Automatic Save** (the newer file) and **Restore Point** (the older) with their
  timestamps - never "save 3 / save 4". A slot is a pair of *generations*, not an automatic
  and a manual save;
- per-container sub-tabs with the slot table (item, amount, type, slot), drawn from the
  existing summary code;
- a *Change a slot* form, action `stage_change`;
- the pending-changes table with a per-row remove, and `commit_changes` /
  `discard_changes`; commit is marked destructive so both hosts ask for confirmation;
- a backups table with `restore_backup`.

## Correctness gates

Before any UI is built:

- a test that takes the real saves (via `NMS_SAVE_DIR`) and committed fixtures, runs
  `read_raw` then `encode_bytes` with **zero edits**, and asserts the result decodes to a
  byte-identical JSON text;
- a manual gate the user drives, **passed 2026-10-20**: `save3.hg` (the Season slot) was
  rewritten with units 21,200 -> 123,456, `mf_save3.hg` left stale, and the game loaded it
  and showed 123,456 units.

  A *no-op* re-encode was tried first and proved nothing: the two files in a slot hold
  near-identical states, so "it loaded fine" looks the same whichever of the pair the game
  read. A gate for a write path needs an observable difference in the written file.

## Tests

Plugin repo only; the app suite runs only for the app-side permission change.

- `compress_block` round trip against `decompress_block`, including sizes that cross the
  512 KiB chunk boundary and the extended-length path;
- the no-op re-encode, on fixtures and on the real saves when present;
- every `validate` refusal, one test each;
- `apply` purity: the input tree is unchanged, and fields the editor does not own survive;
- the commit pipeline's abort paths: each precondition, a write that fails mid-way, and a
  read-back mismatch, each asserting the original file is back in place;
- the staleness check;
- gating: the actions are absent from the view and refused by `action()` when off;
- `tests/test_host_contract.py` for the new actions.

## Documentation

- plugin `HELP.md` and `CHANGELOG.md`;
- app `docs/architecture/plugins.md` for the new permission;
- app `features.md`;
- app `frontend/src/manual/USER_MANUAL.md`: a section for the editor and a troubleshooting
  entry for "the game overwrote my edit".

## Risks

- **`mf_*.hg`** does not bind the save - settled by experiment, see above. Retired.
- **Technology adjacency and upgrade relationships** are not modelled: validation confirms
  that a technology is a valid technology for that container and slot, not that the
  resulting layout is one the game considers sensible. Raised with the user, who chose to
  include technology anyway. The backup list is the remedy.
- **Steam Cloud** may re-sync an edited save. Out of scope; noted in the manual's
  troubleshooting entry.
