"""World types (biomes) in the game's own words: every planet-type name and weather per world type, English and the
game's language, from the language files - so a German question ("Habe ich eine stickige Welt entdeckt?") is
understood as the game means it.

Asked for 2026-10-06: the persona translated "stickige Welt" as "sticky world". In the German game **stickig =
airless** - ``DEAD9`` "Stickiger %PLANETCLASS%" = "Airless %PLANETCLASS%", ``WEATHER_DEAD7`` "Stickig" =
"Airless", ``UI_VISIT_CLIMATE_DEAD`` "stickig" = "airless": a dead world without atmosphere.

* ``WORLD_TYPES``: per world type the language-key prefixes of its planet-type names (``DEAD1..10``, ``LUSH1..``,
  exotic sub-biomes such as ``BUBBLEBIOME``), its weathers (``WEATHER_DEAD1..10``; ``*EXTREME*`` = extreme weather),
  the game's climate word (``UI_VISIT_CLIMATE_*``), the biome names of planet records it covers, its typical
  resources (item ids whose game description ties them to this climate: Ammonia "toxic environment", Dioxite
  "frozen" ...) and harvester gas (``planets_view.GAS_BY_BIOME``), plus researched facts where the game files say
  nothing (``FACTS``, with their source).
* ``WorldBook`` (``load``): the texts of one game build and language; ``glossary`` maps every folded word of a name
  to the world types that use it; ``explain`` names the game terms of a question with their meaning; ``biome_words``
  = per planet-record biome the words of its type names, for the planet search; ``documents`` = one Codex document
  per world type.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import mbin
from .planet_search import QUESTION_WORDS, fold, stem

MIN_WORD = 4
MAX_WEATHER_WORLDS = 2          # a weather word shared by more world types does not tell the world
# Words in many names that say nothing about the world type.
GENERIC_WORDS = {"planet", "planeten", "welt", "welten", "world", "worlds", "mond", "monde", "moon", "atmosphaere",
                 "atmosphere", "regen", "rain", "wind", "winde", "sturm", "storm", "nebel", "fog", "dunst", "wolken",
                 "clouds", "wetter", "weather", "spruehregen", "drizzle", "gewitter", "himmel", "skies", "luft", "air"}
CLASS_TOKEN = "%PLANETCLASS%"
EXOTIC_PREFIXES = ("BEAMSBIOME", "BONESPIREBIOME", "BUBBLEBIOME", "CONTOURBIOME", "FRACTCUBEBIOME", "HEXAGONBIOME",
                   "HYDROGARDENBIOME", "IRRISHELLSBIOME", "MSTRUCTBIOME", "SHARDSBIOME", "WIRECELLSBIOME",
                   "GLITCHBIOME", "REDBIOME", "GREENBIOME", "BLUEBIOME")


@dataclass(frozen=True)
class WorldType:
    """One world type: how the game names it and what it holds."""
    id: str
    title: str                                  # English, e.g. "Airless (dead) worlds"
    type_prefixes: tuple[str, ...]              # planet-type name keys: prefix + digits
    weather_prefixes: tuple[str, ...]           # weather keys: prefix + digits
    climate_key: str | None                     # UI_VISIT_CLIMATE_* - the game's one-word climate
    biomes: tuple[str, ...]                     # planet records' biome names this type covers
    resources: tuple[str, ...] = ()             # typical item ids (the game's descriptions say so)
    gas: str | None = None                      # atmosphere harvester gas
    summary: str = ""                           # one line: what such a world is like
    # False for exotic worlds: ~15 sub-biomes with unrelated names ("Toxic Anomaly", "Planet of Light"); giving every
    # exotic planet all of them made each match "giftige", "gefrorenen" and "grüne" (live test 2026-10-06).
    names_identify: bool = True


WORLD_TYPES = (
    WorldType("dead", "Airless (dead) worlds", ("DEAD",), ("WEATHER_DEAD",), "UI_VISIT_CLIMATE_DEAD", ("Dead",),
              ("SPACEGUNK3",), None,
              "no atmosphere, low gravity, no storms, no ordinary flora or fauna; rich in resources"),
    WorldType("lush", "Lush worlds", ("LUSH",), ("WEATHER_LUSH", "WEATHER_LUSH_CLEAR", "WEATHER_LUSHEXTREME"),
              "UI_VISIT_CLIMATE_LUSH", ("Lush",), ("LUSH1", "PLANT_LUSH"), "GAS3",
              "green, mild worlds full of flora and fauna"),
    WorldType("toxic", "Toxic worlds", ("TOXIC",), ("WEATHER_TOXIC", "WEATHER_TOXIC_CLEAR", "WEATHER_TOXICEXTREME"),
              "UI_VISIT_CLIMATE_TOXIC", ("Toxic",), ("TOXIC1", "PLANT_TOXIC"), "GAS3",
              "poisonous atmosphere and rain: toxic protection drains"),
    WorldType("scorched", "Scorched worlds", ("SCORCHED",), ("WEATHER_HEAT", "WEATHER_HEAT_CLEAR", "WEATHER_HEATEXTREME"),
              "UI_VISIT_CLIMATE_HOT", ("Scorched",), ("HOT1", "PLANT_HOT"), "GAS1",
              "extreme heat: heat protection drains"),
    WorldType("frozen", "Frozen worlds", ("FROZEN",), ("WEATHER_COLD", "WEATHER_COLD_CLEAR", "WEATHER_COLDEXTREME"),
              "UI_VISIT_CLIMATE_FROZEN", ("Frozen",), ("COLD1", "PLANT_SNOW"), "GAS2",
              "extreme cold: cold protection drains"),
    WorldType("radioactive", "Radioactive worlds", ("IRRADIATED",),
              ("WEATHER_RADIO", "WEATHER_RADIO_CLEAR", "WEATHER_RADIOEXTREME"), "UI_VISIT_CLIMATE_RADIO",
              ("Radioactive",), ("RADIO1", "PLANT_RADIO"), "GAS2", "radiation: radiation protection drains"),
    WorldType("barren", "Barren (desert) worlds", ("BARREN",),
              ("WEATHER_BARREN", "WEATHER_BARREN_CLEAR", "WEATHER_BARRENEXTREME"), "UI_VISIT_CLIMATE_DUST",
              ("Barren",), ("DUSTY1", "PLANT_DUST"), "GAS1", "dry, dusty desert worlds with sparse life"),
    WorldType("swamp", "Swamp worlds", ("SWAMPBIOME",), ("WEATHER_SWAMP", "WEATHER_SWAMP_CLEAR", "WEATHER_SWAMP_EXTREME"),
              "UI_VISIT_CLIMATE_SWAMP", ("Swamp",), (), "GAS3", "humid, marshy worlds"),
    WorldType("lava", "Volcanic (lava) worlds", ("LAVABIOME",), ("WEATHER_LAVA", "WEATHER_LAVA_CLEAR", "WEATHER_LAVA_EXTREME"),
              "UI_VISIT_CLIMATE_LAVA", ("Lava",), ("LAVA1",), "GAS1", "volcanic worlds with lava and heat"),
    WorldType("water", "Ocean worlds", ("WATERWORLD",), ("WEATHER_WATERWORLD",), None, ("Waterworld",),
              ("WATERWORLD1", "PLANT_WATER", "WATER2"), None, "almost entirely covered by ocean"),
    WorldType("exotic", "Exotic worlds", EXOTIC_PREFIXES,
              ("WEATHER_GLITCH", "WEATHER_RED", "WEATHER_GREEN", "WEATHER_BLUE", "WEATHER_CLEAR"),
              "UI_VISIT_CLIMATE_WEIRD", ("Exotic", "Exotic (red)", "Exotic (green)", "Exotic (blue)"), (), "OXYGEN",
              "strange worlds (bubbles, glitches, coloured skies) with unusual terrain", names_identify=False),
    WorldType("gasgiant", "Gas giants", (), ("WEATHER_GASGIANT",), None, ("Gas giant",), (), None,
              "giant planets of gas"),
)

# The opening sentence of each world document in German, worded like a question would be ("eine stickige Welt"):
# the Codex's meaning-based lookup embeds the first passage, and "stickige Welt" found "Honied Throat-Sticker"
# (sticky ~ sticker) instead of the airless worlds until the document said it in German (live test 2026-10-06).
GERMAN_SUMMARIES = {
    "dead": "Eine stickige Welt (stickiger, toter, leerer oder unbelebter Planet) ist im Spiel eine Welt ohne "
            "Atmosphäre: kein Wetter, keine Stürme, keine gewöhnlichen Pflanzen oder Tiere, geringe Schwerkraft - "
            "\"stickig\" bedeutet hier luftleer (englisch airless), nicht klebrig.",
    "lush": "Eine grüne, üppige Welt (grüner, regnerischer oder fruchtbarer Planet) hat mildes Klima und viel "
            "Pflanzen- und Tierleben.",
    "toxic": "Eine giftige Welt (giftiger, ätzender, fauliger oder schädlicher Planet) hat giftige Luft und giftigen "
             "Regen: der Giftschutz des Anzugs wird verbraucht.",
    "scorched": "Eine sengend heiße Welt (sengend heißer, verbrannter oder brütend heißer Planet) ist extrem heiß: "
                "der Hitzeschutz wird verbraucht.",
    "frozen": "Eine gefrorene Welt (gefrorener, eisiger, arktischer Planet) ist extrem kalt: der Kälteschutz wird "
              "verbraucht.",
    "radioactive": "Eine verstrahlte Welt (radioaktiver oder verstrahlter Planet) hat starke Strahlung: der "
                   "Strahlenschutz wird verbraucht.",
    "barren": "Eine unwirtliche Welt (unwirtlicher, Wüsten- oder felsiger Planet) ist trocken und staubig, mit "
              "wenig Leben.",
    "swamp": "Eine sumpfige Welt (Sumpf-, Marschland- oder Dampf-Planet) ist feucht und neblig.",
    "lava": "Eine vulkanische Welt (Lava- oder vulkanischer Planet) hat Lava und große Hitze.",
    "water": "Eine Ozeanwelt ist fast ganz von Wasser bedeckt.",
    "exotic": "Eine ungewöhnliche (exotische) Welt hat seltsames Gelände - Blasen, Säulen, Glitches, farbige "
              "Himmel - und eigene Namen wie Planet des Lichts.",
    "gasgiant": "Ein Gasriese ist ein riesiger Planet aus Gas.",
}

# Researched where the game files say nothing (2026-10-06, No Man's Sky community wiki via web search).
FACTS = {
    "dead": {
        "source": "No Man's Sky community wiki (Dead planet), read 2026-10-06",
        "points": [
            "No atmosphere and lower gravity; rocky, dusty surfaces like Mercury or the Moon.",
            "No ordinary flora or fauna, and storms never occur.",
            "More resources than other biomes; Rusted Metal can be found here.",
            "Whispering Eggs lie anywhere on the surface (50-70 units apart) and release Biological Horrors when "
            "disturbed - elsewhere they occur only at abandoned buildings.",
            "The red (oxygen), yellow (sodium) and blue (exosuit charge) plants still grow; some dead worlds have "
            "flora underground, in caves.",
            "No structures such as trading posts.",
            "Life support drains faster: bring Life Support Gel, Oxygen and Dioxite.",
        ],
    },
}


def _clean(text: str | None) -> str:
    return " ".join((mbin.clean_text(text) or "").split())


def _keyed(texts: dict[str, str], prefixes: tuple[str, ...]) -> list[str]:
    """Keys that are one of the prefixes followed by digits, in number order."""
    pattern = re.compile(r"^(" + "|".join(re.escape(p) for p in prefixes) + r")(\d+)$") if prefixes else None
    keys = [k for k in texts if pattern and pattern.match(k)]
    return sorted(keys, key=lambda k: (pattern.match(k).group(1), int(pattern.match(k).group(2))))


@dataclass
class WorldBook:
    """The world-type texts of one game build: {world id: {names, weathers, climate}} in English and the game's
    language (`local`, None when the game runs in English)."""
    worlds: dict[str, dict] = field(default_factory=dict)
    language: str | None = None
    error: str | None = None

    @classmethod
    def from_texts(cls, english: dict[str, str], local: dict[str, str] | None, language: str | None = None) -> WorldBook:
        local = local or {}
        worlds = {}
        for wt in WORLD_TYPES:
            def pair(key, planet_word=("Planet", "Planet")):
                en = _clean(english.get(key)).replace(CLASS_TOKEN, planet_word[0])
                lo = _clean(local.get(key)).replace(CLASS_TOKEN, planet_word[1]) if local.get(key) else None
                return {"key": key, "en": en, "local": lo if lo and lo != en else None}
            names = [pair(k) for k in _keyed(english, wt.type_prefixes)]
            weathers = [dict(pair(k), extreme="EXTREME" in k) for k in _keyed(english, wt.weather_prefixes)]
            climate = pair(wt.climate_key) if wt.climate_key and english.get(wt.climate_key) else None
            worlds[wt.id] = {"names": [n for n in names if n["en"]], "weathers": [w for w in weathers if w["en"]],
                             "climate": climate}
        return cls(worlds, language)

    def glossary(self) -> dict[str, set[str]]:
        """{folded word of a type name, weather or climate word (both languages): {world ids}}."""
        out: dict[str, set[str]] = {}
        for wid, w in self.worlds.items():
            texts = [n for n in w["names"]] + [x for x in w["weathers"]] + ([w["climate"]] if w["climate"] else [])
            for t in texts:
                for text in (t["en"], t["local"]):
                    for word in re.findall(r"[a-z0-9]+", fold(text)):
                        if len(word) >= MIN_WORD and word != "planet":
                            out.setdefault(word, set()).add(wid)
        return out

    def type_words(self, world_id: str) -> set[str]:
        """The folded words of a world type's planet-type names and climate word (not its weathers: a swamp
        weather "Stickiger Sprühregen" must not make every swamp planet airless)."""
        w = self.worlds.get(world_id) or {}
        wt = next((t for t in WORLD_TYPES if t.id == world_id), None)
        names = list(w.get("names") or []) if wt is None or wt.names_identify else []
        texts = names + ([w["climate"]] if w.get("climate") else [])
        out = set()
        for t in texts:
            for text in (t["en"], t["local"]):
                out |= {x for x in re.findall(r"[a-z0-9]+", fold(text)) if len(x) >= MIN_WORD and x != "planet"}
        return out

    def biome_words(self) -> dict[str, set[str]]:
        """{planet-record biome: words of its world type's names} - a search for any name variant ("stickige")
        finds every planet of that world type, whatever variant the game gave it ("Leerer Planet")."""
        out: dict[str, set[str]] = {}
        for wt in WORLD_TYPES:
            words = self.type_words(wt.id)
            for biome in wt.biomes:
                out[biome] = words
        return out

    @staticmethod
    def _uses(entry: dict, word: str, base: str) -> bool:
        """True when a name/weather entry contains the word (or a word starting with its stem)."""
        return any(x == word or x == base or (len(base) >= 5 and x.startswith(base))
                   for t in (entry["en"], entry["local"]) for x in re.findall(r"[a-z0-9]+", fold(t)))

    def matches(self, text: str) -> list[dict]:
        """The distinctive game terms of a text: per word {word, types: {world: [name/climate entries]},
        weathers: {world: [weather entries]}}. Question and generic words ("planeten", "entdeckt") are skipped;
        a word that names no planet type and appears in the weathers of more than MAX_WEATHER_WORLDS world types
        says nothing about the world and is skipped too."""
        out = []
        seen = set()
        for raw in re.findall(r"[\w'-]+", text or "", re.UNICODE):
            word = fold(raw)
            base = stem(word)
            if len(word) < MIN_WORD or word in QUESTION_WORDS or base in QUESTION_WORDS or base in GENERIC_WORDS \
                    or word in GENERIC_WORDS or base in seen:
                continue
            seen.add(base)
            types, weathers = {}, {}
            for wid, w in self.worlds.items():
                named = [e for e in w["names"] + ([w["climate"]] if w["climate"] else []) if self._uses(e, word, base)]
                weather = [e for e in w["weathers"] if self._uses(e, word, base)]
                if named:
                    types[wid] = named
                if weather:
                    weathers[wid] = weather
            if not types and (not weathers or len(weathers) > MAX_WEATHER_WORLDS):
                continue
            out.append({"word": raw, "types": types,
                        "weathers": {k: v for k, v in weathers.items() if k not in types}
                        if len(weathers) <= MAX_WEATHER_WORLDS or types else {}})
        return out

    def explain(self, text: str, max_terms: int = 4) -> list[str]:
        """For the persona, one line per game term of a question: what the game means by it ("stickige" = the
        German game's "Airless" - an airless (dead) world - plus the swamp weather "Stickiger Sprühregen")."""
        titles = {w.id: w for w in WORLD_TYPES}

        def shown(entries):
            pairs = []
            for e in entries:
                text = f"'{e['local']}' = '{e['en']}'" if e["local"] else f"'{e['en']}'"
                if text not in pairs:
                    pairs.append(text)
            return ", ".join(pairs[:3])
        out = []
        for m in self.matches(text)[:max_terms]:
            parts = []
            for wid, entries in m["types"].items():
                wt = titles[wid]
                parts.append(f"{shown(entries)} = {wt.title.lower()} ({wt.summary}; planet records: "
                             f"{', '.join(wt.biomes)})")
            weather_only = m["weathers"] if len(m["weathers"]) <= MAX_WEATHER_WORLDS else {}
            for wid, entries in weather_only.items():
                parts.append(f"{'also ' if parts else ''}the weather {shown(entries)} on {titles[wid].title.lower()}")
            if parts:
                out.append(f"Game term '{m['word']}' in the game's words: " + "; ".join(parts) + ".")
        return out

    def documents(self, lookup, terms=None) -> dict[str, str]:
        """{relative path: Markdown}: one Codex document per world type and language (English, and the game's
        language) - every name the game gives such planets and their weathers in that language, its climate word,
        typical resources and the harvester gas, researched facts with their source."""
        from . import game_terms
        terms = terms or game_terms.GameTerms(language=self.language or "english")
        out = {}
        langs = ["english"] + ([self.language] if self.language and self.language not in ("english", "usenglish") else [])
        for language in langs:
            local = language != "english"
            h = lambda key, language=language, **v: game_terms.heading(key, language, **v)   # noqa: E731
            folder = f"{_label(language)}/{h('worlds')}"
            for wt in WORLD_TYPES:
                w = self.worlds.get(wt.id) or {}
                if not (w.get("names") or w.get("weathers")):
                    continue
                pick = (lambda e: e.get("local") or e["en"]) if local else (lambda e: e["en"])
                climate = w.get("climate")
                if local and language == "german":
                    title = GERMAN_TITLES.get(wt.id, wt.title)
                elif local and climate and climate.get("local"):
                    title = f"{climate['local']} ({wt.title})"
                else:
                    title = wt.title
                summary = GERMAN_SUMMARIES.get(wt.id) if language == "german" else None
                summary = summary or (wt.summary[0].upper() + wt.summary[1:] + ".")
                tags = [wt.id, *wt.biomes] + ([climate["local"]] if local and climate and climate.get("local") else [])
                lines = _front(title, tags, language) + [f"# {title}", "", summary, ""]
                if climate:
                    lines += [h("climate_word", word=pick(climate)), ""]
                lines += [h("biomes", b=", ".join(wt.biomes)), ""]
                facts = FACTS.get(wt.id)
                points = (FACTS_DE.get(wt.id) if language == "german" else None) or (facts or {}).get("points")
                if points:
                    lines += [f"## {h('world_like')}", ""] + [f"- {x}" for x in points] + \
                             ["", h("source", s=facts["source"]), ""]
                res = [r for r in wt.resources if lookup(r)]
                if res or wt.gas:
                    lines += [f"## {h('resources')}", ""]
                    for r in res:
                        e = lookup(r) or {}
                        lines.append(f"- {(e.get('local') if local else None) or e.get('en') or r}")
                    if wt.gas:
                        g = lookup(wt.gas) or {}
                        gas = (g.get("local") if local else None) or g.get("en") or wt.gas
                        lines.append(f"- {h('gas', harvester=terms.get('harvester', language), gas=gas)}")
                    lines.append("")
                if w.get("names"):
                    names = list(dict.fromkeys(pick(n) for n in w["names"]))
                    lines += [f"## {h('planet_names')}", ""] + [f"- {n}" for n in names] + [""]
                if w.get("weathers"):
                    seen = {}
                    for x in w["weathers"]:
                        seen.setdefault(pick(x), x["extreme"])
                    lines += [f"## {h('weather')}", ""] + [f"- {n}" + (f" ({h('extreme')})" if ext else "")
                                                           for n, ext in seen.items()] + [""]
                text = re.sub(r"\n(?=- )", "\n\n", "\n".join(lines)).replace("\n\n\n", "\n\n")
                out[f"{folder}/{_file(title)}"] = text.rstrip() + "\n"
        return out


def _label(language: str) -> str:
    from .game_install import language_label
    return language_label(language)


def _front(title: str, tags: list[str], language: str) -> list[str]:
    from .game_terms import LANGUAGE_CODES
    return ["---", f"title: {json.dumps(title, ensure_ascii=False)}",
            "tags: [" + ", ".join(json.dumps(t, ensure_ascii=False) for t in tags) + "]",
            f"language: {LANGUAGE_CODES.get(language, 'en')}",
            f"# {GENERATED_MARK} - edits are overwritten when the documents are generated again", "---", ""]


GERMAN_TITLES = {
    "dead": "Stickige Welten (tot, ohne Atmosphäre)", "lush": "Grüne Welten (üppig)", "toxic": "Giftige Welten",
    "scorched": "Sengend heiße Welten", "frozen": "Gefrorene Welten", "radioactive": "Verstrahlte Welten (radioaktiv)",
    "barren": "Unwirtliche Welten (Wüste)", "swamp": "Sumpfige Welten", "lava": "Vulkanische Welten (Lava)",
    "water": "Ozeanwelten", "exotic": "Ungewöhnliche Welten (exotisch)", "gasgiant": "Gasriesen",
}
# The researched facts in German (same source as FACTS).
FACTS_DE = {
    "dead": [
        "Keine Atmosphäre und geringere Schwerkraft; felsige, staubige Oberflächen wie Merkur oder der Mond.",
        "Keine gewöhnliche Flora oder Fauna, und es gibt nie Stürme.",
        "Mehr Ressourcen als andere Biome; hier findet man Verrostetes Metall.",
        "Flüsternde Eier (Flüsterndes Ei) liegen überall auf der Oberfläche (50-70 Einheiten auseinander) und setzen Biologische "
        "Abscheulichkeiten frei, wenn man sie stört - auf anderen Welten nur bei verlassenen Gebäuden.",
        "Die roten (Sauerstoff), gelben (Natrium) und blauen (Energie für den Exo-Anzug) Pflanzen wachsen trotzdem; manche "
        "stickigen Welten haben Pflanzen unterirdisch, in Höhlen.",
        "Keine Bauwerke wie Handelsposten.",
        "Die Lebenserhaltung leert sich schneller: Lebenserhaltungsgel, Sauerstoff und Dioxit mitnehmen.",
    ],
}


GENERATED_MARK = "generated: nomanssky-plugin worlds"
WORLDS_DIR = "Worlds"


def _file(title: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip(" .")[:120] + ".md"


def wanted_key(key: str) -> bool:
    """The language keys the world types need (planet names, weathers, climate words)."""
    return bool(_WANTED_RE.match(key))


_WANTED_RE = re.compile(r"^(" + "|".join(sorted({re.escape(p) for wt in WORLD_TYPES
                                                  for p in wt.type_prefixes + wt.weather_prefixes})) + r")\d+$"
                        r"|^UI_VISIT_CLIMATE_")


def load(install) -> WorldBook:
    """The world-type texts of an installation (blocking: reads the English and the game's language files)."""
    from .game_terms import read_language
    if install is None:
        return WorldBook(error="game installation not found")
    try:
        english, local, language = read_language(install, wanted_key)
        return WorldBook.from_texts(english, local, language)
    except (OSError, KeyError, ValueError, RuntimeError) as exc:      # PakError is a ValueError, ZstdUnavailable a RuntimeError
        return WorldBook(error=f"{type(exc).__name__}: {exc}")
