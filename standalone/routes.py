"""The standalone host's HTTP handlers.

One `Deps` object instead of a long parameter list, one small function per route, and the table at the
end - the shape `code-shape.md` asks for. Every call into the connector goes through `Deps.bridge`, so
it runs on the host's loop and never races the 5 s tick.
"""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from urllib.parse import unquote

from standalone import config
from standalone.runner import on_loop
from standalone.server import HttpError, Request, Response, Route, error_response, json_response

ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
ICON_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}\.png$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]{1,40})?$")
WEB_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
MAX_PARAMS = 50
MAX_PARAM_TEXT = 2000
VIEW_TIMEOUT_S = 15.0
ACTION_TIMEOUT_S = 120.0
CHAT_PREPARE_TIMEOUT_S = 30.0
CHAT_MAX_CHARS = 4000
MAX_HISTORY_ENTRIES = 40
MAX_CODEX_TITLES = 50
MAX_CODEX_HITS = 5
MAX_QUERY_CHARS = 500
MAX_HIT_CHARS = 1200
TTS_TIMEOUT_S = 90.0

WEB_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
             ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
             ".png": "image/png", ".ico": "image/x-icon"}


@dataclasses.dataclass
class Deps:
    """Everything the handlers need; one object so no handler takes more than two parameters."""

    plugin: object
    bridge: object
    assets_dir: Path
    settings_path: Path
    web_dir: Path
    version: str
    chat: object = None            # standalone.chat.ChatService, None without AI
    codex: object = None           # standalone.codex.StandaloneCodex, None when the Codex is off
    updater: object = None         # standalone.updates_service.UpdatesService
    probe: object = None           # an OllamaClient used to check before switching AI on
    tts: object = None             # standalone.tts.PiperVoice, None without voice

    @property
    def settings(self) -> config.Settings:
        return config.load(self.settings_path)


def check_params(raw) -> dict:
    """Bound an action's params like the app's `router.check_params`: a flat object of short scalars."""
    params = raw if isinstance(raw, dict) else {}
    if len(params) > MAX_PARAMS:
        raise HttpError(422, "too many params")
    for key, value in params.items():
        if not isinstance(key, str) or not key:
            raise HttpError(422, "a param key must be a non-empty string")
        if isinstance(value, str) and len(value) > MAX_PARAM_TEXT:
            raise HttpError(422, f"param {key} is too long")
        if isinstance(value, (dict, list)):
            raise HttpError(422, f"param {key} must be a scalar")
        if isinstance(value, float) and value != value:
            raise HttpError(422, f"param {key} must be finite")
    return params


def _view(deps: Deps, _request: Request) -> Response:
    """The connector's own view, passed through unchanged."""
    return json_response(deps.bridge.call(on_loop(deps.plugin.view), VIEW_TIMEOUT_S))


def _action(deps: Deps, request: Request) -> Response:
    action_id = request.path_args[0]
    if not ACTION_ID_RE.match(action_id):
        return error_response(422, "bad action id")
    params = check_params(request.body.get("params"))
    result = deps.bridge.call(deps.plugin.action(action_id, params), ACTION_TIMEOUT_S)
    return json_response(result if isinstance(result, dict) else {})


