"""The standalone Codex channel.

`ctx.codex.write(docs, owner=..., adopt=..., adopt_dirs=...)` for the connector, plus `search()` for the
chat and the page. The policy is the app's (`src/plugins/codex.py`), because the connector relies on it:
a document the user edited is kept, one they deleted stays deleted, each owner maintains its own set,
and the marker is the host's so a plugin cannot claim a file it did not write.

Files on disk are the truth; `.state.json` records what this host wrote (per owner) and what the user
deleted. Both the state file and the temporary files are dot-prefixed, so a Codex scan skips them.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

log = logging.getLogger("nms-standalone.codex")

LIBRARY_NAME = "No Man's Sky"
MARKER_KEY = "stc_owner"
PLUGIN_ID = "nomanssky"
OWNER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
MAX_DOCS = 8000
MAX_DOC_BYTES = 200 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
STATE_NAME = ".state.json"
COUNT_KEYS = ("written", "unchanged", "removed", "kept_edited", "hidden", "library")
MIN_SEARCH_WORD = 3
TITLE_WEIGHT = 0.7        # a word in the title outweighs the body
MAX_WORD_COUNT = 5        # more occurrences of one word add nothing
MAX_ADOPT_DIRS = 8


class CodexError(RuntimeError):
    """The write was refused; nothing was touched."""


# --------------------------------------------------------------------------- validation


def document_problem(path: str) -> str | None:
    """Why this path may not be written, or None. Mirrors the app's `document_problem`."""
    if not path or not isinstance(path, str):
        return "a document path must be a non-empty string"
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return f"{path}: absolute paths are refused"
    if "\\" in path:
        return f"{path}: use forward slashes"
    if not path.endswith(".md"):
        return f"{path}: only .md documents"
    for part in path.split("/"):
        if part in ("", ".", ".."):
            return f"{path}: bad path segment"
        if part.startswith((".", "_")):
            return f"{path}: a part starting with . or _ is skipped by the Codex scan"
    return None


def _text_problem(path: str, text) -> str | None:
    """Why one document's text is refused (not a string, too large), or None."""
    if not isinstance(text, str):
        return f"{path}: the text must be a string"
    size = len(text.encode("utf-8"))
    if size > MAX_DOC_BYTES:
        return f"{path}: {size} bytes is over the {MAX_DOC_BYTES} limit"
    return None


def request_problem(documents: dict, owner: str) -> str | None:
    """Why the whole batch is refused, or None. Checked before anything is touched."""
    if not OWNER_RE.match(owner or ""):
        return f"bad owner {owner!r}"
    if not isinstance(documents, dict):
        return "documents must be a mapping of path to text"
    if len(documents) > MAX_DOCS:
        return f"too many documents ({len(documents)} > {MAX_DOCS})"
    total = 0
    for path, text in documents.items():
        problem = document_problem(path) or _text_problem(path, text)
        if problem:
            return problem
        total += len(text.encode("utf-8"))
    if total > MAX_TOTAL_BYTES:
        return f"the write is {total} bytes, over the {MAX_TOTAL_BYTES} limit"
    return None


# --------------------------------------------------------------------------- the marker


def strip_marker(text: str) -> str:
    """The text without any `stc_owner` line: a plugin cannot forge ownership of a file."""
    return "\n".join(line for line in text.splitlines() if not line.startswith(MARKER_KEY + ":"))


def stamp(text: str, owner: str) -> str:
    """The document as it is written: front matter carrying this host's marker, then the plugin's text."""
    body = strip_marker(text)
    marker = f"{MARKER_KEY}: {PLUGIN_ID}/{owner}"
    if body.startswith("---\n") and "\n---" in body[4:]:
        head, rest = body[4:].split("\n---", 1)
        return f"---\n{head}\n{marker}\n---{rest}"
    return f"---\n{marker}\n---\n{body}"


def marker_of(text: str) -> str | None:
    """The owner recorded in a document on disk, or None."""
    for line in text.splitlines():
        if line.startswith(MARKER_KEY + ":"):
            return line.split(":", 1)[1].strip()
    return None


