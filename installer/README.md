# The standalone installer

Builds `nms-companion-<version>-setup.exe`: the No Man's Sky connector plus its own small host
(`standalone/`), so it runs without the 40k Assistant.

## Building

```powershell
.\installer\build.ps1
```

The script downloads the embeddable Python 3.11, installs the five wheels the host imports
(`numpy`, `zstandard`, `pillow`, `pystray`, `six`) into it, smoke-tests that the packaged interpreter
can import them, refuses to continue if anything that must not be shipped is in the tree (see
*Licences*), and compiles the installer with Inno Setup (`ISCC.exe`, 6.3 or newer).

`vendor/` and `installer/Output/` are git-ignored: they are machine artefacts, and the in-app updater
downloads the repository as a tarball rather than an installer.

## What the installer does

* Installs per user into `%LOCALAPPDATA%\Programs\NMS Companion` — deliberately not Program Files, so
  the in-app updater can replace the code without asking for elevation.
* Asks on its own wizard page whether to set up the two **optional** parts; `postinstall.ps1` fetches
  whatever was ticked and writes `%LOCALAPPDATA%\NMS Companion\standalone.json`:
  * **AI assistant** — installs Ollama if it is missing, pulls `gemma4:12b`, builds
    `40k-12b-companion` from the shipped Modelfile, and pulls `nomic-embed-text` for the Codex search.
    Several GB. Without it everything else still works: inventories, maps, timers, discoveries,
    companions, the overlay, the tray and a full-text Codex search — only the chat needs it.
  * **Spoken replies** — downloads Piper and the `en_GB-cori-high` voice (about 70 MB).
* Offers a desktop shortcut and *Start with Windows*, which starts the host with `--no-browser`: the
  tray icon is the face of a windowless start.
* On uninstall, asks before deleting `%LOCALAPPDATA%\NMS Companion` — it holds the settings, months of
  planet history and the generated Codex documents.

Everything the installer fetches is logged to `%LOCALAPPDATA%\NMS Companion\install.log`, and a part
that cannot be set up is left switched off rather than half-installed.

## Licences, credits and what is never shipped

Everything this plugin builds on, bundles or downloads is listed in
[`THIRD-PARTY-NOTICES.md`](../THIRD-PARTY-NOTICES.md), which is **generated** from
`nms_connector/credits.py` (`python tools/write_notices.py`). That one module also feeds the manifest's
`credits`, which the 40k Assistant shows in its manual, and the page's own **About** tab. `build.ps1`
runs `tools/write_notices.py --check` and refuses to compile while any of them is out of date.

The installer shows the notices on its info page and installs the file beside the program, with a Start
menu entry of its own.

In short:

* This plugin and its standalone host: **MIT**, copyright Reto Kummer alias Reat Kay, Shorthand Dev /
  TronTronic Entertainment (see `LICENSE`).
* **Packaged** in `vendor\`: the embeddable **Python 3.11** (PSF-2.0) and the five wheels the host
  imports — **numpy** (BSD-3-Clause), **python-zstandard** (BSD-3-Clause), **Pillow** (MIT-CMU),
  **six** (MIT) and **pystray** (**LGPL-3.0**). pystray is shipped unmodified and imported dynamically;
  its own licence text travels with it in its `.dist-info` folder, so it may be replaced by another
  build of the same library. The installer itself is built with **Inno Setup** (Jordan Russell, Martijn
  Laan).
* **Fonts** are loaded from Google Fonts at runtime: Cinzel, Chakra Petch and Inter (SIL OFL 1.1) and
  Roboto Mono (Apache-2.0).
* **Ollama** (MIT) and the **gemma4** model are installed from their own sources on the user's machine;
  the model's own terms apply and nothing of it is redistributed here.
* **Piper** (MIT) and the **en_GB-cori-high** voice (LibriVox, public domain) are downloaded from their
  release pages.
* **MBINCompiler**'s `mapping.json` is LGPL-3.0 and is **downloaded at runtime**, never packaged.
* Nothing of **Hello Games**' is included: item names, descriptions and icons are read from the user's
  own installation of No Man's Sky, and the game's files are only ever read.

`build.ps1` enforces the last two points: it refuses to compile if `mapping.json`, a `gamedata` folder
or a `.data` folder is anywhere in the tree.
