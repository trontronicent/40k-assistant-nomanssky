"""Export and import of the plugin's own data - the way to move it between the two hosts.

What the plugin accumulates cannot be read back out of the game: 1,778 recorded planets, 7,066
generated system names, 429 economies, the star fixes and the guild records are the result of
playing with it running. The app's data dir (``plugins/.data/nomanssky``) and the standalone
host's are two separate places, so this writes one zip and reads it back into the other.

**Transport is a file path**, not an upload: a plugin view has no file field and the app serves a
plugin's assets as PNG only, so a download would need a new host contract for a feature used
twice a year. The user says where to write the zip, and where to read it from.

Two modes:

* ``replace`` - every file the archive holds overwrites the local one.
* ``merge`` - the records are merged (``merge_history``, ``merge_events``); the caches are taken
  only when the archive was built from a newer game build; settings, the planned route and the
  settlement screen are left alone, because merging a codeword or a route means nothing.

The archive is untrusted input (it may come from anywhere): ``member_problem`` is the whitelist,
and nothing on disk is touched before every member passed it and every JSON member parsed.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

#: Archive layout version. Raised when a reader could no longer make sense of an older archive.
FORMAT = 1
MANIFEST = "manifest.json"

#: What the import form offers. INSPECT writes nothing at all.
INSPECT, MERGE, REPLACE = "inspect", "merge", "replace"
MODES = (INSPECT, MERGE, REPLACE)

#: The connector's own files. The host's (``.stc-data.json``, ``.codex-written.json``,
#: ``codex_stamp.json``) describe what *that* host wrote and would lie in the other one; ``.bak``
#: and ``.tmp`` are the history's own crash protection, which the importing host builds itself.
RECORD_FILES = ("planet_history.json", "save_events.json")
SETTING_FILES = ("settings.json", "route.json", "settlement_screen.json")
MAPPING_FILES = ("mapping.json", "mapping_meta.json")
#: Rebuildable from the game files, but a machine without the game cannot rebuild them.
CACHE_DIRS = ("gamedata", "assets")

MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 20_000
MAX_SCANS = 50            # history.PlanetHistory.MAX_SCANS
MAX_EVENTS = 300          # watcher.SaveWatcher max_events


def member_problem(name: str, size: int) -> str | None:
    """Why this archive member may not be unpacked, or None when it may be.

    The whitelist is by name: a plain file at the top level that this module exports, or a file
    inside one of the cache directories. Everything else - an absolute path, a parent step, a
    device name, a directory entry, a link - is refused rather than interpreted."""
    if size > MAX_MEMBER_BYTES:
        return f"{name} is larger than {MAX_MEMBER_BYTES // (1024 * 1024)} MB"
    if name.endswith("/"):
        return f"{name} is a directory entry"
    if name.startswith("/") or name.startswith("\\") or ":" in name or "\\" in name:
        return f"{name} is not a plain relative path"
    parts = name.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return f"{name} is not a plain relative path"
    if len(parts) == 1:
        return None if name in (MANIFEST, *RECORD_FILES, *SETTING_FILES, *MAPPING_FILES) \
            else f"{name} is not one of the plugin's files"
    if len(parts) == 2 and parts[0] in CACHE_DIRS:
        return None
    return f"{name} is not one of the plugin's files"


def exported_names(data_dir: Path) -> list[str]:
    """The archive members to write for this data dir, in a stable order (the manifest is added by
    `manifest_for`). A file that does not exist yet is simply not in the archive."""
    data_dir = Path(data_dir)
    names = [n for n in (*RECORD_FILES, *SETTING_FILES, *MAPPING_FILES) if (data_dir / n).is_file()]
    for folder in CACHE_DIRS:
        base = data_dir / folder
        if base.is_dir():
            names += sorted(f"{folder}/{p.name}" for p in base.iterdir() if p.is_file())
    return names


def manifest_for(names: list[str], sizes: dict[str, int], *, host: str, plugin_version: str,
                 game_build: str | None, created_at: str) -> dict:
    """What the archive says about itself: who wrote it, from which game build, and what is in it."""
    return {"format": FORMAT, "host": host, "plugin_version": plugin_version, "game_build": game_build,
            "created_at": created_at, "files": {n: sizes.get(n, 0) for n in names}}


def counts_of(history: dict | None) -> dict:
    """How much a planet history holds, for the page's before-and-after table."""
    history = history or {}
    return {"planets": len(history.get("planets") or {}), "economies": len(history.get("economies") or {}),
            "system names": len(history.get("system_names") or {}),
            "star fixes": len(history.get("star_fixes") or []), "guild regions": len(history.get("guilds") or {})}


