"""The standalone Codex: the write policy, the tombstones, and search with and without AI."""
import asyncio

import pytest

from standalone import codex


@pytest.fixture
def library(tmp_path):
    return codex.StandaloneCodex(tmp_path / "codex", index=None)


def write(library, docs, **kwargs):
    return asyncio.run(library.write(docs, owner="generated", **kwargs))


def test_the_counts_match_what_the_connector_reads():
    """`nms_connector/codex_sync.describe` reads these keys off the result. A different shape fails only
    at runtime, after 2,400 documents have been prepared - the contract both hosts implement."""
    from nms_connector import codex_sync
    counts = {"written": 1, "unchanged": 2, "removed": 3, "kept_edited": 4, "hidden": 5, "library": "x"}
    assert set(counts) <= set(codex.COUNT_KEYS)
    assert "1 written" in codex_sync.describe(counts)


def test_a_document_is_written_and_marked(library):
    """The marker is the host's, written into the front matter, so a later write knows which files it
    owns - exactly the app's `stc_owner` rule."""
    write(library, {"Items/Copper.md": "# Copper\n"})
    text = (library.root / "Items" / "Copper.md").read_text(encoding="utf-8")
    assert "stc_owner: nomanssky/generated" in text and "# Copper" in text


def test_the_result_counts_the_write_and_names_the_library(library):
    """The connector shows this line on its page ("2,388 written, ... in the library 'No Man's Sky'")."""
    counts = write(library, {"A.md": "a", "B.md": "b"})
    assert counts["written"] == 2 and counts["library"]


def test_an_unchanged_document_is_not_rewritten(library):
    """2,400 documents are written on every game build; rewriting unchanged files would re-embed all of
    them and cost minutes of model time for nothing."""
    write(library, {"Items/Copper.md": "# Copper\n"})
    before = (library.root / "Items" / "Copper.md").stat().st_mtime_ns
    counts = write(library, {"Items/Copper.md": "# Copper\n"})
    assert counts["unchanged"] == 1
    assert (library.root / "Items" / "Copper.md").stat().st_mtime_ns == before


def test_a_users_edit_is_kept(library):
    """A document the user edited is theirs. Overwriting it would silently undo their notes, which is why
    the app compares the recorded hash before writing."""
    write(library, {"Items/Copper.md": "# Copper\n"})
    path = library.root / "Items" / "Copper.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nmy own notes\n", encoding="utf-8")
    counts = write(library, {"Items/Copper.md": "# Copper\nnew generated text\n"})
    assert counts["kept_edited"] == 1
    assert "my own notes" in path.read_text(encoding="utf-8")


def test_a_file_whose_marker_the_user_removed_is_never_touched(library):
    """Removing `stc_owner` is how the user claims a document; from then on it is theirs, which is what
    makes the marker meaningful at all."""
    write(library, {"Items/Copper.md": "# Copper\n"})
    (library.root / "Items" / "Copper.md").write_text("# Copper\nmine now\n", encoding="utf-8")
    counts = write(library, {"Items/Copper.md": "# Copper\nnew\n"})
    assert counts["kept_edited"] == 1
    assert "mine now" in (library.root / "Items" / "Copper.md").read_text(encoding="utf-8")


def test_a_deleted_document_is_never_written_again(library):
    """A deletion outranks the plugin's wish for the document; without the tombstone every write would
    resurrect what the user threw away."""
    write(library, {"Items/Copper.md": "# Copper\n"})
    (library.root / "Items" / "Copper.md").unlink()
    library.note_deletions()
    counts = write(library, {"Items/Copper.md": "# Copper\n"})
    assert not (library.root / "Items" / "Copper.md").exists()
    assert counts["hidden"] == 1
    assert library.hidden() == ["Items/Copper.md"]


def test_restore_brings_a_hidden_document_back(library):
    """`restore()` clears the tombstones, the one way back from an accidental deletion."""
    write(library, {"Items/Copper.md": "# Copper\n"})
    (library.root / "Items" / "Copper.md").unlink()
    library.note_deletions()
    library.restore()
    write(library, {"Items/Copper.md": "# Copper\n"})
    assert (library.root / "Items" / "Copper.md").exists()


