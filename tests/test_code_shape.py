"""The code shape the plugin keeps: no function that does too much, takes too many arguments or hides a zip length
mismatch (ruff.toml). The test runs ruff when it is installed (the 40k Assistant's venv has it) and fails with the
findings, so a smell comes back as a red test and not as a slow decay."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _ruff() -> list[str] | None:
    """How to run ruff here: the module of this interpreter, else a ruff on the PATH, else None."""
    probe = subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True, text=True)
    if probe.returncode == 0:
        return [sys.executable, "-m", "ruff"]
    found = shutil.which("ruff")
    return [found] if found else None


def test_the_plugin_keeps_its_code_shape():
    """ruff (ruff.toml: complexity <= 8, <= 8 branches, <= 40 statements, <= 6 arguments, explicit zip strictness,
    no unused names or arguments, lines <= 140) reports nothing for nms_connector, standalone, tools and tests. Keeps
    the refactors of 2026-10-08 and 2026-10-18 from rotting - and the standalone host is held to the same shape as
    the connector, since both are this codebase."""
    ruff = _ruff()
    if ruff is None:
        pytest.skip("ruff is not installed")
    res = subprocess.run([*ruff, "check", "nms_connector", "standalone", "tools", "tests", "--output-format", "concise"],
                         cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, "code shape findings:\n" + res.stdout