def manifest_problem(manifest: object) -> str | None:
    """Why this manifest cannot be read, or None. A missing one means the zip is not one of ours."""
    if not isinstance(manifest, dict):
        return f"{MANIFEST} is not an object - this zip was not written by the plugin"
    if manifest.get("format") != FORMAT:
        return f"archive format {manifest.get('format')!r}, this plugin reads {FORMAT}"
    if not isinstance(manifest.get("files"), dict):
        return f"{MANIFEST} does not list its files"
    return None


def take_caches(archive_build: str | None, local_build: str | None, local_has_cache: bool) -> bool:
    """Whether a merge takes the archive's item/table caches: only when they can be newer than what
    is here, or when nothing is here to keep. Game builds are numeric strings that grow."""
    if not local_has_cache:
        return True
    if not archive_build:
        return False
    if not local_build:
        return True
    try:
        return int(archive_build) > int(local_build)
    except (TypeError, ValueError):
        return archive_build > local_build


def plan(manifest: dict, mode: str, *, local_build: str | None, local_has_cache: bool) -> dict:
    """What an import would do to each group of files, as plain words for the page.

    Pure: the page shows this before anything is written, and the import follows exactly it."""
    names = list((manifest.get("files") or {}))
    caches = [n for n in names if n.split("/")[0] in CACHE_DIRS]
    out = {}
    for name in (*RECORD_FILES, *SETTING_FILES, *MAPPING_FILES):
        if name not in names:
            continue
        if mode == "replace":
            out[name] = "replaced"
        elif name in RECORD_FILES:
            out[name] = "merged"
        else:
            out[name] = "kept (replace mode replaces it)"
    if caches:
        taken = mode == "replace" or take_caches(manifest.get("game_build"), local_build, local_has_cache)
        out["gamedata/ + assets/"] = (f"{len(caches)} files replaced" if taken else
                                      f"{len(caches)} files skipped (the local copy is as new or newer)")
    return out


def _newer(a: dict, b: dict, field: str) -> dict:
    """Whichever record was seen last; `a` wins a tie, so a local record is never replaced by an equal one."""
    return a if (a.get(field) or "") >= (b.get(field) or "") else b


def merge_planet(local: dict, incoming: dict) -> dict:
    """One planet record from both hosts: the newer reading, but the whole history of the planet.

    `first_seen` is the earliest of the two (it is when *you* first saw it, on either machine),
    `previous_names` is the union in order, and a planet confirmed on either host stays confirmed -
    confirmation says the planet was read while you were in its system, which cannot un-happen."""
    merged = dict(_newer(local, incoming, "last_seen"))
    first = [s for s in (local.get("first_seen"), incoming.get("first_seen")) if s]
    if first:
        merged["first_seen"] = min(first)
    names = list(dict.fromkeys((local.get("previous_names") or []) + (incoming.get("previous_names") or [])))
    if names:
        merged["previous_names"] = names
    if local.get("confirmed") or incoming.get("confirmed"):
        merged["confirmed"] = True
    return merged


def merge_history(local: dict, incoming: dict) -> dict:
    """Merge two planet_history.json contents (the raw file shape), local winning every tie.

    Pure, and never loses a record: planets are merged per id, economies take the better source
    (a reading beats a prediction, then the newer), and names, fixes and guild records fill gaps
    only - the local host is where the user is playing, so its answer is the one on the screen."""
    out = dict(local)
    out["planets"] = _merge_planets(local.get("planets") or {}, incoming.get("planets") or {})
    out["economies"] = _merge_economies(local.get("economies") or {}, incoming.get("economies") or {})
    for field in ("system_names", "guilds"):
        out[field] = {**(incoming.get(field) or {}), **(local.get(field) or {})}
    out["scans"] = sorted((local.get("scans") or []) + (incoming.get("scans") or []),
                          key=lambda s: s.get("at") or "")[-MAX_SCANS:]
    out["star_fixes"] = _merge_fixes(local.get("star_fixes") or [], incoming.get("star_fixes") or [])
    return out


def _merge_planets(local: dict, incoming: dict) -> dict:
    out = dict(local)
    for key, planet in incoming.items():
        if not isinstance(planet, dict):
            continue
        known = out.get(key)
        out[key] = merge_planet(known, planet) if isinstance(known, dict) else planet
    return out


def _merge_economies(local: dict, incoming: dict) -> dict:
    """A system's star attributes. Read beats read-later; both are readings, so the newer one wins."""
    out = dict(local)
    for key, entry in incoming.items():
        if not isinstance(entry, dict):
            continue
        known = out.get(key)
        out[key] = _newer(known, entry, "read_at") if isinstance(known, dict) else entry
    return out