def test_a_stale_document_of_this_owner_is_removed(library):
    """A game update removes items; documents the plugin no longer produces must go, or the Codex keeps
    answering from things the game no longer has."""
    write(library, {"Items/A.md": "a", "Items/B.md": "b"})
    counts = write(library, {"Items/A.md": "a"})
    assert counts["removed"] == 1 and not (library.root / "Items" / "B.md").exists()


def test_a_stale_document_the_user_edited_is_kept(library):
    """Removing a file the user has written in would destroy their work; the app keeps it and says so."""
    write(library, {"Items/A.md": "a", "Items/B.md": "b"})
    (library.root / "Items" / "B.md").write_text("mine\n", encoding="utf-8")
    counts = write(library, {"Items/A.md": "a"})
    assert counts["kept_edited"] == 1 and (library.root / "Items" / "B.md").exists()


def test_two_owners_do_not_delete_each_others_files(library):
    """The connector writes generated documents while the install ships its own; one owner's stale sweep
    must not touch the other's, which is the bug the app's per-owner state prevents."""
    write(library, {"Items/A.md": "a"})
    asyncio.run(library.write({"Guides/G.md": "g"}, owner="shipped"))
    write(library, {"Items/A.md": "a"})
    assert (library.root / "Guides" / "G.md").exists()


@pytest.mark.parametrize("bad", ["/abs.md", "../x.md", "a\\b.md", "_hidden/x.md", ".dot/x.md", "x.txt", ""])
def test_a_bad_path_is_refused_before_anything_is_touched(library, bad):
    """Paths come from the plugin; absolute paths, `..`, backslashes, dot- or underscore-prefixed parts
    (the Codex scan skips those, so the file would never be indexed) and non-`.md` files are refused as a
    batch, so a bad entry cannot leave a half-written library."""
    with pytest.raises(codex.CodexError):
        write(library, {bad: "x", "Good.md": "ok"})
    assert not (library.root / "Good.md").exists()


def test_the_batch_is_bounded(library):
    """`MAX_DOCS` and the byte limits are checked before anything is written, like the app's
    `request_problem` - a runaway generator must not fill the disk."""
    with pytest.raises(codex.CodexError):
        write(library, {f"{i}.md": "x" for i in range(codex.MAX_DOCS + 1)})
    with pytest.raises(codex.CodexError):
        write(library, {"big.md": "x" * (codex.MAX_DOC_BYTES + 1)})


def test_a_bad_owner_is_refused(library):
    """The owner names the state file's section; anything but a short slug could escape it."""
    with pytest.raises(codex.CodexError):
        asyncio.run(library.write({"A.md": "a"}, owner="../etc"))


def test_adoption_claims_legacy_files_once(library):
    """The connector wrote these documents into the app's Codex before the channel existed; a file
    carrying its old marker and no `stc_owner` is claimed once and maintained from then on."""
    (library.root / "Items").mkdir(parents=True)
    (library.root / "Items" / "Copper.md").write_text("generated: nomanssky-plugin\n# Copper\n",
                                                      encoding="utf-8")
    counts = write(library, {"Items/Copper.md": "# Copper\n"},
                   adopt="generated: nomanssky-plugin", adopt_dirs=("Items",))
    assert counts["written"] == 1
    assert "stc_owner: nomanssky/generated" in (library.root / "Items" / "Copper.md").read_text(encoding="utf-8")


def test_a_file_without_the_legacy_marker_is_not_adopted(library):
    """What the user wrote by hand stays theirs, even in a folder the plugin also writes into."""
    (library.root / "Items").mkdir(parents=True)
    (library.root / "Items" / "Copper.md").write_text("# My own Copper notes\n", encoding="utf-8")
    counts = write(library, {"Items/Copper.md": "# Copper\n"},
                   adopt="generated: nomanssky-plugin", adopt_dirs=("Items",))
    assert counts["kept_edited"] == 1
    assert "My own Copper notes" in (library.root / "Items" / "Copper.md").read_text(encoding="utf-8")


def test_a_damaged_state_file_reads_as_empty_and_is_logged(library, caplog):
    """A half-written state file must not stop the write; it reads as empty and leaves a warning, the way
    the app treats its own. A document whose bytes still match is simply unchanged - losing the state
    must not cause 2,388 pointless rewrites."""
    write(library, {"A.md": "a"})
    library.state_path.write_text("{broken", encoding="utf-8")
    counts = write(library, {"A.md": "a"})
    assert counts["unchanged"] == 1 and counts["written"] == 0
    assert "state" in caplog.text.lower()


