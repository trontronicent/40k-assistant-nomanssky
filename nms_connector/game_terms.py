"""The game's own words for the things the Codex documents talk about, in English and the game's language.

Researched in the language files on 2026-10-06 (build 25625620): the German game calls the cooker
**Nährstoffprozessor** (the item documents said "Nahrungsprozessor" before), the refiners **Tragbare / Mittlere /
Große Raffinerie**, the gas harvester **Atmosphärenverarbeitungsanlage**, crafting **Herstellen**, raw materials
**Rohstoffe**, and an item's uses **Verwendet für:**. ``TERM_KEYS`` names the language key of each concept,
``FALLBACK`` the values read then (used when a key is missing after a game update).

Section headings the game has no word for ("Where it comes from") are the plugin's own (``HEADINGS``), in English
and German; other game languages get the English headings with the game's names.

``read_language(install, wanted)`` reads the English and the game's language tables once (the world types and the
terms share it); ``GameTerms.get(concept, language)`` answers a term.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import mbin

TERM_KEYS = {
    "refiner_portable": "REFINER1_NAME_L", "refiner_medium": "REFINER2_NAME_L", "refiner_large": "REFINER3_NAME_L",
    "processor": "UI_OVEN_NAME_L", "harvester": "BLD_GASHARVESTER_NAME_L", "extractor": "BLD_U_EXTRACTOR_NAME_L",
    "crafting": "ITEMUSE_CRAFT", "cooking": "ITEMUSE_COOK", "recipes": "UI_PORTAL_CAT_RECIPES",
    "raw": "UI_GUIDE_HEADING_SUB_CATA", "products": "BUI_PRODUCTS", "food": "UI_BOTTLE_MSG_LOST_ITEM_5",
    "description": "DESCRIPTION", "used_for": "POPUP_USEDFOR", "sentinels": "ATLAS_SENTINELS",
    "hazard": "PROTECT_NAME_L", "gas_giant": "GASGIANT1", "planet": "PLANET", "moon": "MOON",
    "mined": "BUI_MINED", "harvested": "WAR_HARVESTED",
}
FALLBACK = {
    "english": {"refiner_portable": "Portable Refiner", "refiner_medium": "Medium Refiner",
                "refiner_large": "Large Refiner", "processor": "Nutrient Processor", "harvester": "Atmosphere Harvester",
                "extractor": "Mineral Extractor", "crafting": "Crafting", "cooking": "Cooking", "recipes": "Recipes",
                "raw": "Raw Materials", "products": "Products", "food": "Food", "description": "Description",
                "used_for": "Used for:", "sentinels": "Sentinels", "hazard": "Hazard Protection",
                "gas_giant": "Gas Giant", "planet": "Planet", "moon": "Moon", "mined": "mined", "harvested": "harvested"},
    "german": {"refiner_portable": "Tragbare Raffinerie", "refiner_medium": "Mittlere Raffinerie",
               "refiner_large": "Große Raffinerie", "processor": "Nährstoffprozessor",
               "harvester": "Atmosphärenverarbeitungsanlage", "extractor": "Mineralienextraktor", "crafting": "Herstellen",
               "cooking": "Kochen", "recipes": "Rezepte", "raw": "Rohstoffe", "products": "Produkte", "food": "Nahrung",
               "description": "Beschreibung", "used_for": "Verwendet für:", "sentinels": "Wächter",
               "hazard": "Gefahrenschutz", "gas_giant": "Gasriese", "planet": "Planet", "moon": "Mond",
               "mined": "abgebaut", "harvested": "geerntet"},
}
# Concepts written in lower case in the game ("products", "food") that head a folder or section.
CAPITALISE = {"products", "food", "sentinels"}

# The plugin's own wording, where the game has no text.
HEADINGS = {
    "english": {"where_from": "Where it comes from", "about": "About", "refined": "Refiner recipes",
                "cooked": "Cooking recipes", "crafted": "Crafting recipe", "uses_refiner": "In the refiner",
                "uses_crafting": "To craft", "uses_cooking": "For cooking", "gathered": (
                    "No refiner or crafting recipe makes {name}: it is gathered (mined, harvested or collected) only."),
                "game_data": "Game data", "item_id": "Item id", "other_name": "In the {lang_name} game: {name}.",
                "and_more": "… and {n} more", "world_like": "What such a world is like", "resources": "Typical resources",
                "planet_names": "Planet names the game uses", "weather": "Weather", "extreme": "extreme weather - storms",
                "climate_word": "The game's word for this climate: **{word}**.", "biomes": "Planet records call this biome: {b}.",
                "gas": "{harvester} gas: {gas}", "source": "Source: {s}.", "worlds": "Worlds"},
    "german": {"where_from": "Fundort", "about": "Beschreibung", "refined": "Raffinerie-Rezepte",
               "cooked": "Kochrezepte", "crafted": "Herstellung", "uses_refiner": "In der Raffinerie",
               "uses_crafting": "Zum Herstellen von", "uses_cooking": "Zum Kochen", "gathered": (
                   "Keine Raffinerie und kein Rezept stellt {name} her: es wird nur gesammelt (abgebaut, geerntet "
                   "oder aufgelesen)."),
               "game_data": "Spieldaten", "item_id": "Gegenstands-ID", "other_name": "Im Spiel auf {lang_name}: {name}.",
               "and_more": "… und {n} weitere", "world_like": "Wie solche Welten sind", "resources": "Typische Ressourcen",
               "planet_names": "Planetenbezeichnungen im Spiel", "weather": "Wetter", "extreme": "Extremwetter - Stürme",
               "climate_word": "Das Wort des Spiels für dieses Klima: **{word}**.",
               "biomes": "Im Planetenverzeichnis heißt dieses Biom: {b}.",
               "gas": "Gas für die {harvester}: {gas}", "source": "Quelle: {s}.", "worlds": "Welten"},
}
# ISO codes for the documents' `language` front matter (the app prefers documents in the question's language).
LANGUAGE_CODES = {"english": "en", "usenglish": "en", "german": "de", "french": "fr", "italian": "it",
                  "spanish": "es", "latinamericanspanish": "es", "brazilianportuguese": "pt", "portuguese": "pt",
                  "polish": "pl", "russian": "ru", "japanese": "ja", "korean": "ko", "simplifiedchinese": "zh",
                  "traditionalchinese": "zh", "tencentchinese": "zh", "dutch": "nl"}


# How each language names the others ("In the German game", "Im Spiel auf Englisch").
LANGUAGE_NAMES = {"english": {"english": "English", "german": "German", "french": "French", "italian": "Italian",
                              "spanish": "Spanish", "dutch": "Dutch", "polish": "Polish", "russian": "Russian"},
                  "german": {"english": "Englisch", "german": "Deutsch", "french": "Französisch",
                             "italian": "Italienisch", "spanish": "Spanisch", "dutch": "Niederländisch",
                             "polish": "Polnisch", "russian": "Russisch"}}


def language_name(of: str, written_in: str) -> str:
    """'german' written in English -> 'German'; 'english' written in German -> 'Englisch'."""
    from .game_install import language_label
    return LANGUAGE_NAMES.get(written_in, LANGUAGE_NAMES["english"]).get(of) or language_label(of)


def heading(key: str, language: str, **values) -> str:
    """One of the plugin's own headings/sentences in `language` (English for languages it has none in)."""
    text = HEADINGS.get(language, HEADINGS["english"]).get(key) or HEADINGS["english"][key]
    return text.format(**values) if values else text


