"""Starts the standalone host: one asyncio loop for the connector, one HTTP thread for the page.

    python -m standalone [--port N] [--no-browser] [--no-overlay] [--no-tray]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import socket
import threading
import webbrowser
from pathlib import Path

from standalone import config, instance, ollama, paths, routes, server
from standalone.runner import LoopBridge, Runner

log = logging.getLogger("nms-standalone")

# Set in `serve`; the tray's Quit sets it from its own thread through `call_soon_threadsafe`.
_shutdown: asyncio.Event | None = None

PORT_PROBE_TIMEOUT_S = 0.3        # a closed localhost port costs ~2 s on Windows without this
PORT_TRIES = 20
LOG_BYTES = 2_000_000


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="nms-companion", description="No Man's Sky Companion")
    parser.add_argument("--port", type=int, default=None, help="serve on this port instead of the saved one")
    parser.add_argument("--no-browser", action="store_true", help="do not open the page (autostart)")
    parser.add_argument("--no-overlay", action="store_true", help="do not start the game overlay")
    parser.add_argument("--no-tray", action="store_true", help="do not show a tray icon")
    return parser.parse_args(argv)


def installed_version(root: Path) -> str:
    """The version from the manifest - the same file the release recipe bumps."""
    try:
        return str(json.loads((root / "strategicum-plugin.json").read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError):
        log.warning("could not read the version from the manifest in %s", root)
        return "unknown"


def port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(PORT_PROBE_TIMEOUT_S)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def choose_port(preferred: int) -> int:
    for port in range(preferred, preferred + PORT_TRIES):
        if port_is_free(port):
            return port
    raise RuntimeError(f"no free port in {preferred}..{preferred + PORT_TRIES}")


def bind_server(route_table, preferred: int):
    """Bind the server, falling forward over taken ports. The probe in `choose_port` is an optimisation;
    the bind is the decision, because a port can be taken between the two."""
    last = None
    for port in range(preferred, preferred + PORT_TRIES):
        try:
            return server.build(route_table, port), port
        except OSError as err:
            last = err
            log.info("port %s is taken, trying the next one", port)
    raise RuntimeError(f"no free port in {preferred}..{preferred + PORT_TRIES}: {last}")


def setup_logging(path: Path) -> None:
    """A rotating file handler owned by this process only - never a shell redirect into the same file
    (`Start-Process -RedirectStandardOutput` opens its own handle and the two writers overwrite each
    other's lines: 39 % were lost when the app did it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler, logging.StreamHandler()]
    root.setLevel(logging.INFO)


def build_deps(runner: Runner, data: Path, root: Path, version: str, codex) -> routes.Deps:  # noqa: PLR0913
    """Everything the routes need. Each optional feature is present exactly when it is installed and
    switched on, so the page can hide what this install cannot do."""
    settings = config.load(paths.settings_file(data))
    chat_service = None
    if settings.ai_enabled and settings.chat_model:
        from standalone.chat import ChatService
        client = ollama.OllamaClient(settings.ollama_url)
        chat_service = ChatService(runner.plugin, client, settings.chat_model, codex=codex)
    from standalone.updates_service import UpdatesService
    updates = UpdatesService(root, data, version, settings.update_channel)
    voice = None
    if settings.tts_enabled:
        from standalone.tts import from_settings
        voice = from_settings(data, settings.voice)
    return routes.Deps(
        plugin=runner.plugin,
        bridge=None,                      # set by `serve` once the loop is known
        assets_dir=runner.ctx.assets_dir,
        settings_path=paths.settings_file(data),
        web_dir=root / "standalone" / "web",
        version=version,
        chat=chat_service,
        codex=codex,
        tts=voice,
        updater=updates,
        probe=ollama.OllamaClient(settings.ollama_url),
    )


def build_codex(data: Path, settings: config.Settings):
    """The Codex channel the connector writes its documents through - `None` turns it off entirely
    (`ctx.codex is None` is how the app says "you may not write")."""
    if not settings.codex_enabled:
        return None
    from standalone.codex import StandaloneCodex
    from standalone.codex_index import CodexIndex
    index = None
    if settings.ai_enabled:
        index = CodexIndex(paths.codex_dir(data), ollama.OllamaClient(settings.ollama_url),
                           settings.embed_model)
    return StandaloneCodex(paths.codex_dir(data), index=index)


def start_overlay(port: int) -> None:
    """Launch the game overlay as its own process: a tkinter main loop cannot share this one, and a slow
    redraw must never touch the connector's loop. Never waited on; it is the user's window to close."""
    import subprocess
    import sys
    command = [sys.executable, "-m", "standalone.overlay", "--port", str(port)]
    try:
        subprocess.Popen(command, cwd=str(paths.install_root()))     # noqa: S603 - our own module
        log.info("the overlay was started on port %s", port)
    except OSError as err:
        log.warning("the overlay could not be started: %s", err)


def _finish_pending(root: Path, data: Path, version: str, settings: config.Settings) -> str | None:
    """After an update: clear the pending marker, or roll back if the new code did not come up."""
    from standalone.updates_service import UpdatesService
    return UpdatesService(root, data, version, settings.update_channel).finish_pending()


async def serve(args) -> None:
    global _shutdown
    _shutdown = asyncio.Event()
    root = paths.install_root()
    data = paths.data_dir()
    setup_logging(paths.log_file(data))
    settings = config.load(paths.settings_file(data))
    version = installed_version(root)
    already = instance.running_port(data)
    if already is not None:
        log.info("the companion is already running on port %s; opening its page", already)
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{already}")
        return

    rolled_back = _finish_pending(root, data, version, settings)
    if rolled_back:
        log.error("%s", rolled_back)
    runner = Runner(root, paths.plugin_data_dir(data), codex=build_codex(data, settings), version=version)
    await runner.start()
    deps = build_deps(runner, data, root, version, runner.ctx.codex)
    deps.bridge = LoopBridge(asyncio.get_running_loop())

    httpd, port = bind_server(routes.build(deps), args.port or settings.port)
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    log.info("the standalone host is serving http://127.0.0.1:%s (v%s)", port, version)
    with instance.hold(data, port):
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{port}")
        if settings.overlay_enabled and not args.no_overlay:
            start_overlay(port)
        if settings.tray_enabled and not args.no_tray:
            from standalone import tray
            stop = asyncio.get_running_loop()
            tray.start(port, data, root, on_quit=lambda: stop.call_soon_threadsafe(_shutdown.set))
        try:
            await _shutdown.wait()             # until Quit in the tray, or the process is stopped
        finally:
            httpd.shutdown()
            await runner.stop()


def main() -> None:
    try:
        asyncio.run(serve(parse_args()))
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