def _fix_place(fix: dict) -> tuple:
    """A star fix's identity for a merge: where it is. Its `id` is per host and says nothing."""
    return tuple(round(float(c), 4) for c in (fix.get("position") or []))


def _merge_fixes(local: list, incoming: list) -> list:
    """Star fixes (PROTOTYPE): the local ones keep their ids, an incoming one is appended with a fresh id.

    Skipped when the same star is already fixed here - the same position, or the same system, since the
    naming action keeps one fix per system. Ids are per host, so two hosts that both recorded the same
    fixes would otherwise double every one of them (seen on the real data: 6 fixes became 12)."""
    out = [f for f in local if isinstance(f, dict)]
    systems = {f.get("system") for f in out if f.get("system")}
    places = {_fix_place(f) for f in out}
    next_id = max((f.get("id") or 0 for f in out), default=0) + 1
    for fix in incoming:
        if not isinstance(fix, dict):
            continue
        if (fix.get("system") and fix["system"] in systems) or _fix_place(fix) in places:
            continue
        out.append({**fix, "id": next_id})
        systems.add(fix.get("system"))
        places.add(_fix_place(fix))
        next_id += 1
    return out


def merge_events(local: list, incoming: list) -> list:
    """Save writes from both hosts, oldest first, each write once (same file and mtime = same write)."""
    seen, out = set(), []
    for event in sorted([e for e in (local + incoming) if isinstance(e, dict)], key=lambda e: e.get("mtime") or 0):
        mark = (event.get("file"), event.get("mtime"))
        if mark in seen:
            continue
        seen.add(mark)
        out.append(event)
    return out[-MAX_EVENTS:]