def _asset(deps: Deps, request: Request) -> Response:
    name = unquote(request.path_args[0])
    if not ICON_NAME_RE.match(name):
        return error_response(404, "unknown asset")
    path = (deps.assets_dir / name).resolve()
    if path.parent != deps.assets_dir.resolve() or not path.is_file():
        return error_response(404, "unknown asset")
    return Response(body=path.read_bytes(), content_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


def _item_icons(deps: Deps, _request: Request) -> Response:
    if not hasattr(deps.plugin, "item_icons"):
        return json_response({"icons": {}})
    icons = deps.bridge.call(on_loop(deps.plugin.item_icons), VIEW_TIMEOUT_S)
    return json_response({"icons": icons if isinstance(icons, dict) else {}})


def _overlay(deps: Deps, _request: Request) -> Response:
    payload = deps.bridge.call(on_loop(deps.plugin.overlay), VIEW_TIMEOUT_S)
    return json_response(payload or {})


def _status(deps: Deps, _request: Request) -> Response:
    settings = deps.settings
    return json_response({
        "version": deps.version,
        "ai_enabled": bool(settings.ai_enabled and deps.chat is not None),
        "chat_model": settings.chat_model,
        "tts_enabled": bool(settings.tts_enabled and deps.tts is not None),
        "codex_enabled": bool(settings.codex_enabled and deps.codex is not None),
        "overlay_enabled": settings.overlay_enabled,
        "update_channel": settings.update_channel,
    })


# Changing these only takes effect on the next start; the page says so instead of looking inert.
RESTART_KEYS = ("port", "overlay_enabled", "tray_enabled", "codex_enabled", "ai_enabled", "tts_enabled")
MIN_PORT = 1024
MAX_PORT = 65535


# What each setting type accepts, and the refusal when a value is not that (bool is an int in Python: refused).
TYPE_CHECKS = {
    "bool": (lambda v: isinstance(v, bool), "must be true or false"),
    "int": (lambda v: isinstance(v, int) and not isinstance(v, bool), "must be a whole number"),
    "str": (lambda v: isinstance(v, str), "must be text"),
}


def _check_type(key: str, value) -> None:
    """HttpError 422 unless `key` is a setting and `value` has its type."""
    if key not in config.FIELD_TYPES:
        raise HttpError(422, f"unknown setting {key!r}")
    accepts, refusal = TYPE_CHECKS.get(config.FIELD_TYPES[key], (lambda v: True, ""))
    if not accepts(value):
        raise HttpError(422, f"{key} {refusal}")


def check_settings(changes: dict) -> dict:
    """Validate a settings change against the dataclass. Unknown keys and wrong types are refused, so a
    bad write cannot make the next start fall back to the defaults."""
    if not isinstance(changes, dict) or not changes:
        raise HttpError(422, "send at least one setting")
    for key, value in changes.items():
        _check_type(key, value)
    checked = dict(changes)
    port = checked.get("port")
    if port is not None and not MIN_PORT <= port <= MAX_PORT:
        raise HttpError(422, f"the port must be between {MIN_PORT} and {MAX_PORT}")
    channel = checked.get("update_channel")
    if channel is not None and channel not in config.CHANNELS:
        raise HttpError(422, f"the channel must be one of {list(config.CHANNELS)}")
    return checked


def _settings_state(deps: Deps, _request: Request) -> Response:
    """What the settings panel draws from."""
    return json_response({"settings": config.as_dict(deps.settings)})


def _settings(deps: Deps, request: Request) -> Response:
    """Change one or more settings. Turning AI on is checked against a running Ollama first: a chat box
    that fails on every message is worse than a refusal that says why."""
    changes = check_settings(request.body)
    if changes.get("ai_enabled") and not _ollama_ready(deps):
        return error_response(409, "Ollama did not answer; install the AI assistant or start Ollama first")
    settings = config.replace(deps.settings, changes)
    config.save(deps.settings_path, settings)
    return json_response({"ok": True, "settings": config.as_dict(settings),
                          "restart_needed": any(key in RESTART_KEYS for key in changes)})


def _ollama_ready(deps: Deps) -> bool:
    return bool(deps.probe is not None and deps.probe.available())


def _models(deps: Deps, _request: Request) -> Response:
    """The models Ollama has, for the settings picker."""
    if deps.probe is None or not deps.probe.available():
        return json_response({"models": [], "available": False})
    try:
        return json_response({"models": deps.probe.tags(), "available": True})
    except Exception as err:               # noqa: BLE001 - shown in the picker, logged by the server
        return json_response({"models": [], "available": False, "detail": str(err)})


def _updates(deps: Deps, _request: Request) -> Response:
    """The versions this install can move to, each labelled update / downgrade / installed."""
    from standalone.updater import UpdateError
    if deps.updater is None:
        return error_response(503, "this install cannot update itself")
    try:
        return json_response(deps.updater.versions())
    except UpdateError as err:
        return error_response(502, str(err))


def _update_install(deps: Deps, request: Request) -> Response:
    """Install another version. The swap itself happens in a helper process after this one exits."""
    from standalone.updater import UpdateError
    if deps.updater is None:
        return error_response(503, "this install cannot update itself")
    version = request.body.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        return error_response(422, "version must be a version string")
    try:
        return json_response(deps.updater.install_version(version,
                                                          bool(request.body.get("confirm_data"))))
    except UpdateError as err:
        return error_response(502, str(err))


def _tts(deps: Deps, request: Request) -> Response:
    """Speak one reply. The page plays the answer as a blob; a failure carries Piper's own message."""
    from standalone.tts import TtsError, spoken_text
    if deps.tts is None or not deps.tts.is_installed():
        return error_response(503, "spoken replies are not installed")
    text = spoken_text(request.body.get("text") if isinstance(request.body.get("text"), str) else "")
    if not text:
        return error_response(422, "text must be a non-empty string")
    try:
        audio = deps.bridge.call(deps.tts.speak(text), TTS_TIMEOUT_S)
    except TtsError as err:
        return error_response(502, str(err))
    return Response(body=audio, content_type="audio/wav")


def _codex(deps: Deps, _request: Request) -> Response:
    """What the Codex holds, for the page's Codex box."""
    if deps.codex is None:
        return error_response(404, "this install keeps no Codex")
    documents = deps.codex.documents()
    return json_response({
        "library": deps.codex.library,
        "documents": len(documents),
        "titles": [doc["title"] for doc in documents[:MAX_CODEX_TITLES]],
        "hidden": deps.codex.hidden(),
    })


def _codex_search(deps: Deps, request: Request) -> Response:
    if deps.codex is None:
        return error_response(404, "this install keeps no Codex")
    query = request.body.get("query")
    if not isinstance(query, str) or not query.strip():
        return error_response(422, "query must be a non-empty string")
    hits = deps.codex.search(query.strip()[:MAX_QUERY_CHARS], k=MAX_CODEX_HITS)
    return json_response({"hits": [{"title": hit.get("title"), "path": hit.get("path"),
                                    "text": (hit.get("text") or "")[:MAX_HIT_CHARS],
                                    "score": hit.get("score")} for hit in hits]})


def _codex_restore(deps: Deps, _request: Request) -> Response:
    """Forget the tombstones, so documents the user deleted are written again."""
    if deps.codex is None:
        return error_response(404, "this install keeps no Codex")
    deps.codex.restore()
    return json_response({"ok": True, "message": "Deleted documents will be written again."})


def _sse(payload: dict) -> bytes:
    """One server-sent event: `data: <json>` and a blank line, the convention the app's chat uses."""
    return ("data: " + json.dumps(payload) + "\n\n").encode("utf-8")


def _history(raw) -> list[dict]:
    """The page sends the conversation back on every turn; keep only well-formed, bounded entries."""
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw[-MAX_HISTORY_ENTRIES:]:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content[:CHAT_MAX_CHARS]})
    return out