def test_without_a_recorded_hash_a_changed_document_is_kept(library):
    """Deliberate and conservative: with the state lost, the host cannot tell its own earlier text from
    the user's edit, and it never overwrites without evidence. The user's way to take a document over is
    to remove its marker; the way to get generated text back is to delete the file."""
    write(library, {"A.md": "a"})
    library.state_path.unlink()
    counts = write(library, {"A.md": "a brand new generated text"})
    assert counts["kept_edited"] == 1
    assert "brand new" not in (library.root / "A.md").read_text(encoding="utf-8")


def test_full_text_search_without_ai(library):
    """Without Ollama the Codex still answers: a word search over the documents, which is what the app's
    overlay Codex search does too (full text, no model)."""
    write(library, {"Items/Copper.md": "# Copper\nCopper is refined into Chromatic Metal.\n",
                    "Items/Iron.md": "# Ferrite Dust\nFerrite Dust is everywhere.\n"})
    hits = library.search("chromatic metal", k=3)
    assert hits and hits[0]["title"] == "Copper"


def test_full_text_search_ignores_short_words(library):
    """"in", "a" and "of" match everything; requiring them would rank by noise."""
    write(library, {"A.md": "# A\nCopper is refined in a refiner.\n", "B.md": "# B\nNothing here.\n"})
    assert [hit["title"] for hit in library.search("is a of copper", k=3)] == ["A"]


def test_vector_search_is_used_when_an_index_is_present(tmp_path):
    """With AI installed the search is semantic, so a question in other words still finds the document -
    the reason the app embeds at all."""
    class FakeIndex:
        def search(self, query, k):
            return [{"path": "Items/Copper.md", "title": "Copper", "text": "...", "score": 0.78}]

        def reindex(self, changed, removed):
            return None

    library = codex.StandaloneCodex(tmp_path / "codex", index=FakeIndex())
    assert library.search("what do I smelt for chromatic metal", k=3)[0]["score"] == 0.78


def test_the_index_is_told_what_changed(tmp_path):
    """Re-embedding everything on every write would cost minutes; the index only hears about the files
    that actually changed and the ones that went away."""
    seen = {}

    class FakeIndex:
        def search(self, query, k):
            return []

        def reindex(self, changed, removed):
            seen["changed"] = sorted(changed)
            seen["removed"] = sorted(removed)

    library = codex.StandaloneCodex(tmp_path / "codex", index=FakeIndex())
    asyncio.run(library.write({"A.md": "a", "B.md": "b"}, owner="generated"))
    asyncio.run(library.write({"A.md": "a", "C.md": "c"}, owner="generated"))
    assert seen["changed"] == ["C.md"] and seen["removed"] == ["B.md"]


def test_an_index_failure_never_fails_the_write(tmp_path, caplog):
    """The documents are on disk either way; a failed embedding (Ollama stopped) must leave them there
    and be reported, not roll the write back."""
    class BrokenIndex:
        def search(self, query, k):
            return []

        def reindex(self, changed, removed):
            raise RuntimeError("ollama is gone")

    library = codex.StandaloneCodex(tmp_path / "codex", index=BrokenIndex())
    counts = asyncio.run(library.write({"A.md": "a"}, owner="generated"))
    assert counts["written"] == 1 and (library.root / "A.md").exists()
    assert "ollama is gone" in caplog.text


# --------------------------------------------------------------------------- the routes


def test_the_codex_routes_are_404_without_a_library(tmp_path):
    """A `codex`-less install (the user turned it off) must say so plainly; the page then hides the box."""
    from standalone_fixtures import build_deps, call
    deps = build_deps(tmp_path)
    assert call(deps, "GET", "/api/codex").status == 404
    assert call(deps, "POST", "/api/codex/search", {"query": "copper"}).status == 404


def test_the_codex_route_reports_the_library(tmp_path):
    """The page shows how many documents the connector keeps and what is hidden."""
    from standalone_fixtures import build_deps, call
    import json as _json
    library = codex.StandaloneCodex(tmp_path / "codex", index=None)
    write(library, {"Items/Copper.md": "# Copper\nA metal.\n"})
    deps = build_deps(tmp_path, codex=library)
    body = _json.loads(call(deps, "GET", "/api/codex").body)
    assert body["documents"] == 1 and body["titles"] == ["Copper"] and body["hidden"] == []


