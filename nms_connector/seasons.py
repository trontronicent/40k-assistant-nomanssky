"""Seasons ("expeditions") from the game's own files, plus researched dates, for the persona.

No Man's Sky calls its seasons **Expeditions**: a time-limited run of about six weeks with milestones, phases and
exclusive rewards. The game build carries one name and description per expedition and the names of the rewards
(title, banner, decal, posters, egg, multi-tool, starships) in its language files, English and the game language;
the build of 2026-10-07 knows 23. What the files do not say - when an expedition ran, whether it is running now -
comes from ``research/expeditions.json`` (sources listed in it). The player's save only says whether the save is
itself an expedition (``CommonStateData.SeasonData.SeasonId`` 0 = a normal game, see ``summary.season_of``).

``SeasonBook`` is built from the language texts (``from_texts``, the same pass as the world types) and stored with
them (``store.py``), so the persona answers without the game files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import logs, mbin
from .planet_search import fold

RESEARCH_FILE = Path(__file__).resolve().parent.parent / "research" / "expeditions.json"
MAX_REWARDS = 14                 # reward names listed per expedition
DEFAULT_WEEKS = 6

_NAME_RE = re.compile(r"^UI_SEASON_(\d+)_(NAME|MAIN_TITLE)$")
_TEXT_RE = re.compile(r"^UI_EXPED(\d+)_(MAIN_DESC|SUMMARY|DETAIL_DESC)$")
_REWARD_RE = re.compile(r"^(?P<pre>[A-Z_]*?)EXPD_(?P<kind>[A-Z]+_|POSTER)?(?P<n>\d+)(?P<v>[A-Z]?)_NAME_L$")
_KINDS = {"TITLE_": "title", "EGG_": "egg", "GUN_": "multi-tool", "SHIP_": "starship", "POSTER": "poster"}
SEASON_WORDS = {"season", "seasons", "seasonal", "saison", "saisons", "expedition", "expeditions", "expeditionen"}
FRIGATE_WORDS = {"frigate", "frigates", "fregatte", "fregatten", "fleet", "flotte"}
REWARD_WORDS = {"reward", "rewards", "belohnung", "belohnungen", "gave", "give", "gives", "given", "got", "earn",
                "earned", "unlock", "unlocked", "freischalten", "freigeschaltet", "from", "aus", "von", "welcher",
                "welche", "which"}
REWARD_FILLER = {"the", "title", "poster", "decal", "banner", "framed", "art", "der", "die", "das", "titel",
                 "motiv", "and", "und", "of", "von", "mit"}
LIST_WORDS = {"all", "list", "alle", "welche", "which", "every", "overview", "übersicht", "liste"}


def wanted_key(key: str) -> bool:
    """The language keys the expeditions need (names, descriptions, reward names)."""
    return bool(_NAME_RE.match(key) or _TEXT_RE.match(key) or _REWARD_RE.match(key))


def _clean(text: str | None) -> str:
    return " ".join((mbin.clean_text(text) or "").split())


def _kind_of(match: re.Match) -> str:
    pre = match.group("pre")
    if "BANNER" in pre:
        return "banner"
    if "DECAL" in pre:
        return "decal"
    return _KINDS.get(match.group("kind") or "", "reward")


def load_research(path: Path | None = None) -> dict:
    """The researched dates and facts ({} when the file is missing or unreadable - the persona then says less)."""
    data = logs.read_json(path or RESEARCH_FILE, "The researched expeditions file")
    return data if isinstance(data, dict) else {}


@dataclass
class SeasonBook:
    """The expeditions of one game build: {number: {name, title, summary, detail, rewards}} (each text as
    ``{"en", "local"}``), empty with `error` when the files could not be read."""
    seasons: dict[int, dict] = field(default_factory=dict)
    language: str | None = None
    error: str | None = None

    @classmethod
    def from_texts(cls, english: dict[str, str], local: dict[str, str] | None, language: str | None = None):
        local = local or {}

        def pair(key: str) -> dict | None:
            en = _clean(english.get(key))
            if not en:
                return None
            lo = _clean(local.get(key))
            return {"en": en, "local": lo if lo and lo != en else None}

        seasons: dict[int, dict] = {}
        for key in english:
            m = _NAME_RE.match(key)
            if m and m.group(2) == "NAME":
                n = int(m.group(1))
                seasons[n] = {"rewards": [], "name": pair(key), "title": pair(f"UI_SEASON_{n}_MAIN_TITLE")}
        for n, s in seasons.items():
            s["summary"] = pair(f"UI_EXPED{n}_SUMMARY") or pair(f"UI_EXPED{n}_MAIN_DESC")
            s["detail"] = pair(f"UI_EXPED{n}_DETAIL_DESC")
        for key in sorted(english):
            m = _REWARD_RE.match(key)
            if m and int(m.group("n")) in seasons:
                name = pair(key)
                if name:
                    seasons[int(m.group("n"))]["rewards"].append(dict(name, kind=_kind_of(m)))
        return cls(seasons, language)

    @property
    def latest(self) -> int | None:
        return max(self.seasons) if self.seasons else None

    def name(self, number: int, language: str | None = None) -> str:
        """"Our Journey Continues (Unsere Reise geht weiter)" - both languages when the game's differs."""
        return _both((self.seasons.get(number) or {}).get("name")) or f"Expedition {number}"

    def named_in(self, question: str) -> list[int]:
        """The expeditions a question names: "expedition 15", "Aquarius", "Titan" (whole-word name match)."""
        q = " " + " ".join(re.findall(r"[a-z0-9]+", fold(question))) + " "
        found = []
        for n, s in sorted(self.seasons.items()):
            names = [(s.get("name") or {}).get("en"), (s.get("name") or {}).get("local")]
            names = [" ".join(re.findall(r"[a-z0-9]+", fold(t))) for t in names if t]
            by_number = re.search(rf"\b(?:expedition|expeditionen|season|saison)\s*(?:nr\s*|number\s*)?{n}\b", q)
            if by_number or any(len(t) >= 4 and f" {t} " in q for t in names):
                found.append(n)
        return found


