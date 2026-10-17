# Third-party notices

No Man's Sky Companion / the `nomanssky` plugin for the 40k Assistant.
Copyright (c) 2026 Reto Kummer alias Reat Kay, Shorthand Dev / TronTronic Entertainment. Released under the MIT licence (see `LICENSE`).
<https://github.com/trontronicent/40k-assistant-nomanssky>

This file is generated from `nms_connector/credits.py` by `tools/write_notices.py`; edit the
module, not this file. It lists everything whose licence asks to be named and everything the
standalone installer carries.

## The work this plugin builds on

Read or ported, never redistributed: the game's own data stays in your installation, and the save key mapping is downloaded from MBINCompiler when it is needed.

- **monkeyman192 and the MBINCompiler contributors** - mapping.json (the save file's key names) and the game's data layouts; downloaded at runtime, not bundled. _LGPL-3.0_. <https://github.com/monkeyman192/MBINCompiler>
- **monkeyman192 (HGPAKtool)** - the documentation of the game's archive format, which is how item names and icons are read from your own installation. _MIT_. <https://github.com/monkeyman192/HGPAKtool>
- **Stuart Coyle, had.sh and GoodGuysFree (nms_namegen)** - the game's system generation rules - planet seeds, star colour, economy predictions - ported in procgen.py. _MIT_. <https://github.com/hadsh/nms_namegen>
- **Hello Games** - No Man's Sky itself. Item names, descriptions, values and icons are read from your own installation and never redistributed; nothing in the game or its folders is changed. _All rights reserved_. <https://www.nomanssky.com/>
- **The No Man's Sky community** - the black hole, Atlas and purple-star system indices, and which gas each biome gives. _Freely shared_.
- **40k Assistant / Strategicum** - the host this plugin was written for: its plugin system, personas, Codex and overlay. _MIT_. <https://github.com/trontronicent/40k-assistant>

## Shipped inside the standalone installer

The standalone install carries its own Python so that nothing has to be set up first. Each of these keeps its own licence text in the install folder, under vendor\python.

- **Python (the embeddable distribution)** - the interpreter the standalone host runs on. _PSF License 2.0_. <https://www.python.org/>
- **NumPy** - the array maths behind the memory scans and the galaxy map. _BSD-3-Clause_. <https://numpy.org/>
- **python-zstandard and Facebook's Zstandard** - decompressing the save file. _BSD-3-Clause_. <https://github.com/indygreg/python-zstandard>
- **Pillow** - drawing the tray icon. _MIT-CMU_. <https://python-pillow.github.io/>
- **pystray** - the tray icon itself. Dynamically linked and unmodified; its own LGPL licence text ships beside it, and it may be replaced by another build. _LGPL-3.0_. <https://github.com/moses-palmer/pystray>
- **six** - pystray's Python 2/3 compatibility layer. _MIT_. <https://github.com/benjaminp/six>
- **Inno Setup (Jordan Russell, Martijn Laan)** - the installer itself. _Inno Setup License_. <https://jrsoftware.org/isinfo.php>

## Fonts

Loaded from Google Fonts when the page is online; offline the page falls back to the system fonts and only the lettering differs.

- **Cinzel (Natanael Gama)** - the page title. _SIL Open Font License 1.1_. <https://fonts.google.com/specimen/Cinzel>
- **Chakra Petch (Cadson Demak)** - section heads, tabs and buttons. _SIL Open Font License 1.1_. <https://fonts.google.com/specimen/Chakra+Petch>
- **Inter (Rasmus Andersson)** - the body text. _SIL Open Font License 1.1_. <https://fonts.google.com/specimen/Inter>
- **Roboto Mono (Christian Robertson)** - the copyable text blocks. _Apache License 2.0_. <https://fonts.google.com/specimen/Roboto+Mono>

## Downloaded only if you ask for it

The installer's two optional parts and what the chat uses. Nothing here is packaged; each is fetched from its own project and keeps its own licence.

- **Ollama** - runs the language model that answers your questions. _MIT_. <https://ollama.com/>
- **Google (Gemma)** - gemma4:12b, the base of the 40k-12b-companion model. _Gemma Terms of Use_. <https://ai.google.dev/gemma/terms>
- **Nomic AI** - nomic-embed-text, which makes the Codex searchable. _Apache License 2.0_. <https://github.com/nomic-ai/nomic>
- **Piper (Michael Hansen / rhasspy)** - the spoken replies. _MIT_. <https://github.com/rhasspy/piper>
- **piper-voices (rhasspy)** - the en_GB-cori-high voice, trained on LibriVox recordings. _Public domain (LibriVox)_. <https://huggingface.co/rhasspy/piper-voices>

## Nothing of the game's is redistributed

Item names, descriptions, values, recipes and icons are read from your own No Man's Sky
installation at runtime and stay in your own data folder. `mapping.json` is downloaded
from MBINCompiler when it is needed, which is why no LGPL-licensed data file is packaged.
