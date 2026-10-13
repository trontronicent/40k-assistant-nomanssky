"""Chunking, embedding and cosine search over the standalone Codex (no Ollama: the client is a fake)."""
import numpy as np

from standalone import codex_index


class FakeClient:
    """Embeds by counting letters: deterministic, and similar texts land near each other."""

    def __init__(self):
        self.requests = []

    def embed(self, model, texts):
        self.requests.append(list(texts))
        out = []
        for text in texts:
            folded = text.casefold()
            out.append([float(folded.count(letter)) for letter in "abcdefghij"] or [1.0])
        return out


def test_chunks_carry_their_heading():
    """Each chunk is embedded with the heading it sits under, which is what lets a question naming a
    category match the chunk at all (measured in the app: without it a German question fell below the
    0.6 threshold)."""
    text = "# Copper\n" + ("Copper is refined into Chromatic Metal. " * 40)
    chunks = codex_index.chunk_text(text)
    assert chunks and all(chunk.startswith("[Copper]") for chunk in chunks)


def test_long_documents_are_split_with_overlap():
    """A sentence split across two chunks would match neither; the overlap keeps it whole in one."""
    text = "# T\n" + "\n".join(f"line {i} with some words in it" for i in range(200))
    chunks = codex_index.chunk_text(text)
    assert len(chunks) > 1
    tail = chunks[0].splitlines()[-1]
    assert tail in chunks[1]


def test_a_short_document_is_one_chunk():
    """Most generated item documents are short; splitting them would dilute every hit."""
    assert len(codex_index.chunk_text("# Copper\nA metal.\n")) == 1


def test_embedding_uses_one_request_per_batch(tmp_path):
    """Every embedding request cold-loads the model, so the request count is what costs time. 40 chunks
    must be two requests of 32 and 8, not forty."""
    client = FakeClient()
    index = codex_index.CodexIndex(tmp_path, client, "nomic-embed-text")
    for i in range(40):
        (tmp_path / f"d{i}.md").write_text(f"# D{i}\nbody {i}\n", encoding="utf-8")
    index.reindex([f"d{i}.md" for i in range(40)], [])
    assert len(client.requests) == 2
    assert [len(batch) for batch in client.requests] == [32, 8]


def test_chunks_and_queries_carry_the_task_prefixes(tmp_path):
    """`nomic-embed-text` needs `search_document:` on chunks and `search_query:` on questions; without
    them the scores drift and the 0.6 threshold stops meaning anything."""
    client = FakeClient()
    index = codex_index.CodexIndex(tmp_path, client, "m")
    (tmp_path / "a.md").write_text("# A\nbody\n", encoding="utf-8")
    index.reindex(["a.md"], [])
    assert client.requests[0][0].startswith(codex_index.DOC_PREFIX)
    index.search("a question")
    assert client.requests[-1][0].startswith(codex_index.QUERY_PREFIX)


def test_search_returns_the_closest_document(tmp_path):
    """The point of embedding at all: the nearest chunk comes first."""
    client = FakeClient()
    index = codex_index.CodexIndex(tmp_path, client, "m")
    (tmp_path / "copper.md").write_text("# Copper\naaaa bbbb\n", encoding="utf-8")
    (tmp_path / "iron.md").write_text("# Iron\njjjj iiii\n", encoding="utf-8")
    index.reindex(["copper.md", "iron.md"], [])
    hits = index.search("aaaa bbbb", k=1)
    assert hits and hits[0]["title"] == "Copper" and hits[0]["score"] >= codex_index.RELEVANCE_THRESHOLD


def test_an_unrelated_question_answers_nothing(tmp_path):
    """Below the threshold the host must inject no excerpt at all: a weak hit is worse than none, since
    the model treats whatever it is given as relevant."""
    client = FakeClient()
    index = codex_index.CodexIndex(tmp_path, client, "m")
    (tmp_path / "copper.md").write_text("# Copper\naaaa\n", encoding="utf-8")
    index.reindex(["copper.md"], [])
    assert index.search("jjjj") == []


def test_a_removed_document_leaves_the_index(tmp_path):
    """Otherwise the Codex keeps answering from documents the game no longer has."""
    client = FakeClient()
    index = codex_index.CodexIndex(tmp_path, client, "m")
    (tmp_path / "a.md").write_text("# A\naaaa\n", encoding="utf-8")
    index.reindex(["a.md"], [])
    index.reindex([], ["a.md"])
    assert index.search("aaaa") == []


def test_a_changed_document_is_not_duplicated(tmp_path):
    """Re-indexing a document must replace its chunks, not add a second copy that then wins twice."""
    client = FakeClient()
    index = codex_index.CodexIndex(tmp_path, client, "m")
    (tmp_path / "a.md").write_text("# A\naaaa\n", encoding="utf-8")
    index.reindex(["a.md"], [])
    index.reindex(["a.md"], [])
    assert len(index.search("aaaa", k=10)) == 1


def test_the_index_survives_a_restart(tmp_path):
    """The index is on disk; a restart must not cost a full re-embed of 2,400 documents."""
    client = FakeClient()
    index = codex_index.CodexIndex(tmp_path, client, "m")
    (tmp_path / "a.md").write_text("# A\naaaa\n", encoding="utf-8")
    index.reindex(["a.md"], [])
    fresh = codex_index.CodexIndex(tmp_path, client, "m")
    assert fresh.search("aaaa", k=1)[0]["title"] == "A"


def test_a_damaged_index_reads_as_empty_and_is_logged(tmp_path, caplog):
    """A half-written index file must not stop a chat turn; it answers nothing until the next write
    rebuilds it."""
    (tmp_path / codex_index.INDEX_NAME).write_text("{broken", encoding="utf-8")
    index = codex_index.CodexIndex(tmp_path, FakeClient(), "m")
    assert index.search("anything") == []
    assert "damaged" in caplog.text


def test_a_dimension_mismatch_is_skipped_not_scored(tmp_path, caplog):
    """An index built with another embedding model must be skipped with a warning - never scored, which
    is the app's rule and the reason a library stores its `embed_model`."""
    client = FakeClient()
    index = codex_index.CodexIndex(tmp_path, client, "m")
    (tmp_path / "a.md").write_text("# A\naaaa\n", encoding="utf-8")
    index.reindex(["a.md"], [])
    index._matrix = np.zeros((1, 3), dtype=np.float32)
    assert index.search("aaaa") == []
    assert "another model" in caplog.text


def test_an_embedding_failure_answers_nothing(tmp_path, caplog):
    """Ollama may be stopped; the search must answer nothing and log, never raise into the turn."""
    class Broken(FakeClient):
        def embed(self, model, texts):
            raise RuntimeError("ollama is gone")

    index = codex_index.CodexIndex(tmp_path, FakeClient(), "m")
    (tmp_path / "a.md").write_text("# A\naaaa\n", encoding="utf-8")
    index.reindex(["a.md"], [])
    index.client = Broken()
    assert index.search("aaaa") == []
    assert "ollama is gone" in caplog.text


def test_a_repeated_question_is_embedded_once(tmp_path):
    """A cold query embed costs ~1 s; a regenerate or a repeated question must not pay it twice."""
    client = FakeClient()
    index = codex_index.CodexIndex(tmp_path, client, "m")
    (tmp_path / "a.md").write_text("# A\naaaa\n", encoding="utf-8")
    index.reindex(["a.md"], [])
    before = len(client.requests)
    index.search("aaaa")
    index.search("aaaa")
    assert len(client.requests) == before + 1
