"""Who made this plugin and whose work it builds on - one list, read by everything that shows credits.

The same credits have to appear in four places, and they must not drift apart:

* the **About** tab of the connector's own page (`sections()`), which is why they live in the connector
  and not in a host: the app's plugin page and the standalone page then show the identical tab;
* the manifest's ``credits`` (`manifest_credits()`), which is what the app's manual shows under
  *Plugin Help*;
* ``THIRD-PARTY-NOTICES.md`` in the repository (`notices_markdown()`), which the installer ships;
* ``README.md`` and ``HELP.md``, which name the author.

``tests/test_credits.py`` compares the generated forms with the files in the repository, so changing a
credit here and forgetting the manifest or the notices file fails the suite.

What belongs here: everything whose licence asks to be named, and everything bundled in the standalone
installer. ``bundled`` says how the user gets it, because that is what decides whether a licence applies
to *our* distribution at all - the game's own files are read from the user's installation and never
redistributed, and `mapping.json` (LGPL) is downloaded at runtime for the same reason.
"""
from __future__ import annotations

from dataclasses import dataclass

AUTHOR = "Reto Kummer alias Reat Kay, Shorthand Dev / TronTronic Entertainment"
AUTHOR_URL = "https://github.com/trontronicent"
REPO_URL = "https://github.com/trontronicent/40k-assistant-nomanssky"
APP_REPO_URL = "https://github.com/trontronicent/40k-assistant"
LICENSE = "MIT"


@dataclass(frozen=True)
class Credit:
    """One credited work. ``what`` says what it gave this plugin, in the user's words, not the licence's."""

    name: str
    what: str
    license: str
    url: str = ""


@dataclass(frozen=True)
class Group:
    """A heading of the credits, with the sentence that says how these works reach the user."""

    title: str
    note: str
    entries: tuple[Credit, ...]


BUILT_ON = Group(
    "The work this plugin builds on",
    "Read or ported, never redistributed: the game's own data stays in your installation, and the save "
    "key mapping is downloaded from MBINCompiler when it is needed. The portal glyph pictures are this "
    "plugin's own artwork, drawn after the game's symbols - no glyph files from the game or from a fan "
    "site are shipped or downloaded.",
    (
        Credit("monkeyman192 and the MBINCompiler contributors",
               "mapping.json (the save file's key names) and the game's data layouts; downloaded at "
               "runtime, not bundled",
               "LGPL-3.0", "https://github.com/monkeyman192/MBINCompiler"),
        Credit("monkeyman192 (HGPAKtool)",
               "the documentation of the game's archive format, which is how item names and icons are "
               "read from your own installation",
               "MIT", "https://github.com/monkeyman192/HGPAKtool"),
        Credit("Stuart Coyle, had.sh and GoodGuysFree (nms_namegen)",
               "the game's system generation rules - planet seeds, star colour, economy predictions - "
               "ported in procgen.py",
               "MIT", "https://github.com/hadsh/nms_namegen"),
        Credit("Hello Games",
               "No Man's Sky itself. Item names, descriptions, values and icons are read from your own "
               "installation and never redistributed; nothing in the game or its folders is changed",
               "All rights reserved", "https://www.nomanssky.com/"),
        Credit("The No Man's Sky community",
               "the black hole, Atlas and purple-star system indices, and which gas each biome gives",
               "Freely shared"),
        Credit("40k Assistant / Strategicum",
               "the host this plugin was written for: its plugin system, personas, Codex and overlay",
               "MIT", APP_REPO_URL),
    ),
)

BUNDLED = Group(
    "Shipped inside the standalone installer",
    "The standalone install carries its own Python so that nothing has to be set up first. Each of these "
    "keeps its own licence text in the install folder, under vendor\\python.",
    (
        Credit("Python (the embeddable distribution)", "the interpreter the standalone host runs on",
               "PSF License 2.0", "https://www.python.org/"),
        Credit("NumPy", "the array maths behind the memory scans and the galaxy map",
               "BSD-3-Clause", "https://numpy.org/"),
        Credit("python-zstandard and Facebook's Zstandard",
               "decompressing the save file", "BSD-3-Clause", "https://github.com/indygreg/python-zstandard"),
        Credit("Pillow", "drawing the tray icon", "MIT-CMU", "https://python-pillow.github.io/"),
        Credit("pystray", "the tray icon itself. Dynamically linked and unmodified; its own LGPL licence "
                          "text ships beside it, and it may be replaced by another build",
               "LGPL-3.0", "https://github.com/moses-palmer/pystray"),
        Credit("six", "pystray's Python 2/3 compatibility layer", "MIT", "https://github.com/benjaminp/six"),
        Credit("Inno Setup (Jordan Russell, Martijn Laan)", "the installer itself",
               "Inno Setup License", "https://jrsoftware.org/isinfo.php"),
    ),
)

FONTS = Group(
    "Fonts",
    "Loaded from Google Fonts when the page is online; offline the page falls back to the system fonts "
    "and only the lettering differs.",
    (
        Credit("Cinzel (Natanael Gama)", "the page title", "SIL Open Font License 1.1",
               "https://fonts.google.com/specimen/Cinzel"),
        Credit("Chakra Petch (Cadson Demak)", "section heads, tabs and buttons", "SIL Open Font License 1.1",
               "https://fonts.google.com/specimen/Chakra+Petch"),
        Credit("Inter (Rasmus Andersson)", "the body text", "SIL Open Font License 1.1",
               "https://fonts.google.com/specimen/Inter"),
        Credit("Roboto Mono (Christian Robertson)", "the copyable text blocks", "Apache License 2.0",
               "https://fonts.google.com/specimen/Roboto+Mono"),
    ),
)