def split_front_matter(text: str) -> tuple[list[str], str]:
    """`(front matter lines, body)`. The front matter is the opening `---` block, if there is one."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], "\n".join(lines[index + 1:])
    return [], text


def title_of(text: str, path: str) -> str:
    """The document's title, by the Codex's own precedence: front matter `title:`, else the first `# H1`
    **of the body**, else the file stem.

    The body matters: the connector's documents carry a YAML **comment** in their front matter
    (`# generated: nomanssky-plugin recipes - ...`), and reading the first `# ` line of the whole file
    made every search hit and every listed title read as that marker (seen live 2026-10-13).
    """
    front, body = split_front_matter(text)
    for line in front:
        if line.startswith("title:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'") or Path(path).stem
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return Path(path).stem


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- the policy


def decide(on_disk: str | None, mine: bool, same: bool, previously: str | None, adoptable: bool) -> str:
    """`write` | `unchanged` | `kept_edited` - the whole policy in one pure function.

    `mine` = the file carries this owner's marker, `same` = it already holds what we would write,
    `previously` = the hash this host last wrote for that path, `adoptable` = it carries the legacy
    marker and this channel has not written it yet.
    """
    if on_disk is None:
        return "write"
    if same:
        return "unchanged"
    if mine:
        # Ours, but different: only overwrite when it is still exactly what we wrote last time.
        return "write" if previously and digest(on_disk) == previously else "kept_edited"
    return "write" if adoptable else "kept_edited"


def decide_stale(mine: bool, on_disk: str, previously: str | None) -> str:
    """`remove` | `kept_edited` for a document this owner no longer produces."""
    if mine and previously and digest(on_disk) == previously:
        return "remove"
    return "kept_edited"


# --------------------------------------------------------------------------- the channel


class StandaloneCodex:
    """The Codex library of the standalone install: one folder of Markdown documents plus an index."""

    def __init__(self, root: Path, index=None, library: str = LIBRARY_NAME):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = index
        self.library = library
        self.state_path = self.root / STATE_NAME

    # ---- state ------------------------------------------------------------

    def _state(self) -> dict:
        """`{owner: {"written": {path: sha}, "deleted": [path]}}`; a damaged file reads as empty."""
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            log.warning("the Codex state file is damaged; treating it as empty", exc_info=True)
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_state(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        tmp.replace(self.state_path)

    @staticmethod
    def _section(state: dict, owner: str) -> dict:
        section = state.setdefault(owner, {})
        section.setdefault("written", {})
        section.setdefault("deleted", [])
        return section

    # ---- reading what is there -------------------------------------------

    def _read(self, path: str) -> str | None:
        try:
            return (self.root / path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            log.warning("could not read the Codex document %s", path, exc_info=True)
            return None

    def _write_file(self, path: str, text: str) -> None:
        """Atomic through a dot-prefixed temporary file in place (the scan skips dot files)."""
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name("." + target.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)

    # ---- the write --------------------------------------------------------

    async def write(self, documents: dict, owner: str, adopt: str = "",
                    adopt_dirs: tuple[str, ...] = ()) -> dict:
        """Keep this owner's set of documents up to date. Returns the counts the connector reports."""
        problem = request_problem(documents, owner)
        if problem:
            raise CodexError(problem)
        if adopt and (not isinstance(adopt, str) or not 1 <= len(adopt) <= 120):
            raise CodexError("adopt must be a 1-120 character text")
        if len(adopt_dirs or ()) > MAX_ADOPT_DIRS:
            raise CodexError(f"at most {MAX_ADOPT_DIRS} adopt_dirs")
        state = self._state()
        section = self._section(state, owner)
        counts = dict.fromkeys(COUNT_KEYS[:-1], 0)
        counts["library"] = self.library
        changed = self._apply(documents, owner, section, counts, (adopt, tuple(adopt_dirs or ())))
        removed = self._sweep(documents, section, counts)
        self._save_state(state)
        self._reindex(changed, removed)
        return counts

    def _apply(self, documents: dict, owner: str, section: dict, counts: dict, adoption) -> list[str]:
        """Write what changed; returns the paths the index must learn about."""
        adopt, adopt_dirs = adoption
        changed = []
        for path in sorted(documents):
            if path in section["deleted"]:
                counts["hidden"] += 1
                continue
            wanted = stamp(documents[path], owner)
            on_disk = self._read(path)
            action = decide(on_disk, self._is_mine(on_disk, owner), on_disk == wanted,
                            section["written"].get(path),
                            self._adoptable(path, on_disk, section, adopt, adopt_dirs))
            if action == "write":
                self._write_file(path, wanted)
                section["written"][path] = digest(wanted)
                counts["written"] += 1
                changed.append(path)
            elif action == "unchanged":
                section["written"][path] = digest(wanted)
                counts["unchanged"] += 1
            else:
                counts["kept_edited"] += 1
        return changed

    def _sweep(self, documents: dict, section: dict, counts: dict) -> list[str]:
        """Remove this owner's documents that are no longer produced; keep the ones the user edited."""
        removed = []
        for path in [p for p in list(section["written"]) if p not in documents]:
            on_disk = self._read(path)
            if on_disk is None:
                section["written"].pop(path, None)
                continue
            if decide_stale(self._is_mine(on_disk, None), on_disk, section["written"][path]) == "remove":
                (self.root / path).unlink(missing_ok=True)
                section["written"].pop(path, None)
                counts["removed"] += 1
                removed.append(path)
            else:
                section["written"].pop(path, None)
                counts["kept_edited"] += 1
        return removed

    @staticmethod
    def _is_mine(on_disk: str | None, owner: str | None) -> bool:
        if on_disk is None:
            return False
        marker = marker_of(on_disk)
        if marker is None:
            return False
        return marker == f"{PLUGIN_ID}/{owner}" if owner else marker.startswith(PLUGIN_ID + "/")

    @staticmethod
    def _adoptable(path: str, on_disk: str | None, section: dict, adopt: str,
                   adopt_dirs: tuple[str, ...]) -> bool:
        """A legacy file claimed once: it carries the old marker text, no `stc_owner`, sits in one of the
        named folders, and this channel has not written that path yet. Re-claiming on every write would
        make removing `stc_owner` pointless."""
        if not adopt or on_disk is None or path in section["written"]:
            return False
        if marker_of(on_disk) is not None:
            return False
        if adopt_dirs and not any(path.startswith(folder.rstrip("/") + "/") for folder in adopt_dirs):
            return False
        return adopt in on_disk

    def _reindex(self, changed: list[str], removed: list[str]) -> None:
        """Tell the index what moved. A failure is reported, never raised: the documents are on disk."""
        if self.index is None or not (changed or removed):
            return
        try:
            self.index.reindex(changed, removed)
        except Exception as err:               # noqa: BLE001 - logged; the write itself succeeded
            log.warning("the Codex index could not be updated: %s", err, exc_info=True)

    # ---- deletions --------------------------------------------------------

    def note_deletions(self) -> None:
        """Record every document this host wrote and the user has since deleted, so it is never written
        again (a tombstone). Called before each write and from the page."""
        state = self._state()
        for section in state.values():
            written = section.get("written", {})
            deleted = section.setdefault("deleted", [])
            for path in [p for p in list(written) if not (self.root / p).exists()]:
                written.pop(path, None)
                if path not in deleted:
                    deleted.append(path)
        self._save_state(state)

    def hidden(self) -> list[str]:
        """The documents the user deleted, across owners."""
        out: list[str] = []
        for section in self._state().values():
            out.extend(section.get("deleted", []))
        return sorted(set(out))

    def restore(self) -> None:
        """Forget every tombstone, so the next write brings the documents back."""
        state = self._state()
        for section in state.values():
            section["deleted"] = []
        self._save_state(state)

    # ---- reading ----------------------------------------------------------

    def documents(self) -> list[dict]:
        """Every document in the library as `{path, title, text}` (used by search and the page)."""
        out = []
        for file in sorted(self.root.rglob("*.md")):
            if any(part.startswith((".", "_")) for part in file.relative_to(self.root).parts):
                continue
            text = self._read(file.relative_to(self.root).as_posix())
            if text is None:
                continue
            path = file.relative_to(self.root).as_posix()
            out.append({"path": path, "title": title_of(text, path), "text": text})
        return out

    def search(self, query: str, k: int = 4) -> list[dict]:
        """Semantic search when an index is present, a word search otherwise (the app's overlay Codex
        search is full text too, so this is the same answer the user is used to without a model)."""
        if self.index is not None:
            return self.index.search(query, k)
        return self._full_text(query, k)

    def _full_text(self, query: str, k: int) -> list[dict]:
        """The search without AI: every query word must appear, and a hit in the **title** outweighs the
        body. Ranking by word presence alone put short unrelated documents first ("chromatic metal" ->
        *Dawn's End*, measured on the real 2,388 documents), because almost everything mentions a metal
        somewhere."""
        words = [w for w in re.split(r"\W+", (query or "").casefold()) if len(w) >= MIN_SEARCH_WORD]
        if not words:
            return []
        scored = []
        for doc in self.documents():
            score = _text_score(words, doc)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda row: (-row[0], row[1]["title"]))
        return [dict(doc, score=round(score, 3)) for score, doc in scored[:k]]


def _text_score(words: list[str], doc: dict) -> float:
    """How well a document answers these words without a model.

    Every word must appear somewhere, or the document is out (0). A word in the title is worth
    `TITLE_WEIGHT` of the score, the rest comes from how often the words occur in the body, which keeps
    a short unrelated document from outranking the item's own page.
    """
    title = doc["title"].casefold()
    body = doc["text"].casefold()
    if not all(word in body or word in title for word in words):
        return 0.0
    in_title = sum(1 for word in words if word in title)
    occurrences = sum(min(body.count(word), MAX_WORD_COUNT) for word in words)
    return TITLE_WEIGHT * (in_title / len(words)) + (1 - TITLE_WEIGHT) * (
        occurrences / (len(words) * MAX_WORD_COUNT))
