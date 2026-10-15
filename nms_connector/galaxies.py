"""The 256 galaxies: their names, what kind each one is, and what that changes (pure).

A system's packed address carries its galaxy (``galaxy.galaxy_of``), so the plugin always knows which
galaxy a system, planet or base is in - it just had names for the first ten and said "Galaxy #37" for the
rest.

**The names are not in the game's files.** Only the first five have language keys (``MAIN_GALAXY``,
``SECOND_GALAXY`` … ``FIFTH_GALAXY``, checked on build 25732212, 2026-10-15); the rest live in the
executable's own data and are community-recorded. ``NAMES`` is that list, in address order (index 0 =
Euclid = galaxy 1).

**The kind of a galaxy follows a fixed pattern.** Three kinds sit at the same six places of every block of
twenty galaxy numbers (``KIND_IN_TWENTY``), everything else is a normal galaxy. The pattern was derived
from the galaxies the wiki labels (3 Calypso harsh, 7 Budullangr empty, 10 Eissentam lush, 12 Aptarkaba
empty, 15 Ogtialabi harsh, 19 Isdoraijung lush, then +20 for each of them) and it reproduces the wiki's
own totals exactly: 26 harsh, 26 empty, 25 lush, the rest normal.

What the kind changes is **planet generation**, not the rules of the game: resources, recipes, prices,
hyperdrive range, races and progression are the same everywhere. The sourced detail, the game's own
descriptor words and the disagreements between sources are in ``research/galaxies.json``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from . import logs

RESEARCH_FILE = Path(__file__).resolve().parent.parent / "research" / "galaxies.json"

#: Every galaxy in address order: NAMES[0] is Euclid, which the game calls galaxy 1.
NAMES = [
    "Euclid", "Hilbert Dimension", "Calypso", "Hesperius Dimension", "Hyades",
    "Ickjamatew", "Budullangr", "Kikolgallr", "Eltiensleen", "Eissentam",
    "Elkupalos", "Aptarkaba", "Ontiniangp", "Odiwagiri", "Ogtialabi",
    "Muhacksonto", "Hitonskyer", "Rerasmutul", "Isdoraijung", "Doctinawyra",
    "Loychazinq", "Zukasizawa", "Ekwathore", "Yeberhahne", "Twerbetek",
    "Sivarates", "Eajerandal", "Aldukesci", "Wotyarogii", "Sudzerbal",
    "Maupenzhay", "Sugueziume", "Brogoweldian", "Ehbogdenbu", "Ijsenufryos",
    "Nipikulha", "Autsurabin", "Lusontrygiamh", "Rewmanawa", "Ethiophodhe",
    "Urastrykle", "Xobeurindj", "Oniijialdu", "Wucetosucc", "Ebyeloof",
    "Odyavanta", "Milekistri", "Waferganh", "Agnusopwit", "Teyaypilny",
    "Zalienkosm", "Ladgudiraf", "Mushonponte", "Amsentisz", "Fladiselm",
    "Laanawemb", "Ilkerloor", "Davanossi", "Ploehrliou", "Corpinyaya",
    "Leckandmeram", "Quulngais", "Nokokipsechl", "Rinblodesa", "Loydporpen",
    "Ibtrevskip", "Elkowaldb", "Heholhofsko", "Yebrilowisod", "Husalvangewi",
    "Ovna'uesed", "Bahibusey", "Nuybeliaure", "Doshawchuc", "Ruckinarkh",
    "Thorettac", "Nuponoparau", "Moglaschil", "Uiweupose", "Nasmilete",
    "Ekdaluskin", "Hakapanasy", "Dimonimba", "Cajaccari", "Olonerovo",
    "Umlanswick", "Henayliszm", "Utzenmate", "Umirpaiya", "Paholiang",
    "Iaereznika", "Yudukagath", "Boealalosnj", "Yaevarcko", "Coellosipp",
    "Wayndohalou", "Smoduraykl", "Apmaneessu", "Hicanpaav", "Akvasanta",
    "Tuychelisaor", "Rivskimbe", "Daksanquix", "Kissonlin", "Aediabiel",
    "Ulosaginyik", "Roclaytonycar", "Kichiaroa", "Irceauffey", "Nudquathsenfe",
    "Getaizakaal", "Hansolmien", "Bloytisagra", "Ladsenlay", "Luyugoslasr",
    "Ubredhatk", "Cidoniana", "Jasinessa", "Torweierf", "Saffneckm",
    "Thnistner", "Dotusingg", "Luleukous", "Jelmandan", "Otimanaso",
    "Enjaxusanto", "Sezviktorew", "Zikehpm", "Bephembah", "Broomerrai",
    "Meximicka", "Venessika", "Gaiteseling", "Zosakasiro", "Drajayanes",
    "Ooibekuar", "Urckiansi", "Dozivadido", "Emiekereks", "Meykinunukur",
    "Kimycuristh", "Roansfien", "Isgarmeso", "Daitibeli", "Gucuttarik",
    "Enlaythie", "Drewweste", "Akbulkabi", "Homskiw", "Zavainlani",
    "Jewijkmas", "Itlhotagra", "Podalicess", "Hiviusauer", "Halsebenk",
    "Puikitoac", "Gaybakuaria", "Grbodubhe", "Rycempler", "Indjalala",
    "Fontenikk", "Pasycihelwhee", "Ikbaksmit", "Telicianses", "Oyleyzhan",
    "Uagerosat", "Impoxectin", "Twoodmand", "Hilfsesorbs", "Ezdaranit",
    "Wiensanshe", "Ewheelonc", "Litzmantufa", "Emarmatosi", "Mufimbomacvi",
    "Wongquarum", "Hapirajua", "Igbinduina", "Wepaitvas", "Sthatigudi",
    "Yekathsebehn", "Ebedeagurst", "Nolisonia", "Ulexovitab", "Iodhinxois",
    "Irroswitzs", "Bifredait", "Beiraghedwe", "Yeonatlak", "Cugnatachh",
    "Nozoryenki", "Ebralduri", "Evcickcandj", "Ziybosswin", "Heperclait",
    "Sugiuniam", "Aaseertush", "Uglyestemaa", "Horeroedsh", "Drundemiso",
    "Ityanianat", "Purneyrine", "Dokiessmat", "Nupiacheh", "Dihewsonj",
    "Rudrailhik", "Tweretnort", "Snatreetze", "Iwundaracos", "Digarlewena",
    "Erquagsta", "Logovoloin", "Boyaghosganh", "Kuolungau", "Pehneldept",
    "Yevettiiqidcon", "Sahliacabru", "Noggalterpor", "Chmageaki", "Veticueca",
    "Vittesbursul", "Nootanore", "Innebdjerah", "Kisvarcini", "Cuzcogipper",
    "Pamanhermonsu", "Brotoghek", "Mibittara", "Huruahili", "Raldwicarn",
    "Ezdartlic", "Badesclema", "Isenkeyan", "Iadoitesu", "Yagrovoisi",
    "Ewcomechio", "Inunnunnoda", "Dischiutun", "Yuwarugha", "Ialmendra",
    "Reponudrle", "Rinjanagrbo", "Zeziceloh", "Oeileutasc", "Zicniijinis",
    "Dugnowarilda", "Neuxoisan", "Ilmenhorn", "Rukwatsuku", "Nepitzaspru",
    "Chcehoemig", "Haffneyrin", "Uliciawai", "Tuhgrespod", "Iousongola",
    "Odyalutai",
]

NORMAL, LUSH, HARSH, EMPTY = "normal", "lush", "harsh", "empty"

#: Galaxy **number** modulo 20 -> its kind. Everything else is a normal galaxy.
KIND_IN_TWENTY = {3: HARSH, 7: EMPTY, 10: LUSH, 12: EMPTY, 15: HARSH, 19: LUSH}

#: What each kind is, in one line, and what it changes. The long form, the game's own descriptor words
#: ("a Tranquil galaxy") and the sources are in research/galaxies.json; this is what the page always has.
KINDS = {
    NORMAL: {"label": "Normal", "hologram": "cyan",
             "text": "The usual mix of worlds and weather - 179 of the 256 galaxies are like this."},
    LUSH: {"label": "Lush", "hologram": "green",
           "text": "Lush, green worlds are far more common (about four times as likely around yellow stars) "
                   "and dead ones half as likely; weather is milder."},
    HARSH: {"label": "Harsh", "hologram": "red",
            "text": "Hostile worlds - toxic, scorched, frozen, irradiated - are more common, and players "
                    "report more aggressive Sentinels."},
    EMPTY: {"label": "Empty", "hologram": "blue",
            "text": "Dead, barren worlds are about four times as likely, star systems are sparser, and most "
                    "worlds carry little flora or fauna."},
}

#: What a galaxy's kind does *not* change (the same in all 256).
UNCHANGED = ("Resources, recipes, prices, item drops, hyperdrive range, the races and the whole progression "
             "are the same in every galaxy: the kind only changes how planets are generated.")


def count() -> int:
    return len(NAMES)


def number(index: int) -> int:
    """The galaxy number the game shows (1-256) for an address' RealityIndex (0-255)."""
    return index + 1


