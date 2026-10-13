"""Piper speech: command building, failure reporting and the route's gate."""
import asyncio

import pytest

from standalone import tts


def voice(tmp_path, exe="piper.exe", model="en_GB-cori-high.onnx"):
    return tts.PiperVoice(tmp_path / exe, tmp_path / model)


def test_command_names_the_model_and_the_output(tmp_path):
    """Piper is spawned, not imported; a wrong argument order produces an empty WAV that the page plays
    as silence, so the command is asserted here."""
    command = voice(tmp_path).command(tmp_path / "out.wav")
    assert command[0] == str(tmp_path / "piper.exe")
    assert str(tmp_path / "en_GB-cori-high.onnx") in command
    assert str(tmp_path / "out.wav") in command


def test_text_is_sent_as_utf8(tmp_path):
    """`text=True` would use the locale encoding (cp1252 on this machine) and Piper does not expect it -
    the app hit exactly this with German replies."""
    assert voice(tmp_path).encode("Nährstoffprozessor") == "Nährstoffprozessor".encode("utf-8")


def test_is_installed_is_false_without_the_files(tmp_path):
    """The status route reports whether the voice exists; the page hides the speaker button when it does
    not, instead of offering one that always fails."""
    assert voice(tmp_path, exe="nope.exe", model="nope.onnx").is_installed() is False


def test_is_installed_needs_both_parts(tmp_path):
    """A half-finished download (the exe without the voice) must count as not installed."""
    (tmp_path / "piper.exe").write_bytes(b"x")
    assert voice(tmp_path).is_installed() is False
    (tmp_path / "en_GB-cori-high.onnx").write_bytes(b"x")
    assert voice(tmp_path).is_installed() is True


def test_speaking_without_piper_raises_a_typed_failure(tmp_path):
    """A silent failure would leave the chat waiting forever; the page needs a message it can show."""
    with pytest.raises(tts.TtsError):
        asyncio.run(voice(tmp_path).speak("hello"))


def test_the_temp_wav_is_removed_on_the_failure_path(tmp_path):
    """Temp files are released in `finally`; the app's orphaned `raw_*.wav` artefacts came from cleanup
    that only ran on success."""
    with pytest.raises(tts.TtsError):
        asyncio.run(voice(tmp_path).speak("x"))
    assert list(tmp_path.glob("*.wav")) == []


def test_an_empty_text_is_refused_before_spawning(tmp_path):
    """Spawning Piper for nothing costs a process and returns an empty file the page plays as silence."""
    with pytest.raises(tts.TtsError):
        asyncio.run(voice(tmp_path).speak("   "))


def test_a_long_text_is_cut(tmp_path):
    """A whole inventory listing read aloud would run for minutes; the app's TTS bounds it too."""
    assert len(tts.spoken_text("x" * 10000)) == tts.MAX_TEXT_CHARS


def test_the_route_is_503_without_a_voice(tmp_path):
    """Without the voice installed the page hides the button, but a stale tab must get a clear refusal."""
    from standalone_fixtures import build_deps, call
    deps = build_deps(tmp_path)
    assert call(deps, "POST", "/api/tts", {"text": "hi"}).status == 503


def test_the_route_refuses_an_empty_text(tmp_path):
    """Same reason as the engine: nothing to say, nothing to spawn."""
    from standalone_fixtures import build_deps, call

    class FakeVoice:
        def is_installed(self):
            return True

        async def speak(self, text):
            return b"RIFF"

    deps = build_deps(tmp_path, tts=FakeVoice())
    assert call(deps, "POST", "/api/tts", {"text": ""}).status == 422


def test_the_route_answers_wav_bytes(tmp_path):
    """The page plays the answer as a blob, so the content type has to be right."""
    from standalone_fixtures import build_deps, call

    class FakeVoice:
        def is_installed(self):
            return True

        async def speak(self, text):
            return b"RIFF....WAVE"

    deps = build_deps(tmp_path, tts=FakeVoice())
    response = call(deps, "POST", "/api/tts", {"text": "hello"})
    assert response.status == 200 and response.content_type == "audio/wav"
    assert response.body.startswith(b"RIFF")


def test_a_failing_voice_becomes_a_visible_error(tmp_path):
    """Piper's own message (a missing voice file, a bad model) is what tells the user what to fix."""
    from standalone_fixtures import build_deps, call

    class BrokenVoice:
        def is_installed(self):
            return True

        async def speak(self, text):
            raise tts.TtsError("piper: unable to load voice")

    deps = build_deps(tmp_path, tts=BrokenVoice())
    response = call(deps, "POST", "/api/tts", {"text": "hello"})
    assert response.status == 502 and b"unable to load voice" in response.body