OPTIONAL = Group(
    "Downloaded only if you ask for it",
    "The installer's two optional parts and what the chat uses. Nothing here is packaged; each is "
    "fetched from its own project and keeps its own licence.",
    (
        Credit("Ollama", "runs the language model that answers your questions", "MIT",
               "https://ollama.com/"),
        Credit("Google (Gemma)", "gemma4:12b, the base of the 40k-12b-companion model",
               "Gemma Terms of Use", "https://ai.google.dev/gemma/terms"),
        Credit("Nomic AI", "nomic-embed-text, which makes the Codex searchable", "Apache License 2.0",
               "https://github.com/nomic-ai/nomic"),
        Credit("Piper (Michael Hansen / rhasspy)", "the spoken replies", "MIT",
               "https://github.com/rhasspy/piper"),
        Credit("piper-voices (rhasspy)", "the en_GB-cori-high voice, trained on LibriVox recordings",
               "Public domain (LibriVox)", "https://huggingface.co/rhasspy/piper-voices"),
    ),
)

GROUPS: tuple[Group, ...] = (BUILT_ON, BUNDLED, FONTS, OPTIONAL)


def manifest_credits() -> list[dict]:
    """The manifest's ``credits`` array: the author first, then every credited work.

    The app's manual shows these, so the licence travels in the ``for`` text - the manifest schema has
    no field of its own for it."""
    out = [{"name": AUTHOR, "for": "the plugin", "url": REPO_URL}]
    for group in GROUPS:
        for credit in group.entries:
            entry = {"name": credit.name, "for": f"{credit.what} ({credit.license})"}
            if credit.url:
                entry["url"] = credit.url
            out.append(entry)
    return out


def notices_markdown() -> str:
    """``THIRD-PARTY-NOTICES.md``: the same list as a file, for the repository and the install folder."""
    lines = [
        "# Third-party notices",
        "",
        "No Man's Sky Companion / the `nomanssky` plugin for the 40k Assistant.",
        f"Copyright (c) 2026 {AUTHOR}. Released under the {LICENSE} licence (see `LICENSE`).",
        f"<{REPO_URL}>",
        "",
        "This file is generated from `nms_connector/credits.py` by `tools/write_notices.py`; edit the",
        "module, not this file. It lists everything whose licence asks to be named and everything the",
        "standalone installer carries.",
    ]
    for group in GROUPS:
        lines += ["", f"## {group.title}", "", group.note, ""]
        for credit in group.entries:
            link = f" <{credit.url}>" if credit.url else ""
            lines.append(f"- **{credit.name}** - {credit.what}. _{credit.license}_.{link}")
    lines += ["", "## Nothing of the game's is redistributed", "",
              "Item names, descriptions, values, recipes and icons are read from your own No Man's Sky",
              "installation at runtime and stay in your own data folder. `mapping.json` is downloaded",
              "from MBINCompiler when it is needed, which is why no LGPL-licensed data file is packaged.",
              ""]
    return "\n".join(lines)


def _about_facts(version: str, host: str) -> dict:
    """The key/value section at the top of the About tab."""
    items = [
        {"label": "Made by", "value": AUTHOR},
        {"label": "Version", "value": version},
        {"label": "Running as", "value": "the standalone companion" if host == "standalone"
                                         else "a plugin in the 40k Assistant"},
        {"label": "Licence", "value": f"{LICENSE} - the full text is in LICENSE, beside this program"},
        {"label": "Source and issues", "value": REPO_URL},
        {"label": "The author", "value": AUTHOR_URL},
    ]
    return {"type": "kv", "id": "about-facts", "title": "No Man's Sky Companion", "items": items}


def _group_table(index: int, group: Group) -> dict:
    """One credits group as a table. Four columns, so a phone shows it as cards (the host's own rule).

    The group's own heading and sentence sit in the `text` section above it (a table section carries no
    description of its own), so this one stays untitled."""
    return {
        "type": "table",
        "id": f"about-credits-{index}",
        "columns": ["Name", "For", "Licence", "Link"],
        "rows": [[credit.name, credit.what, credit.license, credit.url or "–"]
                 for credit in group.entries],
        "empty": "Nothing to credit here.",
    }


def sections(version: str, host: str = "plugin") -> list[dict]:
    """The About tab's sections, built only from section types both hosts draw (kv, table, text)."""
    out: list[dict] = [_about_facts(version, host)]
    for index, group in enumerate(GROUPS):
        out.append({"type": "text", "id": f"about-note-{index}", "title": group.title, "text": group.note})
        out.append(_group_table(index, group))
    out.append({"type": "text", "id": "about-thanks", "title": "Thanks",
                "text": "Thanks to everybody who recorded what the game does, and to Hello Games for a "
                        "game worth writing a companion for. If something here is credited wrongly or "
                        "missing, open an issue at " + REPO_URL + " and it will be fixed."})
    return out