def name(index) -> str:
    """'Calypso' for RealityIndex 2; 'Galaxy #37' for an index beyond the recorded names."""
    if isinstance(index, bool) or not isinstance(index, int):
        return "unknown"
    if 0 <= index < len(NAMES):
        return NAMES[index]
    return f"Galaxy #{number(index)}"


def kind(index) -> str:
    """The kind of this galaxy, from the pattern. An index outside 0-255 counts as a normal galaxy."""
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(NAMES):
        return NORMAL
    return KIND_IN_TWENTY.get(number(index) % 20, NORMAL)


def kind_label(index) -> str:
    return KINDS[kind(index)]["label"]


def label(index) -> str:
    """'Calypso (galaxy 3 of 256, harsh)' - the one-line name for a details panel or a chat line.

    An index the universe has no galaxy for keeps its bare name: claiming a kind and a place in 256 for
    it would be inventing both."""
    if not isinstance(index, int) or isinstance(index, bool):
        return "unknown galaxy"
    if not 0 <= index < len(NAMES):
        return name(index)
    return f"{name(index)} (galaxy {number(index)} of {count()}, {kind(index)})"


def of_kind(wanted: str) -> list[int]:
    """Every galaxy index of one kind, in order."""
    return [i for i in range(len(NAMES)) if kind(i) == wanted]


