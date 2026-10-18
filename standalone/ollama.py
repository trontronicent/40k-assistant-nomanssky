"""Talks to a local Ollama.

stdlib only (`urllib.request`): the standalone install ships no third-party HTTP client. Every entry
point either answers or raises `OllamaError`; `available()` never raises at all.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator

log = logging.getLogger("nms-standalone.ollama")

PROBE_TIMEOUT_S = 2.0        # a closed localhost port costs ~2 s on Windows: probe, do not call blind
TAGS_TIMEOUT_S = 10.0
CHAT_TIMEOUT_S = 600.0       # a cold 12B model next to the running game takes minutes
EMBED_TIMEOUT_S = 300.0

# Say what we want instead of leaving it to the server's default: a bare request resets a keep_alive
# someone else chose (measured in the app, which lost its unload-OFF setting to a raw probe).
KEEP_ALIVE = -1


class OllamaError(RuntimeError):
    """Ollama could not be reached or answered something unusable."""


def _default_opener(request, timeout):
    return urllib.request.urlopen(request, timeout=timeout)


class OllamaClient:
    def __init__(self, base_url: str, opener: Callable = _default_opener):
        self.base_url = (base_url or "").rstrip("/")
        self._open = opener

    # ---- plumbing ---------------------------------------------------------

    def _post(self, path: str, payload: dict, timeout: float):
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            return self._open(request, timeout)
        except (OSError, urllib.error.URLError) as err:
            raise OllamaError(f"Ollama at {self.base_url} did not answer: {err}") from err

    # ---- models -----------------------------------------------------------

    def tags(self) -> list[str]:
        """The installed models, as `ollama list` shows them."""
        request = urllib.request.Request(f"{self.base_url}/api/tags")
        try:
            with self._open(request, TAGS_TIMEOUT_S) as response:
                data = json.loads(response.read())
        except (OSError, urllib.error.URLError, ValueError) as err:
            raise OllamaError(f"could not list models: {err}") from err
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    def has_model(self, name: str) -> bool:
        """Whether that model is installed, comparing without the `:latest` tag Ollama adds."""
        wanted = name.split(":")[0]
        try:
            return any(tag.split(":")[0] == wanted for tag in self.tags())
        except OllamaError:
            return False

    def available(self) -> bool:
        """A short, non-raising probe for the status route."""
        request = urllib.request.Request(f"{self.base_url}/api/tags")
        try:
            with self._open(request, PROBE_TIMEOUT_S):
                return True
        except Exception:                      # noqa: BLE001 - a probe; debug on purpose
            log.debug("Ollama is not reachable at %s", self.base_url)
            return False

    # ---- inference --------------------------------------------------------

    def chat_stream(self, model: str, messages: list[dict], options: dict | None = None) -> Iterator[str]:
        """Yield the reply's content pieces. Unparsable lines are skipped (a chunk boundary can split
        one); `done` ends the stream."""
        payload = {"model": model, "messages": messages, "stream": True,
                   "options": options or {}, "keep_alive": KEEP_ALIVE}
        with self._post("/api/chat", payload, CHAT_TIMEOUT_S) as response:
            for raw in response:
                piece, done = self._stream_event(raw)
                if piece:
                    yield piece
                if done:
                    return

    @staticmethod
    def _stream_event(raw: bytes) -> tuple[str, bool]:
        """One NDJSON line as `(content, done)`; an unreadable line is `("", False)`."""
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            return "", False
        try:
            event = json.loads(line)
        except ValueError:
            log.debug("skipped an unparsable stream line")
            return "", False
        return (event.get("message") or {}).get("content") or "", bool(event.get("done"))

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """One request for the whole batch: every request cold-loads the model, so the request count is
        what costs time (the app measured 10 files -> 1 request after batching)."""
        with self._post("/api/embed", {"model": model, "input": texts,
                                       "keep_alive": KEEP_ALIVE}, EMBED_TIMEOUT_S) as response:
            data = json.loads(response.read())
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise OllamaError("Ollama returned no usable embeddings")
        return vectors
