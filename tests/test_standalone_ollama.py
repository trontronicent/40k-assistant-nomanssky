"""The Ollama client: model listing, streaming chat and embeddings, all over an injected opener."""
import json

import pytest

from standalone import ollama


class FakeResponse:
    """What `urllib.request.urlopen` returns, reduced to what the client uses."""

    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return b"".join(self._lines)


def opener_for(lines):
    def opener(request, timeout):
        return FakeResponse(lines)
    return opener


def test_tags_lists_installed_models():
    """The settings page offers the installed models; a wrong shape here would show an empty picker on a
    machine that does have models."""
    payload = json.dumps({"models": [{"name": "40k-12b-companion:latest"}, {"name": "nomic-embed-text"}]})
    client = ollama.OllamaClient("http://x", opener=opener_for([payload]))
    assert client.tags() == ["40k-12b-companion:latest", "nomic-embed-text"]


def test_chat_stream_yields_content_pieces():
    """Replies stream token by token; the client must yield each `message.content` and stop at `done`."""
    lines = [json.dumps({"message": {"content": "Hel"}}) + "\n",
             json.dumps({"message": {"content": "lo"}}) + "\n",
             json.dumps({"done": True}) + "\n"]
    client = ollama.OllamaClient("http://x", opener=opener_for(lines))
    assert list(client.chat_stream("m", [{"role": "user", "content": "hi"}])) == ["Hel", "lo"]


def test_chat_stream_ignores_a_partial_line():
    """A chunk boundary can split a JSON line. An unparsable line is skipped, never raised, or one bad
    packet ends the reply mid-sentence."""
    lines = ["{not json\n", json.dumps({"message": {"content": "ok"}}) + "\n"]
    client = ollama.OllamaClient("http://x", opener=opener_for(lines))
    assert list(client.chat_stream("m", [])) == ["ok"]


def test_chat_stream_sends_keep_alive_minus_one():
    """A raw request with the default keep_alive resets a model the app deliberately kept resident; the
    standalone host owns its Ollama, but the rule is the same - say what you want, never leave it open."""
    sent = {}

    def opener(request, timeout):
        sent["payload"] = json.loads(request.data)
        return FakeResponse([json.dumps({"done": True})])

    client = ollama.OllamaClient("http://x", opener=opener)
    list(client.chat_stream("m", [], options={"temperature": 0.4}))
    assert sent["payload"]["keep_alive"] == -1
    assert sent["payload"]["options"] == {"temperature": 0.4}
    assert sent["payload"]["stream"] is True


def test_embed_returns_a_vector():
    """The Codex index embeds through Ollama; the shape is asserted so a server change is caught by the
    tests rather than by an empty search."""
    payload = json.dumps({"embeddings": [[0.1, 0.2]]})
    client = ollama.OllamaClient("http://x", opener=opener_for([payload]))
    assert client.embed("nomic-embed-text", ["search_document: x"]) == [[0.1, 0.2]]


def test_embed_refuses_a_short_answer():
    """One vector per text or nothing: a partial answer silently mis-aligns every chunk with its
    document, which would corrupt the whole index."""
    payload = json.dumps({"embeddings": [[0.1]]})
    client = ollama.OllamaClient("http://x", opener=opener_for([payload]))
    with pytest.raises(ollama.OllamaError):
        client.embed("nomic-embed-text", ["a", "b"])


def test_a_connection_failure_becomes_an_ollama_error():
    """Ollama may simply not be running (the user declined AI, or stopped the service). That must be a
    clear typed failure the page can show, not a urllib traceback."""
    def boom(request, timeout):
        raise OSError("connection refused")

    client = ollama.OllamaClient("http://x", opener=boom)
    with pytest.raises(ollama.OllamaError):
        client.tags()


def test_available_is_false_without_a_server():
    """The status route reports whether AI can answer; `available()` must be a quick, non-raising probe,
    and a closed localhost port takes ~2 s on Windows, so it carries a short timeout."""
    def boom(request, timeout):
        assert timeout <= ollama.PROBE_TIMEOUT_S
        raise OSError("refused")

    client = ollama.OllamaClient("http://x", opener=boom)
    assert client.available() is False


def test_available_is_true_with_a_server():
    """The positive case matters too: the settings page refuses to turn AI on without it."""
    client = ollama.OllamaClient("http://x", opener=opener_for(['{"models": []}']))
    assert client.available() is True


def test_has_model_ignores_the_latest_tag():
    """`ollama create` names the model `40k-12b-companion`, `ollama list` may show
    `40k-12b-companion:latest`; comparing the raw strings would report the shipped model as missing."""
    client = ollama.OllamaClient("http://x", opener=opener_for(['{"models": [{"name": "40k-12b-companion:latest"}]}']))
    assert client.has_model("40k-12b-companion") is True
    assert client.has_model("gemma4:12b") is False
