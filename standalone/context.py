"""The context the standalone host hands the connector: the same attribute names the app's
`plugins/loader.PluginContext` provides, so `nms_connector` needs no standalone branch anywhere.

Adding something here means the app provides it too (or the connector may not rely on it) - see
CLAUDE.md, "two hosts, one codebase".
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from collections.abc import Coroutine

# Every section type the standalone page renders. The connector checks this to decide between a `timers`
# section and a plain table, so it must list what `standalone/web/sections.js` actually draws
# (tests/test_host_contract.py compares the two).
SECTION_TYPES = ("notice", "stats", "kv", "table", "list", "text", "tabs", "orbit", "starmap",
                 "form", "timers", "recipes")

# What the connector may assume of its host. Kept at the app version whose features this host
# implements; raising the manifest's `app.min_version` means raising this with it.
APP_VERSION = "3.19.0"


class StandaloneContext:
    """What the standalone host gives the connector."""

    def __init__(self, plugin_id: str, version: str, root: Path, data_dir: Path, codex=None,
                 logger: logging.Logger | None = None):
        self.plugin_id = plugin_id
        self.version = version
        # Which host this is, for anything the connector writes that names where it came from (the data
        # archives of transfer.py). The app's context has no such attribute; the connector defaults to
        # "plugin" without it, so this stays additive.
        self.host = "standalone"
        self.root = Path(root)
        self.data_dir = Path(data_dir)
        self.assets_dir = self.data_dir / "assets"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger or logging.getLogger("nms-standalone.plugin")
        self.app_version = APP_VERSION
        self.section_types = SECTION_TYPES
        self.codex = codex
        self._tasks: set[asyncio.Task] = set()

    def spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task:
        """Start a background task the host cancels on stop. The set keeps a strong reference: the event
        loop holds only a weak one, so an unreferenced task can be collected mid-execution."""
        task = asyncio.get_running_loop().create_task(coro, name=f"plugin-{self.plugin_id}-{name}")
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task) -> None:
        """Log a crash; a cancellation is expected and stays quiet."""
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self.logger.error("background task %s crashed", task.get_name(), exc_info=error)

    async def run_blocking(self, fn, *args, **kwargs):
        """Run blocking work (file reads, decoding, memory scans) off the event loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def cancel_tasks(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
