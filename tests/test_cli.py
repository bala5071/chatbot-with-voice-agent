"""The CLI end to end on the fakes: nothing is written unless asked, and the timings printed
are the exact fake ones."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from voice_agent.audio import Audio, read_wav
from voice_agent.cli import Builder, Components, main
from voice_agent.clock import Clock, FakeClock
from voice_agent.config import Settings
from voice_agent.fakes import Delta, FakeChatClient, FakeSpeechToText, FakeTextToSpeech, tone


def fake_builder(clock: FakeClock) -> Builder:
    def build(args: argparse.Namespace, settings: Settings, _clock: Clock) -> Components:
        return Components(
            stt=FakeSpeechToText(clock, "When are you open on Saturday?", duration_ms=250),
            tts=FakeTextToSpeech(clock, first_chunk_ms=60),
            chat=FakeChatClient(clock, [Delta(150, "We open at 9 a.m. on Saturday.")]),
        )

    return build


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty working directory, with every temp-dir variable pointing inside it."""
    work = tmp_path / "work"
    temp = tmp_path / "temp"
    work.mkdir()
    temp.mkdir()
    monkeypatch.chdir(work)
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(temp))
    (work / "in.wav").write_bytes(Audio(tone(400, 16_000), 16_000).to_wav_bytes())
    return tmp_path


def files_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def run(argv: list[str], clock: FakeClock) -> tuple[int, str]:
    out = io.StringIO()
    code = main(argv, env={}, clock=clock, build=fake_builder(clock), out=out)
    return code, out.getvalue()


def test_no_audio_or_text_is_written_without_out(workdir: Path) -> None:
    before = files_under(workdir)
    code, _ = run(["--in", "in.wav", "--timings"], FakeClock())
    assert code == 0
    assert files_under(workdir) == before == {"work/in.wav"}


def test_out_is_the_only_file_written(workdir: Path) -> None:
    code, _ = run(["--in", "in.wav", "--out", "reply.wav"], FakeClock())
    assert code == 0
    assert files_under(workdir) == {"work/in.wav", "work/reply.wav"}
    reply = read_wav(workdir / "work" / "reply.wav")
    assert reply.sample_rate == 16_000
    assert reply.duration_ms > 0


def test_timings_are_printed_exactly_and_text_only_when_asked(workdir: Path) -> None:
    code, out = run(["--in", "in.wav", "--timings"], FakeClock())
    assert code == 0
    report = json.loads(out)
    assert report["outcome"] == "answered"
    assert report["stages_ms"] == {
        "speech_end": 0.0,
        "transcript_ready": 250.0,
        "request_sent": 250.0,
        "first_token": 400.0,
        "first_sentence": 400.0,
        "first_audio_byte": 460.0,
    }
    assert "Saturday" not in out  # neither transcript nor reply without --show-text

    _, shown = run(["--in", "in.wav", "--show-text"], FakeClock())
    assert "caller: When are you open on Saturday?" in shown


def test_missing_key_is_a_clear_error_for_the_real_builder(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--in", "in.wav"], env={}, clock=FakeClock())
    assert code == 2
    assert "GATEWAY_API_KEY is not set" in capsys.readouterr().err


def test_a_stereo_file_is_refused(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import wave

    with wave.open(str(workdir / "work" / "stereo.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\0\0\0\0" * 100)
    code, _ = run(["--in", "stereo.wav"], FakeClock())
    assert code == 2
    assert "mono 16-bit" in capsys.readouterr().err
