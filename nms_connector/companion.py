"""The No Man's Sky Plugin Persona: the persona this plugin brings, and the game data for each of its replies.

App 3.9.0 stores the persona from ``personas()`` once and calls ``chat_context(question)`` before every reply of a
persona that draws on this plugin, injecting the text into its system prompt as ``[GAME DATA: No Man's Sky]``
(an injection, not a tool: llama.cpp drops tools). ``assistant.build_context`` (pure) assembles items, places and
trade goods; this class adds what needs the connector's state: status lines, settlements, economies and - for a
question about equipment - the installed technology with what it does.

The persona also carries a ``setup`` (app 3.10.0): the plugin page asks, while linking the persona to a model,
whether it should draw on a Codex knowledge library (suggested: one whose name contains "No Man's Sky") and use
web search when the model can. Game mechanics, recipes and lore come from there; the player's own numbers only from
the game data.
"""

from __future__ import annotations

import re
import time

from . import assistant, galaxy, planet_search, planets_view, recipes, settlements, timers, trade

PERSONA_PROMPT = (
    "You are the No Man's Sky Plugin Persona, the player's companion for No Man's Sky. With every message you "
    "get a [GAME DATA: No Man's Sky] block: live data from the player's game - inventories with totals per "
    "item and per place, currencies, location, ships and warp range, equipment and what it does, settlements, "
    "frigates and timers.\n\n"
    "Answer questions about their game from that block, every part of a question. For amounts, give the total first, "
    "then where it is (\"You have 1,234 Copper: 500 in the exosuit, 734 in Storage Container 0.\"). Name items in the "
    "player's language - the block gives the English name and, in brackets, the game's language - and leave out the "
    "item ids in square brackets unless asked. If the block does not contain what was asked, say so plainly and "
    "suggest where to look in the game - never invent numbers. Mention when the data comes from an older save if it "
    "matters. Upgrade modules show the range their stats can have; the game keeps the exact values to itself, so "
    "give the range and say so. For trade goods the block groups them by kind (Technology, Minerals, ...) with the "
    "game's base value, what a buyer pays and the nearest known system that needs the kind: answer \"what kind\" and "
    "\"where to sell\" questions from it, the most valuable kind first. For a question about planets (\"where are "
    "scorching hot planets?\") the block lists the recorded planets that match it, nearest first; when it says "
    "\"N recorded planets match ... the nearest M of them\", N is the answer to \"how many\", not M.\n\n"
    "Game words mean what the game means by them. A \"Game term\" line in the block says what a word of the "
    "question is in the game (the German game's \"stickig\" is airless - a dead world without atmosphere - not "
    "sticky): use that meaning. Never translate game names yourself - planet types, weathers, items, refiners and "
    "buildings are named in the block in English and the game's language, so use the name in the player's "
    "language exactly as given. \"How to get\" lines come from the game's own recipe tables: prefer them to Codex "
    "excerpts and to your memory, which may be from an older version of the game. Codex excerpts may be in German "
    "or English; quote names from them as they are written.\n\n"
    "For general No Man's Sky questions (recipes, mechanics, lore) use the Codex excerpts or web search results when "
    "you are given them and cite them as given; otherwise answer from your own knowledge and say that it is not from "
    "their save. The player's own numbers come only from the game data. Be concise and friendly; answer in the "
    "language the player writes in."
)

PERSONA_SLUG = "companion"
PERSONA_VOICE = "ai-male"     # the app's voice key: Cogitator AI (Male), Kokoro bm_george
PERSONA_ID = f"plugin-nomanssky-{PERSONA_SLUG}"     # the app's reserved id: plugin-<plugin id>-<slug>

# What the plugin page asks while linking the persona to a model (app 3.10.0, plugins/personas.normalize_setup).
PERSONA_SETUP = {
    "knowledge": {"ask": True, "suggest": "No Man's Sky", "mode": "auto",
                  "why": "Recipes, mechanics and lore from your Codex library - the game data only knows your save."},
    "web_search": {"ask": True, "mode": "tool",
                   "why": "Look up current game facts (updates, expeditions) when the model can search."},
}

