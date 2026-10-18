"""Chunking, embedding and cosine search over the standalone Codex.

numpy only: the app's `KnowledgeIndex` does the same brute-force search over an L2-normalised float32
matrix, and the measured numbers it is tuned with (threshold 0.6, task prefixes, batches of 32) carry
over because the embedding model is the same.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("nms-standalone.codex-index")

CHUNK_CHARS = 1000
CHUNK_OVERLAP = 150
BATCH = 32
RELEVANCE_THRESHOLD = 0.6          # measured in the app: relevant 0.74-0.78, unrelated up to 0.57
DOC_PREFIX = "search_document: "   # nomic-embed-text's task prefixes
QUERY_PREFIX = "search_query: "
INDEX_NAME = ".index.json"
VECTORS_NAME = ".vectors.npy"
QUERY_CACHE = 128


def chunk_text(text: str) -> list[str]:
    """Heading-aware chunks of about `CHUNK_CHARS` with `CHUNK_OVERLAP` of overlap, each prefixed with
    the heading path it sits under (the app's chunker does the same, and category words in the prefix
    are what let a question naming a category match)."""
    lines = text.splitlines()
    heading = ""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        current.append(line)
        size += len(line) + 1
        if size >= CHUNK_CHARS:
            chunks.append(_join(heading, current))
            tail = _tail(current)
            current = list(tail)
            size = sum(len(entry) + 1 for entry in current)
    if current:
        chunks.append(_join(heading, current))
    return [chunk for chunk in chunks if chunk.strip()]


def _join(heading: str, lines: list[str]) -> str:
    body = "\n".join(lines).strip()
    return f"[{heading}]\n{body}" if heading else body


def _tail(lines: list[str]) -> list[str]:
    """The last `CHUNK_OVERLAP` characters worth of lines, so a sentence split across chunks survives."""
    out: list[str] = []
    size = 0
    for line in reversed(lines):
        out.insert(0, line)
        size += len(line) + 1
        if size >= CHUNK_OVERLAP:
            break
    return out


class CodexIndex:
    """The embedded index of one Codex folder."""

    def __init__(self, root: Path, client, model: str):
        self.root = Path(root)
        self.client = client
        self.model = model
        self.index_path = self.root / INDEX_NAME
        self.vectors_path = self.root / VECTORS_NAME
        self._entries: list[dict] | None = None
        self._matrix: np.ndarray | None = None
        self._queries: dict[str, np.ndarray] = {}

    # ---- storage ----------------------------------------------------------

    def _load(self) -> None:
        if self._entries is not None:
            return
        try:
            self._entries = json.loads(self.index_path.read_text(encoding="utf-8"))["chunks"]
            self._matrix = np.load(self.vectors_path)
        except FileNotFoundError:
            self._entries, self._matrix = [], np.zeros((0, 1), dtype=np.float32)
        except (OSError, ValueError, KeyError):
            log.warning("the Codex index is damaged; it will be rebuilt on the next write", exc_info=True)
            self._entries, self._matrix = [], np.zeros((0, 1), dtype=np.float32)

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"model": self.model, "chunks": self._entries}), encoding="utf-8")
        tmp.replace(self.index_path)
        np.save(self.vectors_path, self._matrix)

    # ---- building ---------------------------------------------------------

    def reindex(self, changed: list[str], removed: list[str]) -> None:
        """Embed the changed documents and drop the removed ones. One request per batch of 32: every
        request cold-loads the model, so the request count is the cost (the app measured 10 files -> 1
        request after batching)."""
        self._load()
        gone = set(removed) | set(changed)
        entries = [entry for entry in self._entries if entry["path"] not in gone]
        vectors = [self._matrix[i] for i, entry in enumerate(self._entries) if entry["path"] not in gone]
        texts, new_entries = self._prepare(changed)
        for start in range(0, len(texts), BATCH):
            batch = texts[start:start + BATCH]
            vectors += [_normalise(np.asarray(vector, dtype=np.float32))
                        for vector in self.client.embed(self.model, [DOC_PREFIX + text for text in batch])]
        self._entries = entries + new_entries
        self._matrix = (np.vstack(vectors) if vectors else np.zeros((0, 1), dtype=np.float32))
        self._queries.clear()
        self._save()
        log.info("the Codex index holds %s chunks of %s documents", len(self._entries),
                 len({entry["path"] for entry in self._entries}))

    def _prepare(self, changed: list[str]) -> tuple[list[str], list[dict]]:
        """The chunks of every changed document, with their metadata, in one order."""
        texts: list[str] = []
        entries: list[dict] = []
        for path in changed:
            try:
                text = (self.root / path).read_text(encoding="utf-8")
            except OSError:
                log.warning("could not read %s for indexing", path, exc_info=True)
                continue
            title = _title(text, path)
            for chunk in chunk_text(text):
                texts.append(chunk)
                entries.append({"path": path, "title": title, "text": chunk})
        return texts, entries

    # ---- searching --------------------------------------------------------

    def search(self, query: str, k: int = 4) -> list[dict]:
        """The best `k` chunks above the relevance threshold. Any failure answers nothing (and is
        logged): a chat turn must not die because Ollama stopped."""
        self._load()
        if not self._entries or not (query or "").strip():
            return []
        try:
            vector = self._query_vector(query)
        except Exception as err:               # noqa: BLE001 - logged; the turn goes on without excerpts
            log.warning("could not embed the Codex query: %s", err)
            return []
        if vector is None or vector.shape[0] != self._matrix.shape[1]:
            log.warning("the Codex index was built with another model; skipping it")
            return []
        scores = self._matrix @ vector
        count = min(k, scores.shape[0])
        best = np.argpartition(-scores, count - 1)[:count]
        hits = sorted(((float(scores[i]), int(i)) for i in best), reverse=True)
        return [dict(self._entries[i], score=score) for score, i in hits if score >= RELEVANCE_THRESHOLD]

    def _query_vector(self, query: str):
        """The query's embedding, cached: a regenerate or a repeated question skips the ~1 s cold load."""
        if query in self._queries:
            return self._queries[query]
        vectors = self.client.embed(self.model, [QUERY_PREFIX + query])
        vector = _normalise(np.asarray(vectors[0], dtype=np.float32))
        if len(self._queries) >= QUERY_CACHE:
            self._queries.clear()
        self._queries[query] = vector
        return vector


def _normalise(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def _title(text: str, path: str) -> str:
    """One title rule for the whole host; `codex.title_of` owns it (front matter, then the body's H1)."""
    from standalone.codex import title_of
    return title_of(text, path)