def read_archive(path: Path) -> tuple[dict, dict]:
    """(manifest, {name: bytes}) of every member that may be unpacked. Raises ValueError otherwise.

    Nothing is written here: the caller gets the whole archive in hand, so a refusal leaves the data
    dir untouched. Blocking I/O - call it in a thread."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"{path} does not exist")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_MEMBERS:
                raise ValueError(f"the archive holds {len(infos)} files, more than {MAX_MEMBERS}")
            total = sum(i.file_size for i in infos)
            if total > MAX_TOTAL_BYTES:
                raise ValueError(f"the archive unpacks to {total // (1024 * 1024)} MB, "
                                 f"more than {MAX_TOTAL_BYTES // (1024 * 1024)} MB")
            for info in infos:
                problem = member_problem(info.filename, info.file_size)
                if problem:
                    raise ValueError(problem)
            files = {i.filename: archive.read(i.filename) for i in infos}
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{path.name} is not a readable zip file ({exc})") from exc
    if MANIFEST not in files:
        raise ValueError(f"the archive has no {MANIFEST} - it was not written by the plugin")
    manifest = _loads(files[MANIFEST], MANIFEST)
    problem = manifest_problem(manifest)
    if problem:
        raise ValueError(problem)
    for name in (*RECORD_FILES, *SETTING_FILES, "mapping_meta.json"):
        if name in files:
            _loads(files[name], name)       # parsed here so a damaged file is found before anything is written
    return manifest, files


def _loads(raw: bytes, name: str):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} in the archive is damaged ({exc})") from exc


class DataTransfer:
    """The file side of it: writes the archive, reads one back into the data dir.

    Every method blocks (zip and disk), so a host calls them in a thread. The decisions are the pure
    functions above; this class only moves bytes, and writes nothing before `read_archive` returned.
    """

    EXPORT_DIR = "exports"
    BACKUP_DIR = "backups"
    TEMP_DIR = ".transfer"

    def __init__(self, data_dir: Path, *, host: str, plugin_version: str, game_build: str | None = None):
        self.data_dir = Path(data_dir)
        self.host = host
        self.plugin_version = plugin_version
        self.game_build = game_build

    # --- export

    def default_folder(self) -> Path:
        return self.data_dir / self.EXPORT_DIR

    def export(self, folder: str | None, now: str) -> dict:
        """Write one zip of the connector's files; returns {path, files, bytes}."""
        target = Path(folder.strip()) if (folder or "").strip() else self.default_folder()
        target.mkdir(parents=True, exist_ok=True)
        path = self._free_name(target, f"nms-data-{now[:10]}")
        names = exported_names(self.data_dir)
        sizes = {n: (self.data_dir / n).stat().st_size for n in names}
        manifest = manifest_for(names, sizes, host=self.host, plugin_version=self.plugin_version,
                                game_build=self.game_build, created_at=now)
        self._write_zip(path, names, manifest)
        return {"path": str(path), "files": len(names), "bytes": path.stat().st_size}

    def _write_zip(self, path: Path, names: list[str], manifest: dict) -> None:
        tmp = path.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
            for name in names:
                archive.write(self.data_dir / name, name)
        tmp.replace(path)

    @staticmethod
    def _free_name(folder: Path, stem: str) -> Path:
        """`stem.zip`, or `stem-2.zip` and on - two exports on one day must not overwrite each other."""
        path = folder / f"{stem}.zip"
        count = 1
        while path.exists():
            count += 1
            path = folder / f"{stem}-{count}.zip"
        return path

    # --- import

    def local_build(self) -> str | None:
        """The game build the local item cache was read from, or None when there is no cache."""
        cached = self.data_dir / "gamedata" / "items.json"
        if not cached.is_file():
            return None
        raw = json.loads(cached.read_text(encoding="utf-8")) if cached.stat().st_size else {}
        build = raw.get("build_id") if isinstance(raw, dict) else None
        return str(build) if build is not None else None

    def inspect(self, path: str, mode: str) -> dict:
        """What the archive holds and what importing it in this mode would do. Writes nothing."""
        manifest, files = read_archive(Path(str(path).strip()))
        history = _loads(files["planet_history.json"], "planet_history.json") \
            if "planet_history.json" in files else None
        local = self.data_dir / "planet_history.json"
        mine = json.loads(local.read_text(encoding="utf-8")) if local.is_file() else None
        return {"manifest": manifest, "counts": counts_of(history), "mine": counts_of(mine),
                "plan": plan(manifest, mode, local_build=self.local_build(),
                             local_has_cache=(self.data_dir / "gamedata" / "items.json").is_file())}

    def apply(self, path: str, mode: str, now: str) -> dict:
        """Import the archive. Returns {backup, written, plan, counts}; raises ValueError before any write.

        The current data dir is backed up first, then each member is written through a temp file and
        `os.replace`d into place - a crash leaves either the old or the new file, never half of one.
        """
        manifest, files = read_archive(Path(str(path).strip()))
        decided = plan(manifest, mode, local_build=self.local_build(),
                       local_has_cache=(self.data_dir / "gamedata" / "items.json").is_file())
        backup = self.backup(now)
        written = []
        for name, what in decided.items():
            if "skipped" in what or what.startswith("kept"):
                continue
            written += self._write_group(name, files, mode)
        archive_history = _loads(files["planet_history.json"], "planet_history.json") \
            if "planet_history.json" in files else None
        history = self.data_dir / "planet_history.json"
        local = json.loads(history.read_text(encoding="utf-8")) if history.is_file() else None
        return {"backup": str(backup), "written": len(written), "plan": decided, "manifest": manifest,
                "counts": counts_of(archive_history), "mine": counts_of(local)}

    def _write_group(self, name: str, files: dict, mode: str) -> list[str]:
        """Write one line of the plan: a cache directory's files, a merged record file, or a plain copy."""
        if name == "gamedata/ + assets/":
            return [self._place(n, files[n]) for n in files if n.split("/")[0] in CACHE_DIRS]
        if name in RECORD_FILES and mode == "merge":
            return [self._place(name, self._merged(name, files[name]))]
        return [self._place(name, files[name])]

    def _merged(self, name: str, incoming: bytes) -> bytes:
        """The local file merged with the archive's, as bytes to write (local wins every tie)."""
        local_path = self.data_dir / name
        local = json.loads(local_path.read_text(encoding="utf-8")) if local_path.is_file() else None
        other = _loads(incoming, name)
        if name == "planet_history.json":
            merged = merge_history(local, other) if isinstance(local, dict) and isinstance(other, dict) else other
        else:
            merged = merge_events(local or [], other or []) if isinstance(other, list) else other
        return json.dumps(merged, ensure_ascii=False).encode("utf-8")

    def _place(self, name: str, raw: bytes) -> str:
        """Write one member atomically into the data dir (through a temp file next to its target)."""
        target = self.data_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_bytes(raw)
        tmp.replace(target)
        return name

    def backup(self, now: str) -> Path:
        """Zip the connector's current files aside before an import, so a bad archive costs nothing."""
        folder = self.data_dir / self.BACKUP_DIR
        folder.mkdir(parents=True, exist_ok=True)
        path = self._free_name(folder, f"backup-{now[:19].replace(':', '-')}")
        names = exported_names(self.data_dir)
        sizes = {n: (self.data_dir / n).stat().st_size for n in names}
        self._write_zip(path, names, manifest_for(names, sizes, host=self.host, plugin_version=self.plugin_version,
                                                  game_build=self.game_build, created_at=now))
        return path
