"""Spoken replies through Piper, if the installer set it up.

Piper is spawned, never imported: `asyncio.create_subprocess_exec` with a bounded wait, text on stdin as
**UTF-8** (`text=True` would use cp1252 on this machine and Piper does not expect it), a non-zero exit
or empty output raising with Piper's own stderr, and the temporary file removed in `finally`.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

log = logging.getLogger("nms-standalone.tts")

PIPER_TIMEOUT_S = 60.0
MAX_TEXT_CHARS = 2000


class TtsError(RuntimeError):
    """Piper could not speak; the message carries its own stderr where there is one."""


def spoken_text(text: str) -> str:
    """What is actually sent: trimmed and bounded (a whole inventory read aloud runs for minutes)."""
    return (text or "").strip()[:MAX_TEXT_CHARS]


class PiperVoice:
    """One installed Piper voice."""

    def __init__(self, exe: Path, model: Path):
        self.exe = Path(exe)
        self.model = Path(model)

    def is_installed(self) -> bool:
        """Both parts: a half-finished download must count as missing."""
        return self.exe.is_file() and self.model.is_file()

    def command(self, out_path: Path) -> list[str]:
        return [str(self.exe), "--model", str(self.model), "--output_file", str(out_path)]

    @staticmethod
    def encode(text: str) -> bytes:
        return text.encode("utf-8")

    async def speak(self, text: str) -> bytes:
        """The WAV bytes for `text`."""
        payload = spoken_text(text)
        if not payload:
            raise TtsError("there is nothing to speak")
        if not self.is_installed():
            raise TtsError("the voice is not installed")
        out_path = Path(tempfile.mkstemp(suffix=".wav", dir=str(self.model.parent))[1])
        try:
            return await self._run(payload, out_path)
        finally:
            out_path.unlink(missing_ok=True)

    async def _run(self, payload: str, out_path: Path) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command(out_path), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except OSError as err:
            raise TtsError(f"piper could not be started: {err}") from err
        try:
            _out, err = await asyncio.wait_for(process.communicate(self.encode(payload)),
                                               PIPER_TIMEOUT_S)
        except TimeoutError as timeout:
            process.kill()
            raise TtsError(f"piper did not answer within {PIPER_TIMEOUT_S:.0f} s") from timeout
        if process.returncode:
            raise TtsError(f"piper failed ({process.returncode}): "
                           f"{err.decode('utf-8', 'replace').strip()[:400]}")
        audio = out_path.read_bytes() if out_path.exists() else b""
        if not audio:
            raise TtsError("piper wrote no audio")
        return audio


def from_settings(data_dir: Path, voice: str) -> PiperVoice:
    """The voice the installer put in the data dir (`<data>/piper/piper.exe` + `<voice>.onnx`)."""
    from standalone import paths
    folder = paths.piper_dir(data_dir)
    return PiperVoice(folder / "piper.exe", folder / f"{voice}.onnx")
