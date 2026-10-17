"""Write the credits from `nms_connector/credits.py` into the two files that have to repeat them.

    python tools/write_notices.py            # write THIRD-PARTY-NOTICES.md and the manifest's credits
    python tools/write_notices.py --check    # only say whether they are up to date (exit 1 if not)

`credits.py` is the one list. The notices file is what the installer ships and what a reader of the
repository finds; the manifest's `author` and `credits` are what the 40k Assistant shows in its manual
under *Plugin Help*. `tests/test_credits.py` runs the --check path, so a credit added to the module and
forgotten here fails the suite instead of shipping half-applied.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nms_connector import credits  # noqa: E402  (after the path set-up)

NOTICES = ROOT / "THIRD-PARTY-NOTICES.md"
MANIFEST = ROOT / "strategicum-plugin.json"


def manifest_with_credits() -> str:
    """The manifest as it should be: the author and credits replaced, everything else untouched.

    Returned as text rather than written, so --check can compare without touching the file. Key order is
    kept because `json.load` preserves it and the credits keys are replaced in place."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    data["author"] = {"name": credits.AUTHOR, "url": credits.AUTHOR_URL}
    data["credits"] = credits.manifest_credits()
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    wanted = {NOTICES: credits.notices_markdown(), MANIFEST: manifest_with_credits()}
    stale = [path for path, text in wanted.items()
             if not path.exists() or path.read_text(encoding="utf-8") != text]
    if check:
        for path in stale:
            print(f"out of date: {path.name} (run python tools/write_notices.py)")
        return 1 if stale else 0
    for path in stale:
        path.write_text(wanted[path], encoding="utf-8")
        print(f"wrote {path.name}")
    if not stale:
        print("both files were already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