def _reward_tokens(*names: str | None) -> list[set[str]]:
    """Distinctive words of a reward name in each language ("The Wraith" -> {wraith}; the filler is dropped)."""
    out = []
    for name in names:
        if name:
            tokens = {w for w in re.findall(r"[a-z0-9]+", fold(name)) if w not in REWARD_FILLER}
            if tokens and any(len(w) >= 4 for w in tokens):
                out.append(tokens)
    return out


def rewards_named_in(book: SeasonBook, question: str) -> list[int]:
    """The expeditions that gave a reward the question names ("Which expedition gave the Wraith?"): every
    distinctive word of a reward's name must be in the question."""
    q = set(re.findall(r"[a-z0-9]+", fold(question)))
    found = []
    for n, s in sorted(book.seasons.items()):
        for reward in s.get("rewards") or []:
            if any(tokens <= q for tokens in _reward_tokens(reward.get("en"), reward.get("local"))):
                found.append(n)
                break
    return found


def asked_about(words: set[str]) -> bool:
    """A question about seasons/expeditions - not about the frigates' expeditions."""
    return bool(words & SEASON_WORDS) and not (words & FRIGATE_WORDS)


def _days(n: int) -> str:
    return f"{n} day{'' if n == 1 else 's'}"


def timing(number: int, research: dict, today: date) -> tuple[str | None, bool]:
    """(one sentence on when an expedition ran or runs - None when nothing is known, whether it is running now),
    from the researched file."""
    info = (research.get("seasons") or {}).get(str(number)) or {}
    try:
        if info.get("start"):
            start = date.fromisoformat(info["start"])
            official = bool(info.get("official_end"))
            end = date.fromisoformat(info["official_end"]) if official else \
                start + timedelta(weeks=int(info.get("weeks") or DEFAULT_WEEKS))
            if today < start:
                return f"starts {start.isoformat()}", False
            if today <= end:
                note = "" if official else " - Hello Games announced about six weeks and no exact end date, so the end is an estimate"
                verb = "ends" if official else "is expected to end about"
                return (f"started {start.isoformat()} ({_days((today - start).days)} ago); {verb} {end.isoformat()} "
                        f"({_days((end - today).days)} left){note}"), True
            return f"ran from {start.isoformat()} to about {end.isoformat()}", False
        if info.get("first_run"):
            a, b = info["first_run"]
            return f"first ran {a} to {b} (reruns happen mostly in a Nov-Jan holiday block)", False
    except (ValueError, TypeError):
        return None, False
    return None, False


