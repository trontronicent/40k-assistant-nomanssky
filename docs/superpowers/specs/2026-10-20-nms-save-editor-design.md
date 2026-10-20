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

### `mf_*.hg` is opaque

`mf_save.hg` is 432 bytes with no magic and high entropy (encrypted metadata). Whether the
game validates `save.hg` against it cannot be determined by reading. It becomes an explicit
empirical gate, not an assumption - see *Correctness gates*.

## Modules

### `nms_connector/lz4.py` - `compress_block(data) -> bytes`

Literals-only LZ4 block output: token `0xF0`, the extended literal length bytes, then the
literals. This is valid LZ4 that any decompressor accepts, needs no match finding, and is
correct by construction. Compression ratio is explicitly not a goal; the file grows by
roughly 0.4 % of its size in length bytes.

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
2. No Man's Sky is not running;
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
- a save-slot picker;
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
- a manual gate the user drives: commit a no-op re-encode over save slot 2 (the older pair,
  not the live slot) and load it in the game. If it loads, `mf_*.hg` needs no update and the
  feature is viable. If it does not, that is known before anything is built on top.

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

- **`mf_*.hg`** may bind the save. Addressed by the manual gate above before further work.
- **Technology adjacency and upgrade relationships** are not modelled: validation confirms
  that a technology is a valid technology for that container and slot, not that the
  resulting layout is one the game considers sensible. Raised with the user, who chose to
  include technology anyway. The backup list is the remedy.
- **Steam Cloud** may re-sync an edited save. Out of scope; noted in the manual's
  troubleshooting entry.