@dataclass
class GameTerms:
    """The game's words for TERM_KEYS in English and the game's language (`local`)."""
    english: dict[str, str] = field(default_factory=dict)
    local: dict[str, str] = field(default_factory=dict)
    language: str = "english"
    error: str | None = None

    @classmethod
    def from_texts(cls, english: dict[str, str], local: dict[str, str] | None, language: str = "english") -> "GameTerms":
        def pick(texts):
            return {c: " ".join((mbin.clean_text(texts.get(k)) or "").split()) for c, k in TERM_KEYS.items()
                    if texts.get(k)}
        return cls(pick(english), pick(local or {}), language)

    def get(self, concept: str, language: str = "english") -> str:
        """The term in `language` (the game's language or English): read from the game, else measured fallback."""
        found = (self.english if language in ("english", "usenglish") else self.local).get(concept)
        text = found or FALLBACK.get(language, {}).get(concept) or self.english.get(concept) \
            or FALLBACK["english"][concept]
        return text[0].upper() + text[1:] if concept in CAPITALISE and text else text


def term_keys_wanted(key: str) -> bool:
    return key in _TERM_KEY_SET


_TERM_KEY_SET = set(TERM_KEYS.values())


def read_language(install, wanted) -> tuple[dict[str, str], dict[str, str] | None, str]:
    """(English texts, game-language texts or None for an English game, language suffix) of the keys `wanted(key)`
    accepts - one pass over the language files (blocking)."""
    from . import hgpak
    from .gamedata import PAK_HINTS
    language = getattr(install, "language", None) or "english"
    texts: dict[str, dict[str, str]] = {"english": {}, language: {}}
    with hgpak.PakSet(install.pcbanks, PAK_HINTS) as paks:
        for lang in dict.fromkeys(("english", language)):
            for name in paks.names_matching("language/", f"_{lang}.mbin"):
                for key, text in mbin.parse_language_table(paks.read(name)).items():
                    if wanted(key):
                        texts[lang][key] = text
    return texts["english"], (texts[language] if language not in ("english", "usenglish") else None), language


def load(install) -> GameTerms:
    """The terms of an installation; the measured fallbacks when the game cannot be read."""
    if install is None:
        return GameTerms()
    try:
        english, local, language = read_language(install, term_keys_wanted)
        return GameTerms.from_texts(english, local, language)
    except (OSError, KeyError, ValueError, RuntimeError) as exc:     # PakError is a ValueError, ZstdUnavailable a RuntimeError
        return GameTerms(language=getattr(install, "language", "english"), error=f"{type(exc).__name__}: {exc}")