def _text(entry: dict | None, language: str | None = None) -> str:
    """A description in English (the persona translates prose itself)."""
    return (entry or {}).get("en") or ""


def _both(entry: dict | None) -> str:
    """A game name as "English (game language)" - the persona must use the game's own names, never translate."""
    if not entry or not entry.get("en"):
        return ""
    return entry["en"] + (f" ({entry['local']})" if entry.get("local") else "")


def expedition_lines(book: SeasonBook, research: dict, question: str, today: date, save_season: dict | None,
                     language: str | None = None) -> list[str]:
    """The persona's block for a question about seasons/expeditions (empty when it is not one)."""
    if not book.seasons:
        return []
    words = set(re.findall(r"[\w'-]+", (question or "").lower()))
    named = book.named_in(question)
    # "Which expedition gave the Wraith?" - a reward's name finds its expedition, but only when the question talks
    # about rewards/expeditions (a "gas giant" question must not open the Titan expedition's poster).
    if not named and (asked_about(words) or words & REWARD_WORDS):
        named = rewards_named_in(book, question)
    if not (asked_about(words) or named):
        return []
    latest = book.latest
    out = ["Expeditions (the game's seasons) - names and rewards from the game's files, dates researched:"]
    out.append(f"  The game build knows {len(book.seasons)} expeditions; the newest is Expedition {latest} "
               f"\"{book.name(latest, language)}\".")
    if save_season is not None:
        if save_season.get("active"):
            out.append(f"  Your save is expedition {save_season['number']} (\"{book.name(save_season['number'], language)}\").")
        else:
            out.append("  Your save is a normal game, not an expedition (the save's seasonal data is empty), so no "
                       "expedition progress is stored in it.")
        if save_season.get("redeemed"):
            out.append(f"  Expedition rewards you have redeemed: {save_season['redeemed']}.")
    for n in named or [latest]:
        s = book.seasons.get(n)
        if not s:
            continue
        when, running = timing(n, research, today)
        out.append(f"  Expedition {n} \"{book.name(n, language)}\"" + (f" - {when}" if when else
                   " - when it ran is not in the game files and was not researched")
                   + (" - this is the current expedition" if running else ""))
        for label, key in (("what it is", "summary"), ("how it works", "detail")):
            if _text(s.get(key), language):
                out.append(f"    {label}: {_text(s.get(key), language)}")
        rewards = s.get("rewards") or []
        if rewards:
            posters = [r for r in rewards if r["kind"] == "poster"]
            parts = [f"{r['kind']}: {_both(r)}" for r in rewards if r["kind"] != "poster"][:MAX_REWARDS]
            if posters:
                parts.append(f"{len(posters)} posters ({', '.join(_both(p) for p in posters[:4])}"
                             f"{', ...' if len(posters) > 4 else ''})")
            out.append("    rewards the game names: " + "; ".join(parts))
    if not named or words & LIST_WORDS:
        def dated(n):
            run = ((research.get("seasons") or {}).get(str(n)) or {}).get("first_run")
            return f"{n} {book.name(n, language)}" + (f" ({run[0]} to {run[1]})" if run else "")
        out.append("  All expeditions (first-run dates where researched): " + ", ".join(dated(n) for n in sorted(book.seasons)))
    for fact in research.get("facts") or []:
        out.append(f"  {fact}")
    return out