SETTLEMENT_WORDS = {"settlement", "settlements", "siedlung", "siedlungen", "overseer", "aufseher", "colony", "town"}
ECONOMY_WORDS = {"economy", "economies", "wirtschaft", "trade", "sell", "buy", "verkaufen", "kaufen", "handel"}
# A question about equipment: the installed technology of what it names (all of it when it names nothing).
EQUIPMENT_WORDS = {
    "multitool": "multitools", "multi-tool": "multitools", "multitools": "multitools", "multiwerkzeug": "multitools",
    "weapon": "multitools", "waffe": "multitools", "exosuit": "exosuit", "exoanzug": "exosuit", "suit": "exosuit",
    "anzug": "exosuit", "exocraft": "exocraft", "exo-fahrzeug": "exocraft", "vehicle": "exocraft",
    "fahrzeug": "exocraft", "roamer": "exocraft", "nautilon": "exocraft", "minotaur": "exocraft",
    "colossus": "exocraft", "pilgrim": "exocraft", "nomad": "exocraft", "freighter": "freighter", "frachter": "freighter",
    "ship": "ships", "starship": "ships", "schiff": "ships", "raumschiff": "ships",
}
TECH_WORDS = {"upgrade", "upgrades", "module", "modules", "modul", "technology", "technologies", "technologie",
              "technologien", "tech", "equipment", "ausrüstung", "installed", "installiert", "stats", "werte",
              "modifiers", "bonus", "boni", "slot", "slots"}
# A question about planets ("wo gibt es sengend heiße Planeten?"): the recorded planets that match its other words.
# A question about getting an item: its recipes and where it comes from are added (recipe_lines).
RECIPE_WORDS = {"recipe", "recipes", "refine", "refiner", "refining", "craft", "crafting", "make", "made", "produce",
                "obtain", "get", "find", "where", "mine", "mining", "harvest", "extract", "farm", "source",
                "rezept", "rezepte", "raffinerie", "raffinieren", "herstellen", "herstellung", "bauen", "machen",
                "bekommen", "finden", "wo", "abbauen", "gewinnen", "erzeugen", "farmen", "woher"}
MAX_RECIPE_ITEMS = 3
MAX_RECIPES_PER_ITEM = 6

PLANET_WORDS = {"planet", "planets", "planeten", "welt", "welten", "world", "worlds", "mond", "monde", "moon", "moons"}
MAX_PLANETS = 8
MAX_TECH_LINES = 40
MAX_TECH_CHARS = 5000     # the app cuts the whole game-data block at 8,000 characters


# The overlay's areas (app 3.12.0): (id, title, shown by default). The user ticks them on or off in the overlay.
OVERLAY_AREAS = [("timers", "Timers", True), ("location", "Where you are", True),
                 ("settlements", "Settlements", True), ("mission", "Current mission", False),
                 ("currencies", "Currencies", False), ("ships", "Ships", False), ("frigates", "Frigates", False)]


