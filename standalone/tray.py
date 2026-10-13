"""The Windows tray icon (pystray).

Decisions live in `tray_menu`; this module only talks to pystray, the host's own HTTP API and the shell.
Two lessons carried over from the app's tray (`src/tray/app.py`):

* **pystray inspects a callback's arity** and calls it with `(icon, item)`. A handler with a different
  signature is silently never run, so every handler is built by `make_handler`.
* The menu is a **callable**, so `update_menu()` re-reads the state without rebuilding the icon.

The icon also carries the alerts: `AlertWatcher` polls the host's `/api/overlay` and raises a balloon per
finished timer, which is the only alert path when no page is open (the autostart entry opens none).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from standalone import alerts, tray_menu

log = logging.getLogger("nms-standalone.tray")

POLL_S = 5.0
POLL_TIMEOUT_S = 3.0
ICON_NAME = "favicon.ico"


def make_handler(action):
    """A pystray callback with exactly the `(icon, item)` signature it inspects for.

    A failure is logged: an exception inside a callback disappears into the Win32 message loop, and a
    broken entry would look like a frozen tray.
    """
    def handler(icon, item):      # noqa: ARG001 - pystray inspects this exact signature
        try:
            action()
        except Exception:                      # noqa: BLE001 - logged; the loop must keep running
            log.exception("a tray action failed")
    return handler


class AlertWatcher:
    """Raises one balloon per finished timer, using the same rule the page uses (`standalone.alerts`)."""

    def __init__(self, notify, state=None):
        self.notify = notify
        self.state = state or alerts.new_state()

    def poll(self, payload: dict, now: float) -> list[dict]:
        finished = alerts.due(self.state, alerts.collect(payload), now)
        for timer in finished:
            try:
                self.notify(timer.get("label") or "Timer", "finished")
            except Exception:                  # noqa: BLE001 - a balloon is optional, the poll is not
                log.warning("the alert could not be shown", exc_info=True)
        return finished


class TrayIcon:
    """The icon itself; `run()` blocks in pystray's Win32 message loop, so it gets its own thread."""

    def __init__(self, port: int, data_dir: Path, install: Path, on_quit=None):
        self.port = port
        self.data_dir = Path(data_dir)
        self.install = Path(install)
        self.on_quit = on_quit
        self.icon = None
        self.overlay_on = True
        self.update: str | None = None
        self.watcher = AlertWatcher(self._balloon)
        self.overlay_on = True
        self._actions = {
            "open_page": lambda: self._open(f"http://127.0.0.1:{self.port}"),
            "open_chat": lambda: self._open(f"http://127.0.0.1:{self.port}#chat"),
            "toggle_overlay": self._toggle_overlay,
            "rescan": lambda: self._send("/api/actions/rescan", {"params": {}}),
            "check_updates": lambda: self._open(f"http://127.0.0.1:{self.port}#updates"),
            "open_data_folder": lambda: self._open(str(self.data_dir)),
            "open_log": lambda: self._open(str(self.data_dir / "standalone.log")),
            "restart": self._restart,
            "quit": self._quit,
        }

    # ---- the host ---------------------------------------------------------

    def _get(self, path: str) -> dict:
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=POLL_TIMEOUT_S) as response:
            return json.loads(response.read())

    def _send(self, path: str, body: dict, method: str = "POST") -> dict:
        """Menu actions go through the host's own API, so there is one code path for every caller."""
        url = f"http://127.0.0.1:{self.port}{path}"
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    # ---- actions ----------------------------------------------------------

    @staticmethod
    def _open(target: str) -> None:
        os.startfile(target)                   # noqa: S606 - a local page, folder or log file

    def _toggle_overlay(self) -> None:
        """The setting is the host's; the tray only asks for the change and follows the answer."""
        wanted = not self.overlay_on
        self._send("/api/settings", {"overlay_enabled": wanted}, method="PUT")
        self.overlay_on = wanted
        log.info("the overlay switch is now %s", wanted)

    def _restart(self) -> None:
        subprocess.Popen([sys.executable, "-m", "standalone", "--no-browser"],  # noqa: S603 - our module
                         cwd=str(self.install))
        self._quit()

    def _quit(self) -> None:
        if self.icon is not None:
            self.icon.stop()
        if self.on_quit is not None:
            self.on_quit()

    def _balloon(self, title: str, text: str) -> None:
        if self.icon is not None and hasattr(self.icon, "notify"):
            self.icon.notify(text, title)

    # ---- pystray glue -----------------------------------------------------

    def _items(self):
        """Called by pystray whenever it draws the menu, so the state is always current."""
        import pystray
        out = []
        for entry in tray_menu.build_menu(self.overlay_on, self._ai_enabled(), self.update):
            if entry.kind == "separator":
                out.append(pystray.Menu.SEPARATOR)
                continue
            action = self._actions.get(entry.local or "")
            out.append(pystray.MenuItem(
                entry.text, make_handler(action) if action else None,
                checked=(lambda item, e=entry: e.checked) if entry.kind == "check" else None,
                default=entry.default, enabled=entry.enabled))
        return out

    def _ai_enabled(self) -> bool:
        try:
            status = self._get("/api/status")
        except Exception:                      # noqa: BLE001 - the host may still be starting
            return False
        self.overlay_on = bool(status.get("overlay_enabled", self.overlay_on))
        return bool(status.get("ai_enabled"))

    def _poll(self) -> None:
        """Alerts and the update hint, every `POLL_S` while the icon lives."""
        import time
        while self.icon is not None and getattr(self.icon, "visible", True):
            try:
                self.watcher.poll(self._get("/api/overlay"), time.time())
            except Exception as err:           # noqa: BLE001 - the host restarts during an update
                log.debug("the tray could not poll the host: %s", err)
            time.sleep(POLL_S)

    def run(self) -> None:
        import pystray
        from PIL import Image
        icon_path = self.install / "standalone" / "web" / ICON_NAME
        image = Image.open(icon_path) if icon_path.is_file() else Image.new("RGB", (32, 32), "#d9a13b")
        self.icon = pystray.Icon("nms-companion", image,
                                 tray_menu.tooltip("ready", self.port),
                                 menu=pystray.Menu(self._items))
        threading.Thread(target=self._poll, name="tray-poll", daemon=True).start()
        self.icon.run()


def start(port: int, data_dir: Path, install: Path, on_quit=None):
    """Start the icon on its own thread; returns the `TrayIcon` or None when pystray is missing."""
    try:
        import pystray                         # noqa: F401 - checked here so the host can go on without it
    except ImportError:
        log.info("pystray is not installed; the tray icon is skipped")
        return None
    if not sys.platform.startswith("win"):
        log.info("the tray icon is a Windows feature; skipped on %s", sys.platform)
        return None
    icon = TrayIcon(port, data_dir, install, on_quit=on_quit)
    threading.Thread(target=icon.run, name="tray", daemon=True).start()
    return icon
