"""The plugin's documents in the user's Codex, through the app's Codex channel (plugin 0.15.0, needs app 3.15.0).

Before 0.15.0 the plugin guessed the app's ``knowledge_base`` folder from its own install path, wrote 2,400 generated
documents there itself and asked the user to press *Write Codex documents* and then *Sync now*. Now:

* **One call.** ``ctx.codex.write(docs, owner="generated", adopt=..., adopt_dirs=...)``: the app confines the paths,
  marks the files, never overwrites a document the user edited, never writes a deleted one again (*Restore hidden
  documents* on the plugin page brings them back) and indexes everything in a single pass.
* **One owner for everything generated.** Items and world types share the language folders, and ``adopt_dirs`` removes
  legacy files that are no longer produced; two owners would delete each other's documents.
* **Adoption.** The documents written before the channel existed carry ``generated: nomanssky-plugin recipes`` /
  ``... worlds``; ``adopt`` claims them once, so they keep updating instead of reading as the user's own files.
* **Automatic.** Written after the game files are read, once per game build and plugin version (``stamp_of``), not
  on every 5 s tick; a failed write is retried after ``RETRY_AFTER_S`` rather than every tick.
* **Shipped documents** (``codex/`` in this repository: the FAQ, guides, references and updates) are written by the
  app itself from ``contributes.codex``; this module does not touch them.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import recipes

ADOPT = "generated: nomanssky-plugin"          # the start of both legacy markers (recipes, worlds)
OWNER = "generated"
STAMP_NAME = "codex_stamp.json"
RETRY_AFTER_S = 600


def generated_documents(tables, lookup) -> dict[str, str]:
    """Every generated document (items, then world types) as {path: text}; blocking (reads the tables)."""
    terms = tables.terms
    docs = dict(recipes.documents(tables.recipes, lookup, terms))
    docs.update(tables.worlds.documents(lookup, terms))
    return docs


def legacy_folders(terms) -> tuple[str, ...]:
    """The folders whose legacy-marked files the plugin owns: the language roots and the old mixed ones."""
    return tuple(recipes._label(lang) for lang in recipes.languages_of(terms)) + recipes.LEGACY_DIRS


def stamp_of(install, version: str) -> dict:
    """What the written documents depend on: the game build, its language and the plugin version."""
    return {"build": getattr(install, "build_id", None), "language": getattr(install, "language", None),
            "version": version}


def describe(counts: dict) -> str:
    """The one-line result shown on the page."""
    parts = [f"{counts.get('written', 0):,} written", f"{counts.get('unchanged', 0):,} unchanged"]
    for key, label in (("removed", "removed"), ("kept_edited", "kept because you edited them"),
                       ("hidden", "left out because you deleted them")):
        if counts.get(key):
            parts.append(f"{counts[key]:,} {label}")
    return f"Codex documents in the library '{counts.get('library', '?')}': " + ", ".join(parts) + "."


class CodexPublisher:
    """Writes the generated documents when they are due; holds the plugin's side of the schedule."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / STAMP_NAME
        self.failed_at: float | None = None

    def _saved(self) -> dict | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def due(self, stamp: dict, now: float) -> bool:
        """True when nothing was written for this build/language/version yet and no failure is cooling down."""
        if self.failed_at is not None and now - self.failed_at < RETRY_AFTER_S:
            return False
        return self._saved() != stamp

    def remember(self, stamp: dict) -> None:
        self.failed_at = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(stamp), encoding="utf-8")
        tmp.replace(self.path)

    def failed(self, now: float) -> None:
        self.failed_at = now

    @staticmethod
    def ready(tables, gamedata) -> str | None:
        """Why the documents cannot be built yet, or None."""
        if not (tables.loaded and gamedata.ready and tables.recipes.recipes and tables.worlds.worlds):
            return tables.recipes.error or tables.worlds.error or "the game files are not read yet"
        return None