def test_the_search_route_answers_hits(tmp_path):
    """This is also what the overlay's Codex search area uses - full text without AI, as in the app."""
    from standalone_fixtures import build_deps, call
    import json as _json
    library = codex.StandaloneCodex(tmp_path / "codex", index=None)
    write(library, {"Items/Copper.md": "# Copper\nCopper is refined into Chromatic Metal.\n"})
    deps = build_deps(tmp_path, codex=library)
    body = _json.loads(call(deps, "POST", "/api/codex/search", {"query": "chromatic"}).body)
    assert body["hits"][0]["title"] == "Copper"
    assert call(deps, "POST", "/api/codex/search", {"query": ""}).status == 422


def test_the_restore_route_clears_the_tombstones(tmp_path):
    """The one way back from a deletion the user regrets."""
    from standalone_fixtures import build_deps, call
    library = codex.StandaloneCodex(tmp_path / "codex", index=None)
    write(library, {"A.md": "a"})
    (library.root / "A.md").unlink()
    library.note_deletions()
    deps = build_deps(tmp_path, codex=library)
    assert call(deps, "POST", "/api/codex/restore").status == 200
    assert library.hidden() == []


def test_the_title_comes_from_the_front_matter(library):
    """The connector's documents carry a YAML **comment** in their front matter
    (`# generated: nomanssky-plugin recipes - ...`). Reading the first `# ` line of the whole file made
    every Codex hit read as that marker (seen live 2026-10-13 on the real 2,388 documents)."""
    text = ('---\ntitle: "Aalgelee"\ntags: ["FOOD_F_JEELS"]\n'
            '# generated: nomanssky-plugin recipes - edits are overwritten\n---\n\n# Aalgelee\n')
    assert codex.title_of(text, "Deutsch/Nahrung/Aalgelee.md") == "Aalgelee"


def test_the_title_falls_back_to_the_bodys_heading(library):
    """A document without a front-matter title (the shipped guides) keeps its H1."""
    assert codex.title_of("# Companions and Creature Battles\n\ntext\n", "Guides/x.md") \
        == "Companions and Creature Battles"


def test_the_title_falls_back_to_the_file_name(library):
    """Neither a title nor a heading: the file name is still better than a marker line."""
    assert codex.title_of("just text\n", "Items/Copper.md") == "Copper"


def test_a_marker_comment_is_never_a_title(library):
    """The specific regression: a `#` line inside the front matter must never win."""
    text = "---\n# generated: nomanssky-plugin recipes\nstc_owner: nomanssky/generated\n---\n\n# Copper\n"
    assert codex.title_of(text, "Items/Copper.md") == "Copper"


def test_a_title_match_outranks_a_passing_mention(library):
    """Measured on the real 2,388 documents: ranking by word presence put *Dawn's End* above *Chromatic
    Metal* for "chromatic metal", because almost every document mentions a metal somewhere."""
    write(library, {
        "Items/Chromatic Metal.md": "---\ntitle: \"Chromatic Metal\"\n---\n\n# Chromatic Metal\n"
                                    "Refined from Copper.\n",
        "Items/Dawns End.md": "---\ntitle: \"Dawn's End\"\n---\n\n# Dawn's End\n"
                              "A chromatic sword of metal.\n"})
    assert [hit["title"] for hit in library.search("chromatic metal", k=2)][0] == "Chromatic Metal"


def test_a_document_missing_one_word_is_not_a_hit(library):
    """All the query's words have to be there; otherwise a question returns whatever shares one word."""
    write(library, {"A.md": "# Copper\nA metal.\n", "B.md": "# Cadmium\nAnother metal.\n"})
    assert [hit["title"] for hit in library.search("copper metal", k=5)] == ["Copper"]


def test_the_score_is_bounded_and_comparable(library):
    """The page prints it; a score outside 0..1 would be meaningless next to the embedded search's."""
    write(library, {"A.md": "---\ntitle: \"Copper\"\n---\n\n# Copper\nCopper copper copper.\n"})
    score = library.search("copper", k=1)[0]["score"]
    assert 0 < score <= 1
