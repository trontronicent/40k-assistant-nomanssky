"""The standalone host's HTTP handlers.

One `Deps` object instead of a long parameter list, one small function per route, and the table at the
end - the shape `code-shape.md` asks for. Every call into the connector goes through `Deps.bridge`, so
it runs on the host's loop and never races the 5 s tick.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from urllib.parse import unquote

from standalone import config
from standalone.runner import on_loop
from standalone.server import HttpError, Request, Response, Route, error_response, json_response

ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
ICON_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}\.png$")
WEB_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
MAX_PARAMS = 50
MAX_PARAM_TEXT = 2000
VIEW_TIMEOUT_S = 15.0
ACTION_TIMEOUT_S = 120.0

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
    updater: object = None         # standalone.updater.Updater
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
        Route("GET", r"/(?:|([A-Za-z0-9._-]+))$", bind(_web)),
    ]