class PluginCompanion:
    """The persona and its chat data, for one connector (whose state is read on every call)."""

    def __init__(self, connector):
        self.connector = connector

    def personas(self) -> list[dict]:
        """The persona this plugin brings (the app stores it once; the user links it to a model)."""
        return [{
            "slug": PERSONA_SLUG, "name": "No Man's Sky Plugin Persona",
            "personality": "Helpful, precise with numbers, a seasoned traveller of the Euclid galaxy.",
            "speech_style": "Short and clear; totals first, then where things are.",
            "background": "Brought by the No Man's Sky plugin: answers from your live game data - inventories, "
                          "ships, equipment, settlements, frigates, timers and location.",
            "system_prompt": PERSONA_PROMPT, "temperature": 0.3, "setup": PERSONA_SETUP,
            # Default voice (app 3.12.0, ignored by older apps): the app's calm British ship-AI voice with its light
            # "ai" effect. The user can pick another one in the persona editor - e.g. ai-male-de for German.
            "voice": PERSONA_VOICE,
        }]

    def chat_context(self, question: str) -> dict:
        """The game data for one chat message (see assistant.py); the app injects it into the system prompt."""
        c = self.connector
        snap = c.snapshot
        ctx = c.context()
        text = c.describe

        def names_of(item_id):
            entry = c.gamedata.lookup(item_id) or {}
            return [n for n in dict.fromkeys([entry.get("en"), entry.get("local")]) if n]

        def name_of(item_id):
            return ctx.texts.name(item_id) or item_id

        here = c.here()

        def planets_offering(item_id):
            """The nearest recorded planets offering an item (resource, plant or gas), as 'name in system (distance)'."""
            found = []
            for planet in c.history.planets.values():
                gas = planets_view.planet_gas(planet)
                if item_id in (planet.get("common"), planet.get("uncommon"), planet.get("rare"), gas) \
                        or item_id in (planet.get("extra") or []):
                    dist = galaxy.distance_ly(here, planet["system"]) if here is not None else None
                    found.append((dist if dist is not None else 1e12, planet))
            found.sort(key=lambda d: d[0])
            out = []
            for dist, planet in found[:assistant.NEAREST_PLANETS]:
                system = planets_view._system_label(planet["system"], ctx.visit(planet["system"]))
                where = "your current system" if planet["system"] == here else galaxy.distance_text(dist if dist < 1e12 else None)
                out.append(f"{planet.get('name') or 'a planet'} in {system} ({where})")
            return out

        status = [f"No Man's Sky - data of the save written {assistant.saved_text((snap or {}).get('saved_at'))}"
                  + (", position live from the running game" if c.live.current_system is not None else "")]
        if snap:
            status.append(f"Units {snap.get('units') or 0:,}, Nanites {snap.get('nanites') or 0:,}, "
                          f"Quicksilver {snap.get('quicksilver') or 0:,}")
            if here is not None:
                status.append(f"You are in the system {planets_view._system_label(here, ctx.visit(here))} "
                              f"({snap['location'].get('galaxy')}), portal address {snap['location'].get('portal')}")
            status.append(f"Primary ship: {text.primary_ship()}")
            status.append(f"Freighter: {text.freighter(snap['freighter']['name'])}")
            status.append(f"Current mission: {text.mission(snap.get('current_mission'))}")
        extra = []
        now = time.time()
        shown = timers.visible(c.timers, now)
        if shown:
            extra.append("Timers: " + "; ".join(
                f"{t['label']} - {'done' if t['ends_at'] <= now else 'ends ' + timers.clock(t['ends_at'])}" for t in shown))
        if c.settlements:
            extra.append(f"Settlements: {text.settlements()}")
        if c.frigates:
            out_on = [f for f in c.frigates if f["on_expedition"]]
            extra.append(f"Frigates: {len(c.frigates)} ({len(out_on)} out on an expedition)")
        words = set(re.findall(r"[\w'-]+", (question or "").lower()))
        extra += self.settlement_lines(words, now)
        extra += self.economy_lines(question, ctx, here)
        extra += self.equipment_lines(words, ctx.texts)
        extra += self.planet_lines(question, words, ctx)
        extra += self.recipe_lines(question, words)
        extra += self.world_lines(question)
        all_names = {i: [n for n in (e.get("en"), e.get("local")) if n] for i, e in (c.gamedata.items or {}).items()}

        def item_notes(item_id):
            hint = ctx.trade_hint(item_id)        # trade goods: who pays well, the nearest known such system
            return " ".join(hint.split("\n")) if hint else None

        return {"title": "No Man's Sky", "text": assistant.build_context(
            question, snap, name_of, names_of, all_names, status, extra, planets_offering, item_notes,
            lambda place_names: self.kind_lines(snap, place_names, ctx, name_of)),
            # The Settings tab's "Single Context Per Question": this plugin's persona gets no earlier turns (3.11.0).
            "single_context": bool(getattr(getattr(c, "settings", None), "single_context", False))}

    def overlay(self) -> dict:
        """The desktop overlay in this plugin's mode (app 3.11.0): the running timers, where you are, the persona
        and its codeword (Settings tab). The overlay counts the timers down itself.

        App 3.12.0 draws ``areas`` instead: named blocks (OVERLAY_AREAS) the user ticks on or off in the overlay's
        right-click menu - the overlay keeps that choice, the plugin only says which are on by default. The flat
        ``timers``/``lines`` stay for older apps, which ignore ``areas``. ``codex_search`` adds the app's own area
        *Codex search*: the words typed, found in the libraries attached to this plugin's persona."""
        c = self.connector
        now = time.time()
        shown_timers = timers.visible(c.timers, now)[:20]
        here = self.where_lines()
        lines = here[:1]
        if c.settlements:
            lines.append(f"Settlements: {c.describe.settlements()}")
        settings = getattr(c, "settings", None)
        content = {"timers": shown_timers, "location": here, "settlements": self.settlement_overlay_lines(now),
                   "mission": self.mission_lines(), "currencies": self.currency_lines(), "ships": self.ship_lines(),
                   "frigates": self.frigate_lines()}
        areas = []
        for area_id, title, default_on in OVERLAY_AREAS:
            data = content[area_id]
            areas.append({"id": area_id, "title": title, "default_on": default_on,
                          "timers": data if area_id == "timers" else [], "lines": [] if area_id == "timers" else data})
        return {"title": "No Man's Sky", "timers": shown_timers, "lines": lines, "areas": areas,
                # App 3.12.0: a full-text search (no model) in the Codex libraries attached to the persona.
                "codex_search": True,
                "persona_id": PERSONA_ID, "codeword": getattr(settings, "codeword", None),
                # Switches in the overlay; clicking one runs the plugin's set_setting action (plugin.SET_SETTING).
                "toggles": settings.toggles("set_setting") if settings is not None else []}

    def where_lines(self) -> list[str]:
        """Overlay area *Where you are*: the system (live from the game, else the save's) and its galaxy."""
        c = self.connector
        here = c.here()
        if here is None:
            return []
        out = [f"You are in {planets_view._system_label(here, c.context().visit(here))}"]
        galaxy_name = ((c.snapshot or {}).get("location") or {}).get("galaxy")
        if galaxy_name:
            out.append(f"Galaxy: {galaxy_name}")
        return out

    def settlement_overlay_lines(self, now: float) -> list[str]:
        """Overlay area *Settlements*: one line per settlement - population, a waiting decision or the window of
        the next one (the game draws its moment inside JudgementWaitTimeMin..Max), the construction."""
        c = self.connector
        if not c.settlements:
            return []
        lo, hi = c.tables.settlement_rules["judgement_wait"]
        out = []
        for s in c.settlements:
            bits = [f"{s['population']} inhabitants"]
            if s["pending"] and s["pending"] != "None":
                bits.append(f"decision waiting ({settlements._words(s['pending'])})")
            elif s["last_judgement"]:
                start, end = s["last_judgement"] + lo, s["last_judgement"] + hi
                bits.append("next decision any time now" if end <= now else
                            f"next decision {timers.clock(max(start, now))}-{timers.clock(end)}")
            if s.get("building"):
                bits.append(f"{s['building']} in construction")
            out.append(f"{s['name']}: " + ", ".join(bits))
        return out

    def mission_lines(self) -> list[str]:
        """Overlay area *Current mission*: the mission as the game describes it."""
        mission = (self.connector.snapshot or {}).get("current_mission")
        return [self.connector.describe.mission(mission)] if mission else []

    def currency_lines(self) -> list[str]:
        """Overlay area *Currencies*: Units, Nanites and Quicksilver from the newest save."""
        snap = self.connector.snapshot
        if not snap:
            return []
        return [f"Units {snap.get('units') or 0:,}", f"Nanites {snap.get('nanites') or 0:,}",
                f"Quicksilver {snap.get('quicksilver') or 0:,}"]

    def ship_lines(self) -> list[str]:
        """Overlay area *Ships*: the primary ship with its warp range estimate, and the freighter."""
        c = self.connector
        out = []
        if any(s.get("primary") for s in c.ships):
            out.append(f"Ship: {c.describe.primary_ship()}")
        freighter = ((c.snapshot or {}).get("freighter") or {})
        if c.freighter or freighter.get("name"):
            out.append(f"Freighter: {c.describe.freighter(freighter.get('name'))}")
        return out

    def frigate_lines(self) -> list[str]:
        """Overlay area *Frigates*: the fleet and how many are out (their return is in *Timers*)."""
        frigates = self.connector.frigates
        if not frigates:
            return []
        out_on = sum(1 for f in frigates if f["on_expedition"])
        return [f"{len(frigates)} frigates, {out_on} out on an expedition"]

    def kind_lines(self, snap: dict, place_names: list[str] | None, ctx, name_of) -> list[str]:
        """Trade goods by kind (assistant.trade_kinds) with the game's base value, which economies buy the kind,
        what that pays and the nearest known system of such an economy - the most valuable kind first."""
        c = self.connector
        kinds = assistant.trade_kinds(snap, place_names, lambda i: (c.gamedata.lookup(i) or {}).get("value"))
        if not kinds:
            return []
        where = ", ".join(place_names) if place_names else "all your inventories"
        out = [f"Trade goods by kind in {where} (base value = the game's value per unit; a system whose economy needs "
               "the kind pays about the factor shown; the most valuable kind first):"]
        for kind in kinds:
            category = kind["category"]
            buyers = [e for e, t in ctx.trading.items() if t.get("needs") == category]
            low, high = ((ctx.trading[buyers[0]].get("buys_at") or (None, None))[:2]) if buyers else (None, None)
            goods = ", ".join(f"{name_of(i)} {amount:,}" for i, amount in kind["goods"][:4])
            line = f"- {trade.CATEGORY_NAMES.get(category, category)}: {kind['units']:,} units ({goods})"
            if kind["value"]:
                line += f"; base value {kind['value']:,} units"
                if low and high:
                    line += f", sold where needed about {kind['value'] * low:,.0f}-{kind['value'] * high:,.0f} units (x{low}-{high})"
            if buyers:
                nearest = ctx.nearest_economy(buyers)
                line += (f"; needed by {', '.join(ctx.economy_name(e) or e for e in buyers)} economies - nearest known: "
                         + (nearest or "none of your known systems yet"))
            out.append(line)
        return out

    def world_lines(self, question: str) -> list[str]:
        """What the game terms of a question mean, in the game's own words: "stickige" is the German game's
        "Airless" - an airless (dead) world - not "sticky" (worlds.WorldBook.explain; the model translated it
        wrong on 2026-10-06)."""
        book = getattr(self.connector.tables, "worlds", None)
        return book.explain(question) if book is not None and book.worlds else []

    def recipe_lines(self, question: str, words: set[str]) -> list[str]:
        """For a question about getting an item ("Wie bekomme ich Ammoniak?", "how to make Sulphurine"): per named
        item (<= MAX_RECIPE_ITEMS) where it comes from (the game's description), the refiner recipes that make it
        (<= MAX_RECIPES_PER_ITEM, best yield first) and its crafting recipe - from the game's own recipe table."""
        c = self.connector
        book = getattr(c.tables, "recipes", None)
        if not (words & RECIPE_WORDS) or book is None or not book.recipes:
            return []
        names = {i: [n for n in (e.get("en"), e.get("local")) if n] for i, e in (c.gamedata.items or {}).items()}
        lookup = c.gamedata.lookup
        out = []
        for item in assistant.match_items(question, names)[:MAX_RECIPE_ITEMS]:
            refined = book.made_by(item)
            crafted = book.crafting.get(item)
            entry = lookup(item) or {}
            if not (refined or crafted or entry.get("desc_en")):
                continue
            out.append(f"How to get {recipes.item_label(lookup, item)} (from the game's files):")
            if entry.get("desc_en"):
                out.append("  where it comes from: " + " ".join(entry["desc_en"].split()))
            for r in refined[:MAX_RECIPES_PER_ITEM]:
                out.append("  refiner: " + recipes.recipe_line(lookup, r, getattr(c.tables, "terms", None)))
            if len(refined) > MAX_RECIPES_PER_ITEM:
                out.append(f"  ... {len(refined) - MAX_RECIPES_PER_ITEM} more refiner recipes")
            if crafted:
                out.append("  crafted from: " + " + ".join(f"{a} {recipes.item_label(lookup, i)}" for i, a in crafted))
            if not (refined or crafted):
                out.append("  no refiner or crafting recipe makes it: it is gathered only")
        return out

    def settlement_lines(self, words: set[str], now: float) -> list[str]:
        """Settlement details for a question about them (or naming one): stats as the screen shows them when read,
        production, perks, the waiting decision, the construction."""
        c = self.connector
        names = {s["name"].lower() for s in c.settlements}
        if not (words & SETTLEMENT_WORDS or any(n.split()[0] in words for n in names if n)):
            return []
        rules = c.tables.settlement_rules
        out = []
        for s in c.settlements:
            out.append(f"Settlement {s['name']}: population {s['population']} ({s['race'] or 'unknown race'})")
            reading = c.settlement_live.values.get(s.get("seed"))
            if reading:
                shown = [f"{settlements.STAT_LABELS[st]} {settlements.shown(st, v, rules, s['population'])}"
                         for st, v in zip(settlements.STATS, reading["stats"]) if st not in ("Sentinels", "Debt")]
                out.append(f"  as its screen showed at {timers.clock(reading['at'])}: " + ", ".join(shown))
            if s["production"]:
                out.append("  production: " + "; ".join(
                    f"{(c.gamedata.lookup(p['item']) or {}).get('en') or p['item']} {p['amount']} of {p['cap']}"
                    for p in s["production"]))
            if s["pending"] and s["pending"] != "None":
                out.append(f"  a decision is waiting: {settlements._words(s['pending'])}")
            elif s["last_judgement"]:
                lo, hi = rules["judgement_wait"]
                out.append(f"  next decision between {timers.clock(s['last_judgement'] + lo)} and "
                           f"{timers.clock(s['last_judgement'] + hi)}")
            build = next((t for t in c.timers if t["key"].startswith("settlement.") and s["name"] in t["label"]), None)
            if build:
                out.append(f"  construction: {build['label']} - " + (f"finished at {timers.clock(build['ends_at'])}"
                           if build["ends_at"] <= now else f"ends {timers.clock(build['ends_at'])}"))
            out.append(f"  perks: {len(s['perks'])} (details in the plugin's Settlements tab)")
        return out

    def economy_lines(self, question: str, ctx, here) -> list[str]:
        """For a question about economies or trading: the nearest known systems of each economy it names (all
        economies when it names none), read or predicted from the game's generation rules (marked)."""
        q = (question or "").lower()
        named = [e for e in trade.ECONOMY_FALLBACK_NAMES
                 if any(n and n.lower() in q for n in (trade.ECONOMY_FALLBACK_NAMES[e], ctx.economy_name(e), e))]
        if not named and not (ECONOMY_WORDS & set(re.findall(r"[\w']+", q))):
            return []
        out = [f"Economy of your current system: {ctx.economy_summary(here) or 'unknown'}"] if here is not None else []
        for econ in named or list(trade.ECONOMY_FALLBACK_NAMES):
            keys = [k for k, e in ctx.economies.items()
                    if e.get("economy") == econ and galaxy.galaxy_of(k) == galaxy.galaxy_of(here or k)]
            keys.sort(key=lambda k: (galaxy.distance_ly(here, k) or 0) if here is not None else 0)
            if not keys:
                continue
            listed = []
            for k in keys[:3 if not named else 6]:
                e = ctx.economies[k]
                dist = galaxy.distance_text(galaxy.distance_ly(here, k), k == here) if here is not None else "?"
                listed.append(f"{planets_view._system_label(k, ctx.visit(k))} ({e.get('wealth')}, {dist}"
                              + (", predicted" if e.get("predicted") else "") + ")")
            out.append(f"Nearest {ctx.economy_name(econ)} systems: " + "; ".join(listed))
        return out

    def planet_lines(self, question: str, words: set[str], ctx) -> list[str]:
        """For a question about planets: the recorded planets that match most of its other words (type, weather,
        resources, flora, fauna, sentinels, name - English or the game's language), nearest first, with all they
        are known for (planet_search)."""
        if not {planet_search.fold(w) for w in words} & PLANET_WORDS:
            return []
        index = planets_view.planet_index(ctx)
        wanted, found = index.best(question, None)
        if not wanted:
            return []
        if not found:
            return [f"No recorded planet matches {', '.join(wanted)} ({len(index.entries)} planets recorded - planets "
                    "are recorded while you play with the game running)."]
        # The total first: with only the nearest MAX_PLANETS listed, the model counted the list ("8 giftige Planeten"
        # for 11 - live test 2026-10-06).
        shown = found[:MAX_PLANETS]
        out = [f"{len(found)} recorded planets match {', '.join(found[0][1])} (of the words {', '.join(wanted)}; "
               f"{len(index.entries)} planets recorded in all)"
               + (f"; the nearest {len(shown)} of them:" if len(found) > len(shown) else "; nearest first:")]
        for entry, _matched in shown:
            row = [planet_search._cell_text(c) for c in entry["row"]]
            facts = [f"{label}: {value}" for label, value in zip(planets_view.PLANET_COLUMNS[1:], row[1:]) if value]
            out.append(f"- {row[0]} in {entry['system_label']} ({index.distance_text(entry['system'])}): "
                       + "; ".join(facts))
        return out

    def equipment_lines(self, words: set[str], texts) -> list[str]:
        """For a question about equipment or upgrades: the installed technology of what it names (exosuit,
        multi-tools, exocraft, freighter, ships - all of them when it names none) with what each part does."""
        c = self.connector
        asked = {EQUIPMENT_WORDS[w] for w in words if w in EQUIPMENT_WORDS}
        # Only a question about equipment: "what is aboard my ship" names the ship but means its cargo (seen
        # 2026-10-05: a trade-goods question got the ship's whole technology and ran over the 8,000-character limit).
        if not words & TECH_WORDS:
            return []
        groups: list[tuple[str, list[dict]]] = []
        eq = c.equipment
        if eq is not None:
            if not asked or "exosuit" in asked:
                groups.append(("Exosuit", eq.exosuit.technology))
            if not asked or "multitools" in asked:
                groups += [(f"Multi-tool {t.name(texts)}", t.technology) for t in eq.multitools]
            if not asked or "exocraft" in asked:
                groups += [(f"Exocraft {v.name(texts)}", v.technology) for v in eq.exocraft]
            if not asked or "freighter" in asked:
                groups.append(("Freighter", eq.freighter.technology))
        if not asked or "ships" in asked:
            groups += [(f"Starship {s['name'] or s['type']}" + (" (primary)" if s["primary"] else ""), s["technology"])
                       for s in c.ships]
        tech_stats = getattr(c.gamedata, "tech", None)

        def english_modifiers(item_id):
            # English stat names only: half the length of 'Shield Strength (Schildstärke)', the model translates.
            if tech_stats is None or not tech_stats.ready:
                return texts.modifiers(item_id)
            return tech_stats.modifiers(item_id, lambda key: (c.gamedata.text(key) or {}).get("en"))

        out: list[str] = []
        used = 0
        for title, technology in groups:
            parts = []
            for tech in technology:
                if tech["id"].startswith("SHIPSLOT_DMG"):
                    continue
                mods = english_modifiers(tech["id"])
                parts.append(texts.name(tech["id"]) + (f" ({', '.join(mods)})" if mods else ""))
            line = f"{title}: " + ("; ".join(parts) if parts else "no technology")
            if out and (used + len(line) > MAX_TECH_CHARS or len(out) >= MAX_TECH_LINES):
                out.append("(more equipment in the plugin's Equipment tab - ask about one item, e.g. the multi-tool)")
                break
            out.append(line)
            used += len(line)
        if out:
            out.append("Upgrade modules list the range of each stat they can have; the exact values are not stored.")
        return out