def kind_counts() -> dict:
    """{kind: how many galaxies} - the check against the recorded totals (26 harsh, 26 empty, 25 lush)."""
    return {k: len(of_kind(k)) for k in (NORMAL, LUSH, HARSH, EMPTY)}


def load_research(path: Path | None = None) -> dict:
    """The researched galaxy facts ({} when the file is missing, as with the other research files)."""
    data = logs.read_json(path or RESEARCH_FILE, "The researched galaxy file")
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def research() -> dict:
    """`load_research`, read once per process: the view is built on every 5 s poll and this is a shipped
    file that cannot change under a running host."""
    return load_research()


def kind_facts(index, research: dict | None = None) -> list[str]:
    """What this galaxy's kind means, longest known form first: the researched bullets when the file is
    there, else the built-in line. Always ends with what the kind does not change."""
    entry = ((research or {}).get("kinds") or {}).get(kind(index)) or {}
    bullets = [b for b in (entry.get("differences") or []) if isinstance(b, str)]
    return (bullets or [KINDS[kind(index)]["text"]]) + [UNCHANGED]


def descriptors(index, research: dict | None = None) -> list[str]:
    """The words the game itself uses for a galaxy of this kind ("a Tranquil galaxy"), when researched."""
    entry = ((research or {}).get("kinds") or {}).get(kind(index)) or {}
    return [w for w in (entry.get("descriptors") or []) if isinstance(w, str)]
