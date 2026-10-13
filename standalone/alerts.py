"""When a finished timer is worth announcing, and how a countdown reads.

One rule, two implementations: this one for the tray and the overlay, `standalone/web/timers.js` for
the page. `tests/alert_cases.json` is run against both, so they cannot drift.
"""
from __future__ import annotations

GRACE_S = 3600      # the app's notification grace: an ending older than this is history, not news


def new_state() -> dict:
    """`sent` maps a timer key to the end time already announced."""
    return {"sent": {}}


def collect(payload: dict) -> list[dict]:
    """Every timer in an overlay payload: the top-level list (the pre-3.12.0 fallback the connector still
    sends) and the ones inside each area."""
    payload = payload if isinstance(payload, dict) else {}
    timers = list(payload.get("timers") or [])
    for area in payload.get("areas") or []:
        if isinstance(area, dict):
            timers.extend(area.get("timers") or [])
    return [timer for timer in timers if isinstance(timer, dict)]


def due(state: dict, timers: list[dict], now: float) -> list[dict]:
    """The timers that just ended and were not announced for that end time.

    A restarted timer (a settlement's next construction under the same key) has a new end time and is
    announced again; an ending older than `GRACE_S` is not, so opening the page after a week does not
    fire a burst.
    """
    out = []
    for timer in timers or []:
        key = timer.get("key")
        ends_at = timer.get("ends_at")
        if not key or isinstance(ends_at, bool) or not isinstance(ends_at, (int, float)):
            continue
        if not 0 <= now - ends_at <= GRACE_S:
            continue
        if state["sent"].get(key) == ends_at:
            continue
        state["sent"][key] = ends_at
        out.append(timer)
    return out


def format_remaining(timer: dict, now: float) -> str:
    """`1 h 02:03`, `10:00`, or `done` - what the overlay and the tray print."""
    ends_at = timer.get("ends_at")
    if not isinstance(ends_at, (int, float)):
        return ""
    left = int(ends_at - now)
    if left <= 0:
        return "done"
    hours, rest = divmod(left, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours} h {minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