def _chat(deps: Deps, request: Request) -> Response:
    """Stream a reply: `{"token": ...}` events, then one `{"done": true, "recipes": [...]}`.

    The recipes are data for the page's diagrams and are never prompted - a model asked to repeat
    "A + B -> C" verbatim still mangled it (the app's chat tests, 2026-10-10/11).
    """
    if deps.chat is None:
        return error_response(503, "the AI assistant is not installed")
    message = request.body.get("message")
    if not isinstance(message, str) or not message.strip():
        return error_response(422, "message must be a non-empty string")
    plan = deps.bridge.call(deps.chat.prepare(message.strip()[:CHAT_MAX_CHARS],
                                              _history(request.body.get("history"))),
                            CHAT_PREPARE_TIMEOUT_S)

    def stream(write):
        try:
            for token in deps.chat.tokens(plan):
                write(_sse({"token": token}))
        except Exception as err:               # noqa: BLE001 - shown to the page, logged by the server
            write(_sse({"error": str(err)}))
            raise
        write(_sse({"done": True, "recipes": plan.recipes}))

    return Response(stream=stream)


def _web(deps: Deps, request: Request) -> Response:
    """The page itself. Only files directly inside `web/`, and only known extensions."""
    name = unquote(request.path_args[0] or "") or "index.html"
    if not WEB_NAME_RE.match(name):
        return error_response(404, "not found")
    path = (deps.web_dir / name).resolve()
    if path.parent != deps.web_dir.resolve() or not path.is_file():
        return error_response(404, "not found")
    content_type = WEB_TYPES.get(path.suffix)
    if content_type is None:
        return error_response(404, "not found")
    return Response(body=path.read_bytes(), content_type=content_type)


def build(deps: Deps) -> list[Route]:
    """The route table. Chat, TTS, Codex and update routes are appended by their own modules."""
    def bind(fn):
        return lambda request: fn(deps, request)

    return [
        Route("GET", r"/api/view$", bind(_view)),
        Route("POST", r"/api/actions/([^/]+)$", bind(_action)),
        Route("GET", r"/api/assets/([^/]+)$", bind(_asset)),
        Route("GET", r"/api/item-icons$", bind(_item_icons)),
        Route("GET", r"/api/overlay$", bind(_overlay)),
        Route("GET", r"/api/status$", bind(_status)),
        Route("POST", r"/api/chat$", bind(_chat)),
        Route("POST", r"/api/tts$", bind(_tts)),
        Route("GET", r"/api/settings$", bind(_settings_state)),
        Route("PUT", r"/api/settings$", bind(_settings)),
        Route("GET", r"/api/models$", bind(_models)),
        Route("GET", r"/api/updates$", bind(_updates)),
        Route("POST", r"/api/updates/install$", bind(_update_install)),
        Route("GET", r"/api/codex$", bind(_codex)),
        Route("POST", r"/api/codex/search$", bind(_codex_search)),
        Route("POST", r"/api/codex/restore$", bind(_codex_restore)),
        Route("GET", r"/(?:|([A-Za-z0-9._-]+))$", bind(_web)),
    ]
