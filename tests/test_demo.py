"""The demo script on the fakes and ``FakeClock``: each call's path and exact stage times, the
emergency call never reaching the model, the temporary folder deleted and nothing else, files
only with ``--out``, playback, and clear exits without a key or a reachable gateway."""

from __future__ import annotations

import argparse
import io
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from scripts.demo import CALLS, LABEL, near_silence
from scripts.demo import main as demo_main

from tests.helpers import PLANTED_KEY, find_leaks
from voice_agent.audio import Audio, read_wav
from voice_agent.cli import Builder, Components
from voice_agent.clock import Clock, FakeClock
from voice_agent.config import Settings
from voice_agent.errors import NotAuthorized, SpokenError, Unavailable
from voice_agent.fakes import Delta, FakeChatClient, FakeTextToSpeech
from voice_agent.pipeline import WARM_UP_TEXT
from voice_agent.safety import is_emergency

ENV = {"GATEWAY_API_KEY": PLANTED_KEY}
REPLY = "We open at 9 a.m. on Saturday."
HARDWARE = {"cpu": "test cpu", "gpu": None}


class ScriptedSpeechToText:
    """Returns ``transcripts`` in order, ``duration_ms`` each; records each audio's length."""

    def __init__(self, clock: FakeClock, transcripts: Sequence[str], duration_ms: float) -> None:
        self._clock = clock
        self._transcripts = list(transcripts)
        self.duration_ms = duration_ms
        self.heard_ms: list[float] = []

    async def transcribe(self, audio: Audio) -> str:
        self.heard_ms.append(audio.duration_ms)
        self._clock.advance(self.duration_ms)
        return self._transcripts.pop(0)


def transcripts(*, silence: str = "") -> list[str]:
    """What the fake hears: the warm-up text, then each call's sentence (``silence`` for the
    near-silent call)."""
    return [WARM_UP_TEXT, *(call.text if call.text is not None else silence for call in CALLS)]


@dataclass
class Run:
    clock: FakeClock = field(default_factory=FakeClock)
    heard: list[str] = field(default_factory=transcripts)
    fail: SpokenError | None = None
    played: list[tuple[Path, bool]] = field(default_factory=list)
    built: int = 0
    closed: int = 0
    stt: ScriptedSpeechToText | None = None
    chat: FakeChatClient | None = None

    def build(self) -> Builder:
        def build(args: argparse.Namespace, settings: Settings, _clock: Clock) -> Components:
            self.built += 1
            self.stt = ScriptedSpeechToText(self.clock, self.heard, duration_ms=250)
            self.chat = FakeChatClient(self.clock, [Delta(150, REPLY)], fail=self.fail)
            return Components(self.stt, FakeTextToSpeech(self.clock, 60), self.chat, self.close)

        return build

    async def close(self) -> None:
        self.closed += 1

    def play(self, path: Path) -> None:
        self.played.append((path, path.is_file()))

    def main(
        self, argv: list[str], temp: Path, env: dict[str, str] | None = None
    ) -> tuple[int, str]:
        out = io.StringIO()
        code = demo_main(
            argv,
            env=ENV if env is None else env,
            clock=self.clock,
            build=self.build(),
            out=out,
            player=self.play,
            hardware=lambda: dict(HARDWARE),
            temp_parent=temp,
        )
        return code, out.getvalue()


@pytest.fixture
def temp(tmp_path: Path) -> Path:
    """The temporary folder's parent, holding one file that is not the demo's."""
    parent = tmp_path / "temp"
    parent.mkdir()
    (parent / "not-the-demos.txt").write_text("keep me\n", encoding="utf-8")
    return parent


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def files_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def call_block(out: str, index: int) -> str:
    return out.split(f"Call {index}: ")[1].split("\n\n")[0]


# --- the calls ------------------------------------------------------------------------------


def test_each_call_takes_its_path(temp: Path, workdir: Path) -> None:
    code, out = Run().main([], temp)
    assert code == 0
    paths = [call_block(out, i).split("path:")[1].splitlines()[0].strip() for i in range(1, 6)]
    assert paths == ["model", "model", "scripted emergency", "model", "scripted no-speech"]
    assert "expected" not in out


def test_a_call_prints_its_transcript_reply_and_exact_stage_times(
    temp: Path, workdir: Path
) -> None:
    _, out = Run().main([], temp)
    first = call_block(out, 1).splitlines()
    assert first[:3] == [
        "opening hours",
        "  transcript: 'Hi, what time do you open on Saturday?'",
        f"  reply:      {REPLY!r}",
    ]
    assert [line.split() for line in first[5:]] == [
        ["speech_end", "0.0"],
        ["transcript_ready", "250.0"],
        ["request_sent", "250.0"],
        ["first_token", "400.0"],
        ["first_sentence", "400.0"],
        ["first_audio_byte", "460.0"],
    ]
    emergency = [line.split() for line in call_block(out, 3).splitlines()[5:]]
    assert emergency[2:4] == [["request_sent", "-"], ["first_token", "-"]]


def test_the_emergency_call_never_reaches_the_model(temp: Path, workdir: Path) -> None:
    run = Run()
    code, _ = run.main([], temp)
    assert code == 0
    emergency = CALLS[2].text
    assert emergency is not None
    assert is_emergency(emergency)
    assert run.chat is not None
    sent = [m.content for messages in run.chat.calls for m in messages if m.role == "user"]
    assert len(sent) == 1 + 3  # the warm-up, then the three calls that go to the model
    assert emergency not in sent
    assert not any(is_emergency(text) for text in sent)


