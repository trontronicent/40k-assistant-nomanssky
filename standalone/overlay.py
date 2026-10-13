"""The standalone game overlay: a small always-on-top window over No Man's Sky.

`tkinter` and `ctypes` only, like the app's own overlay, and a separate process so a slow redraw can
never touch the connector's loop. It polls the host's `/api/overlay` - exactly what the page reads - and
draws the connector's areas. **The user owns which areas are shown**; the plugin only supplies
`default_on`, and the choice lives in `<data>/overlay.json`.

    python -m standalone.overlay --port 8787

Two keys of the payload are deliberately unused here: `persona_id` and `codeword` exist so the app's
overlay can switch Live Comms to the plugin's persona and set its wake word. The standalone host has no
Live Comms and only one persona - the chat page always talks to it - so there is nothing to switch.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
import urllib.request
from pathlib import Path

from standalone import alerts, paths

log = logging.getLogger("nms-standalone.overlay")

POLL_S = 2.0
POLL_TIMEOUT_S = 3.0
MAX_AREA_LINES = 12          # the app's MAX_AREA_LINES
MAX_LINE_CHARS = 160
FALLBACK_AREA_ID = "plugin"  # where a pre-3.12.0 payload's timers and lines go
MAX_TOGGLES = 4              # the app's MAX_TOGGLES
ALPHA = 0.85
CHOICES_NAME = "overlay.json"


# --------------------------------------------------------------------------- pure parts


def overlay_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/overlay"


def visible_areas(payload: dict, choices: dict) -> list[dict]:
    """The areas to draw: the plugin's, filtered by the user's choice (its `default_on` when they have
    not chosen). A payload without `areas` falls back to the top-level timers and lines."""
    payload = payload if isinstance(payload, dict) else {}
    areas = [area for area in (payload.get("areas") or [])
             if isinstance(area, dict) and area.get("id") and area.get("title")]
    if not areas:
        if not (payload.get("timers") or payload.get("lines")):
            return []
        areas = [{"id": FALLBACK_AREA_ID, "title": payload.get("title") or "No Man's Sky",
                  "timers": payload.get("timers") or [], "lines": payload.get("lines") or [],
                  "default_on": True}]
    return [area for area in areas
            if choices.get(area["id"], bool(area.get("default_on", True)))]


def toggle_rows(payload: dict) -> list[dict]:
    """The plugin's own switches (`toggles`), as the app's overlay draws them: a row the user clicks,
    which runs the plugin's action with `{id, value}` - the plugin owns the setting, not the overlay."""
    out = []
    for toggle in (payload.get("toggles") or [])[:MAX_TOGGLES]:
        if not (isinstance(toggle, dict) and toggle.get("id") and toggle.get("action")):
            continue
        out.append({"id": toggle["id"], "label": str(toggle.get("label") or toggle["id"])[:60],
                    "value": bool(toggle.get("value")), "hint": str(toggle.get("hint") or "")[:160],
                    "action": toggle["action"]})
    return out


def wants_codex_search(payload: dict) -> bool:
    """`codex_search: true` is the plugin asking for a Codex search over its own persona's library. The
    app draws its own search area; the standalone overlay offers the page's Codex tab instead, which is
    where that search lives here (HELP.md says so)."""
    return payload.get("codex_search") is True


def area_rows(area: dict, now: float) -> list[str]:
    """One area's lines: its timers as countdowns first, then its text lines, bounded like the app's."""
    rows = [f"{timer.get('label', '')}  {alerts.format_remaining(timer, now)}"
            for timer in (area.get("timers") or []) if isinstance(timer, dict)]
    rows.extend(line.strip()[:MAX_LINE_CHARS] for line in (area.get("lines") or [])
                if isinstance(line, str) and line.strip())
    return rows[:MAX_AREA_LINES]


