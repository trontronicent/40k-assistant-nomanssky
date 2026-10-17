"""The standalone game overlay: a small always-on-top window over No Man's Sky.

`tkinter` and `ctypes` only, like the app's own overlay, and a separate process so a slow redraw can
never touch the connector's loop. It polls the host's `/api/overlay` - exactly what the page reads - and
draws the connector's areas. **The user owns which areas are shown**; the plugin only supplies
`default_on`, and the choice lives in `<data>/overlay.json`.

    python -m standalone.overlay --port 8787

Since plugin 0.15.0-beta.7 it also draws the **recipe viewer** (`recipe_view.overlay_area`): the area's own
text box runs the connector's `recipe_search` action, and its `recipes` are drawn as diagrams - the same cards,
arrow and station the chat and the page show, with the item icons read straight from the plugin's assets folder
(the overlay runs on the same machine, so there is nothing to fetch). An area without diagrams falls back to its
`lines`, which is what an older overlay drew.

Two keys of the payload are deliberately unused here: `persona_id` and `codeword` exist so the app's
overlay can switch Live Comms to the plugin's persona and set its wake word. The standalone host has no
Live Comms and only one persona - the chat page always talks to it - so there is nothing to switch.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
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
MAX_RECIPES = 4               # the window is small; the page shows them all
MAX_QUERY_CHARS = 60          # the connector cuts it too (its search field's length)
ICON_PX = 20
ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")   # the app's views.ACTION_ID_RE


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


def recipe_areas(payload: dict, choices: dict) -> list[dict]:
    """The switched-on areas that carry the recipe viewer (diagrams, or its own search box)."""
    return [area for area in visible_areas(payload, choices) if area.get("recipes") or area.get("search")]


def recipe_cards(recipe: dict) -> list[tuple[str, str]]:
    """One recipe as (text, icon file) cards with the marks between them: [("1 Nitrogen", "gas.png"),
    ("+", ""), ("1 Di-hydrogen", ""), ("→", ""), ("1 Ammonia", "toxic.png")].

    Pure, so the drawing is only placement: an entry the connector could not fill (no result, no
    ingredients) yields nothing at all rather than an arrow pointing at empty space."""
    items = [i for i in (recipe.get("ingredients") or []) if isinstance(i, dict) and i.get("name")]
    result = recipe.get("result")
    if not items or not (isinstance(result, dict) and result.get("name")):
        return []
    out: list[tuple[str, str]] = []
    for card in items:
        if out:
            out.append(("+", ""))
        out.append((f"{card.get('amount', 1)} {card['name']}", str(card.get("icon") or "")))
    out.append(("→", ""))
    out.append((f"{result.get('amount', 1)} {result['name']}", str(result.get("icon") or "")))
    return out


def search_action(payload: dict) -> str:
    """The connector's action an area's search box runs (`recipe_search`), or "" when it offers none."""
    action = payload.get("recipe_search")
    return action if isinstance(action, str) and ACTION_RE.match(action) else ""


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

    def __init__(self, port: int, data_dir: Path, root=None):
        """`root` is only given by the tests: many `Tk()` roots in one process intermittently fail with
        "Can't find a usable tk.tcl", so they hand in a Toplevel under one hidden root."""
        import tkinter as tk

        self.port = port
        self.choices_path = Path(data_dir) / CHOICES_NAME
        stored = load_choices(self.choices_path)
        self.choices = stored["areas"]
        self.state = OverlayState()
        self.alert_state = alerts.new_state()
        self.root = root or tk.Tk()
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
        # The recipe viewer needs widgets (a text box, icons), not one Label: its own frame below the text.
        self.recipes = tk.Frame(self.root, bg="#0e1116")
        self.recipes.pack(fill="x")
        self.assets = Path(data_dir) / "assets"
        self._images: dict = {}            # icon file -> PhotoImage (Tk drops an unreferenced image)
        self._query_box = None
        self._note = ""                    # what the last recipe search did
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

    def _post_action(self, action: str, params: dict) -> str:
        """Run one of the connector's actions through the host; returns "" or what went wrong.

        The connector owns the state - a switch's value, the recipe query - exactly as it does for its
        page, so the overlay only asks and then polls again."""
        import urllib.error
        body = json.dumps({"params": params}).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/actions/{action}", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30):
                return ""
        except (OSError, urllib.error.URLError) as err:
            log.warning("the action %s failed: %s", action, err)
            return str(err)

    def _run_toggle(self, toggle: dict) -> None:
        """Ask the host to run the plugin's action; the plugin owns the setting, so we only report."""
        self._post_action(toggle["action"], {"id": toggle["id"], "value": not toggle["value"]})

    def search_recipes(self, query: str) -> None:
        """What the recipe box typed: the connector searches and answers the next poll, so the page and the
        overlay always show the same item in the same language."""
        action = search_action(self.state.payload)
        if not action:
            return
        query = " ".join((query or "").split())[:MAX_QUERY_CHARS]
        failed = self._post_action(action, {"query": query})
        self._note = f"the search failed: {failed}" if failed else ""
        self.poll_now()

    def poll_now(self) -> None:
        """Read the host once, outside the 2 s rhythm (after a search, so the answer is drawn at once)."""
        try:
            self.state.apply(fetch(self.port))
        except Exception as err:               # noqa: BLE001 - kept content plus a note; logged
            log.debug("the host did not answer: %s", err)
            self.state.failed(str(err))
        self.render()

    def _icon(self, name: str):
        """The item's icon as a PhotoImage, read from the plugin's own assets folder; None when there is
        none, it is not a plain file name, or Tk cannot read it (a card without a picture is still a card)."""
        if not name or "/" in name or "\\" in name or ".." in name:
            return None
        if name in self._images:
            return self._images[name]
        path = self.assets / name
        if not path.is_file():
            return None
        try:
            import tkinter as tk
            image = tk.PhotoImage(file=str(path)).subsample(max(1, 64 // ICON_PX), max(1, 64 // ICON_PX))
        except Exception as err:               # noqa: BLE001 - one missing picture, never a broken overlay
            log.debug("the icon %s could not be read: %s", name, err)
            self._images[name] = None
            return None
        self._images[name] = image
        return image

    def _draw_recipes(self) -> None:
        """Rebuild the recipe frame: the search box, a note, then one row of cards per recipe."""
        import tkinter as tk
        for child in self.recipes.winfo_children():
            if child is not self._query_box:
                child.destroy()
        areas = recipe_areas(self.state.payload, self.choices)
        if not areas:
            if self._query_box is not None:
                self._query_box.pack_forget()
            return
        if search_action(self.state.payload):
            self._draw_query_box()
        area = areas[0]
        note = self._note or (f"searching for \u201c{area.get('query')}\u201d" if area.get("query")
                              else "type an item and press Enter")
        tk.Label(self.recipes, text=note, fg="#8b93a1", bg="#0e1116", font=("Segoe UI", 8),
                 anchor="w", padx=10).pack(fill="x")
        drawn = 0
        for recipe in (area.get("recipes") or []):
            cards = recipe_cards(recipe)
            if not cards or drawn >= MAX_RECIPES:
                continue
            self._draw_recipe_row(cards, str(recipe.get("station") or ""))
            drawn += 1

    def _draw_query_box(self) -> None:
        """The one text box (created once, re-packed): Enter searches, Escape clears it."""
        import tkinter as tk
        if self._query_box is None:
            box = tk.Entry(self.recipes, bg="#161b22", fg="#dfe5ec", insertbackground="#dfe5ec",
                           relief="flat", font=("Segoe UI", 9))
            box.bind("<Return>", lambda _e: self.search_recipes(box.get()))
            box.bind("<Escape>", lambda _e: self.clear_search())
            box.bind("<Button-1>", lambda _e: box.focus_force())
            self._query_box = box
        self._query_box.pack(fill="x", padx=10, pady=(0, 3))

    def clear_search(self) -> None:
        """Escape: empty the box and the connector's query."""
        if self._query_box is not None:
            self._query_box.delete(0, "end")
        self.search_recipes("")

    def _draw_recipe_row(self, cards: list, station: str) -> None:
        """One diagram: a card per item (icon above the text), the marks between them, the station below."""
        import tkinter as tk
        row = tk.Frame(self.recipes, bg="#0e1116")
        row.pack(fill="x", padx=8, pady=1)
        for text, icon in cards:
            if text in ("+", "\u2192"):
                tk.Label(row, text=text, fg="#a08a4a", bg="#0e1116", font=("Segoe UI", 9)).pack(side="left")
                continue
            card = tk.Frame(row, bg="#161b22", highlightbackground="#2a2a30", highlightthickness=1)
            card.pack(side="left", padx=2)
            image = self._icon(icon)
            if image is not None:
                picture = tk.Label(card, image=image, bg="#161b22")
                picture.image = image          # the label keeps the reference Tk needs
                picture.pack()
            tk.Label(card, text=text, fg="#dfe5ec", bg="#161b22", font=("Segoe UI", 8),
                     wraplength=110, justify="center").pack(padx=3)
        if station:
            tk.Label(self.recipes, text=station, fg="#8b93a1", bg="#0e1116", font=("Segoe UI", 8),
                     anchor="w", padx=10).pack(fill="x")

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
        drawn = {area["id"] for area in recipe_areas(self.state.payload, self.choices) if area.get("recipes")}
        for area in visible_areas(self.state.payload, self.choices):
            if area["id"] in drawn:
                continue                       # drawn as diagrams below, not as text
            rows = area_rows(area, now)
            blocks.append(str(area.get("title") or "") + "\n" + ("\n".join(rows) if rows else "  -"))
        text = "\n\n".join(blocks) or ("" if drawn else "nothing to show (right-click to pick areas)")
        if self.state.stale:
            text += f"\n\n{self.state.note}"
        self.body.configure(text=text)
        self._draw_recipes()

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
