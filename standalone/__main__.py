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

from standalone import config, ollama, paths, routes, server
from standalone.runner import LoopBridge, Runner

log = logging.getLogger("nms-standalone")

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


def build_deps(runner: Runner, data: Path, root: Path, version: str, codex) -> routes.Deps:
    """Everything the routes need. Each optional feature is present exactly when it is installed and
    switched on, so the page can hide what this install cannot do."""
    settings = config.load(paths.settings_file(data))
    chat_service = None
    if settings.ai_enabled and settings.chat_model:
        from standalone.chat import ChatService
        client = ollama.OllamaClient(settings.ollama_url)
        chat_service = ChatService(runner.plugin, client, settings.chat_model, codex=codex)
    return routes.Deps(
        plugin=runner.plugin,
        bridge=None,                      # set by `serve` once the loop is known
        assets_dir=runner.ctx.assets_dir,
        settings_path=paths.settings_file(data),
        web_dir=root / "standalone" / "web",
        version=version,
        chat=chat_service,
        codex=codex,
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


async def serve(args) -> None:
    root = paths.install_root()
    data = paths.data_dir()
    setup_logging(paths.log_file(data))
    settings = config.load(paths.settings_file(data))
    version = installed_version(root)
    port = choose_port(args.port or settings.port)

    runner = Runner(root, paths.plugin_data_dir(data), codex=build_codex(data, settings), version=version)
    await runner.start()
    deps = build_deps(runner, data, root, version, runner.ctx.codex)
    deps.bridge = LoopBridge(asyncio.get_running_loop())

    httpd = server.build(routes.build(deps), port)
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    log.info("the standalone host is serving http://127.0.0.1:%s (v%s)", port, version)
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")
    try:
        await asyncio.Event().wait()           # until the process is asked to exit
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