def load_choices(path: Path) -> dict:
    """The user's area switches and the window position; a missing or damaged file reads as defaults."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"areas": {}, "geometry": ""}
    areas = raw.get("areas") if isinstance(raw, dict) else None
    return {"areas": areas if isinstance(areas, dict) else {},
            "geometry": str(raw.get("geometry") or "") if isinstance(raw, dict) else ""}


def save_choices(path: Path, areas: dict, geometry: str = "") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"areas": areas, "geometry": geometry}, indent=1), encoding="utf-8")
    tmp.replace(path)


def geometry_offset(geometry: str) -> str:
    """The `+x+y` part of a tkinter geometry string (`240x120+1200+40` -> `+1200+40`), or "".

    Kept pure and tested: the drag handler saves this on every release, and getting it wrong means the
    window forgets where the user put it.
    """
    parts = str(geometry or "").split("+")
    return "+" + "+".join(parts[1:]) if len(parts) > 2 else ""


class OverlayState:
    """The last payload the host gave us, and whether it is still fresh."""

    def __init__(self):
        self.payload: dict = {}
        self.stale = False
        self.note = ""

    def apply(self, payload: dict) -> None:
        self.payload = payload if isinstance(payload, dict) else {}
        self.stale = False
        self.note = ""

    def failed(self, reason: str) -> None:
        """Keep what we have; the host may be restarting after an update."""
        self.stale = True
        self.note = f"waiting for the companion ({reason})"


# --------------------------------------------------------------------------- the window


def fetch(port: int, opener=urllib.request.urlopen) -> dict:
    with opener(overlay_url(port), timeout=POLL_TIMEOUT_S) as response:
        return json.loads(response.read())


class OverlayWindow:
    """The tkinter window. Built lazily so importing this module needs no display."""

    def __init__(self, port: int, data_dir: Path):
        import tkinter as tk

        self.port = port
        self.choices_path = Path(data_dir) / CHOICES_NAME
        stored = load_choices(self.choices_path)
        self.choices = stored["areas"]
        self.state = OverlayState()
        self.alert_state = alerts.new_state()
        self.root = tk.Tk()
        self.root.title("No Man's Sky Companion")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", ALPHA)
        self.root.configure(bg="#0e1116")
        if stored["geometry"]:
            self.root.geometry(stored["geometry"])
        self.body = tk.Label(self.root, justify="left", anchor="nw", font=("Segoe UI", 10),
                             fg="#dfe5ec", bg="#0e1116", padx=10, pady=8, text="starting...")
        self.body.pack(fill="both", expand=True)
        self._wire_drag()
        self._wire_menu()

    def _wire_drag(self) -> None:
        start = {}

        def press(event):
            start["x"], start["y"] = event.x, event.y

        def drag(event):
            self.root.geometry(f"+{event.x_root - start.get('x', 0)}+{event.y_root - start.get('y', 0)}")

        def release(_event):
            save_choices(self.choices_path, self.choices, self._geometry())

        self.body.bind("<Button-1>", press)
        self.body.bind("<B1-Motion>", drag)
        self.body.bind("<ButtonRelease-1>", release)

    def _wire_menu(self) -> None:
        import tkinter as tk

        self.menu = tk.Menu(self.root, tearoff=0)
        self.body.bind("<Button-3>", self._open_menu)

    def _open_menu(self, event) -> None:
        """Built on every click: the areas come from the plugin and can change between polls."""
        self.menu.delete(0, "end")
        for toggle in toggle_rows(self.state.payload):
            self.menu.add_command(label=("* " if toggle["value"] else "   ") + toggle["label"],
                                  command=lambda t=toggle: self._run_toggle(t))
        if toggle_rows(self.state.payload):
            self.menu.add_separator()
        if wants_codex_search(self.state.payload):
            self.menu.add_command(label="Search the Codex...", command=self._open_codex)
            self.menu.add_separator()
        for area in self.state.payload.get("areas") or []:
            if not (isinstance(area, dict) and area.get("id")):
                continue
            area_id = area["id"]
            on = self.choices.get(area_id, bool(area.get("default_on", True)))
            self.menu.add_command(label=("* " if on else "   ") + str(area.get("title") or area_id),
                                  command=lambda i=area_id, v=on: self._toggle(i, not v))
        self.menu.add_separator()
        self.menu.add_command(label="Close the overlay", command=self.root.destroy)
        self.menu.tk_popup(event.x_root, event.y_root)

    def _run_toggle(self, toggle: dict) -> None:
        """Ask the host to run the plugin's action; the plugin owns the setting, so we only report."""
        import urllib.error
        body = json.dumps({"params": {"id": toggle["id"], "value": not toggle["value"]}}).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/actions/{toggle['action']}", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30):
                pass
        except (OSError, urllib.error.URLError) as err:
            log.warning("the switch %s could not be set: %s", toggle["id"], err)

    def _open_codex(self) -> None:
        """The Codex search lives on the page here, not in the overlay window."""
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{self.port}#codex")

    def _toggle(self, area_id: str, value: bool) -> None:
        self.choices[area_id] = value
        save_choices(self.choices_path, self.choices, self._geometry())
        self.render()

    def _geometry(self) -> str:
        return geometry_offset(self.root.geometry())

    def render(self) -> None:
        now = time.time()
        blocks = []
        for area in visible_areas(self.state.payload, self.choices):
            rows = area_rows(area, now)
            blocks.append(str(area.get("title") or "") + "\n" + ("\n".join(rows) if rows else "  -"))
        text = "\n\n".join(blocks) or "nothing to show (right-click to pick areas)"
        if self.state.stale:
            text += f"\n\n{self.state.note}"
        self.body.configure(text=text)

    def poll(self) -> None:
        try:
            self.state.apply(fetch(self.port))
        except Exception as err:               # noqa: BLE001 - kept content plus a note; logged
            log.debug("the host did not answer: %s", err)
            self.state.failed(str(err))
        self._beep_for_finished()
        self.render()
        self.root.after(int(POLL_S * 1000), self.poll)

    def _beep_for_finished(self) -> None:
        """A finished timer beeps even with no page open; the tray icon carries the full balloon."""
        finished = alerts.due(self.alert_state, alerts.collect(self.state.payload), time.time())
        if not finished:
            return
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception as err:               # noqa: BLE001 - sound is optional, the text is not
            log.debug("could not beep: %s", err)

    def run(self) -> None:
        self.root.after(100, self.poll)
        self.root.mainloop()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="nms-companion-overlay")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    OverlayWindow(args.port, paths.data_dir()).run()


if __name__ == "__main__":
    main()