def test_the_summary_has_the_range_hardware_tier_and_label(temp: Path, workdir: Path) -> None:
    _, out = Run().main([], temp)
    rows = {
        line.split()[0]: line.split()[1:]
        for line in out.split("Summary over the calls (warm-up excluded)\n")[1].splitlines()
        if line.split() and line.split()[0] in {"first_token", "first_audio_byte"}
    }
    assert rows == {
        "first_token": ["400.0", "400.0", "3"],
        "first_audio_byte": ["310.0", "460.0", "5"],
    }
    assert "  cpu: test cpu" in out
    assert "Tier asked for: standard (VOICE_MODEL)" in out
    assert out.rstrip().endswith(LABEL)


def test_a_call_that_takes_another_path_is_flagged_and_fails_the_exit(
    temp: Path, workdir: Path
) -> None:
    code, out = Run(heard=transcripts(silence="Thank you.")).main([], temp)
    assert code == 1
    assert "path:       model  (expected scripted no-speech)" in call_block(out, 5)


def test_warm_up_comes_first_and_is_not_counted(temp: Path, workdir: Path) -> None:
    run = Run()
    _, out = run.main([], temp)
    assert run.stt is not None
    assert len(run.stt.heard_ms) == 1 + len(CALLS)
    assert "Call 0" not in out
    assert call_block(out, 1).count("speech_end") == 1


def test_near_silence_is_quiet_and_the_same_every_time() -> None:
    pcm = near_silence(16_000)
    assert pcm == near_silence(16_000)
    assert Audio(pcm, 16_000).duration_ms == 1_500.0
    samples = memoryview(pcm).cast("h")
    assert max(abs(s) for s in samples) <= 30


# --- files ----------------------------------------------------------------------------------


def test_the_temporary_folder_is_deleted_and_nothing_else(temp: Path, workdir: Path) -> None:
    run = Run()
    seen: list[set[str]] = []
    run.play = lambda path: seen.append(files_under(path.parent))  # type: ignore[method-assign]
    code, _ = run.main(["--play"], temp)
    assert code == 0
    assert files_under(temp) == {"not-the-demos.txt"}
    assert {f"caller_{i}.wav" for i in range(1, 6)} <= seen[0]


def test_nothing_is_written_without_out(temp: Path, workdir: Path) -> None:
    code, _ = Run().main([], temp)
    assert code == 0
    assert files_under(workdir) == set()
    assert files_under(temp) == {"not-the-demos.txt"}


def test_out_writes_each_reply_and_its_transcript(temp: Path, workdir: Path) -> None:
    code, _ = Run().main(["--out", "replies"], temp)
    assert code == 0
    names = {
        f"replies/{kind}_{i}.{ext}"
        for i in range(1, 6)
        for kind, ext in [("reply", "wav"), ("call", "txt")]
    }
    assert files_under(workdir) == {"replies", *names}
    assert read_wav(workdir / "replies" / "reply_1.wav").duration_ms > 0
    text = (workdir / "replies" / "call_3.txt").read_text(encoding="utf-8")
    assert "path: scripted emergency" in text
    assert f"transcript: {CALLS[2].text}" in text


def test_play_plays_each_reply_while_it_exists_then_it_is_gone(temp: Path, workdir: Path) -> None:
    run = Run()
    code, _ = run.main(["--play"], temp)
    assert code == 0
    assert [p.name for p, _ in run.played] == [f"reply_{i}.wav" for i in range(1, 6)]
    assert all(existed for _, existed in run.played)
    assert all(p.parent.parent == temp and not p.exists() for p, _ in run.played)
    assert files_under(workdir) == set()


# --- refusals -------------------------------------------------------------------------------


def test_a_missing_key_stops_before_anything_loads(
    temp: Path, workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Run()
    code, out = run.main([], temp, env={})
    assert code == 2
    assert run.built == 0
    assert "GATEWAY_API_KEY is not set" in capsys.readouterr().err
    assert out == ""
    assert files_under(temp) == {"not-the-demos.txt"}


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (Unavailable(None, "gateway_unreachable"), "could not be reached; is it running?"),
        (NotAuthorized(401, "invalid_api_key"), "refused the key (HTTP 401)"),
        (Unavailable(503, "upstream_unavailable"), "warm-up request to the gateway failed"),
    ],
)
def test_a_failed_warm_up_stops_with_a_clear_message(
    error: SpokenError,
    message: str,
    temp: Path,
    workdir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = Run(fail=error)
    code, out = run.main([], temp)
    assert code == 2
    assert message in capsys.readouterr().err
    assert "Call 1" not in out
    assert run.chat is not None
    assert len(run.chat.calls) == 1  # the warm-up only
    assert run.closed == 1
    assert files_under(temp) == {"not-the-demos.txt"}


@pytest.mark.parametrize("fail", [None, NotAuthorized(401, "invalid_api_key")])
def test_the_key_is_never_printed_or_logged(
    fail: SpokenError | None,
    temp: Path,
    workdir: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, out = Run(fail=fail).main(["--out", "replies"], temp)
    captured = capsys.readouterr()
    places: list[tuple[str, Any]] = [
        ("stdout", out),
        ("captured stdout", captured.out),
        ("stderr", captured.err),
        ("logs", caplog.text),
        *((p.name, p.read_bytes().decode("latin-1")) for p in workdir.rglob("*") if p.is_file()),
    ]
    assert find_leaks(PLANTED_KEY, places) == []
    assert find_leaks(PLANTED_KEY, [("control", f"x{PLANTED_KEY}x")]) == ["control"]
