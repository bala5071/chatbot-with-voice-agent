"""Five scripted calls to the mock clinic, through the real pipeline and the gateway.

    export GATEWAY_API_KEY=...   # yourself; never printed
    uv run python scripts/demo.py [--play] [--out DIR]

The callers' speech is synthesized here by Piper from fixed mock-clinic sentences (the fifth
call is a quiet generated tone, near-silence), never recorded (CLAUDE.md, hard rule 6). Those
WAVs go to a folder made with ``tempfile.mkdtemp``, and exactly that folder is deleted at the
end, also on failure. Every stage is warmed up first; the warm-up is not counted. A missing key
stops the demo before anything loads; a warm-up that cannot reach the gateway, or whose key is
refused, stops it with a clear message.

Per call it prints the transcript, the reply, the path that ran and the stage times; then the
min and max of each stage over the calls, the hardware and the tier asked for. These are single
demo runs on one machine, not a benchmark.

``--play`` plays each reply with the OS player. ``--out DIR`` writes each reply as a WAV with a
text file of its transcript and reply. Nothing else is written (hard rule 8).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from voice_agent.audio import Audio, read_wav, write_wav
from voice_agent.cli import DEFAULT_VOICE, DEFAULT_WHISPER_DIR, Builder, build_real
from voice_agent.clinic import load_clinic
from voice_agent.clock import Clock, WallClock
from voice_agent.config import ConfigError, Settings
from voice_agent.errors import NotAuthorized, SpokenError, Unavailable
from voice_agent.interfaces import TextToSpeech
from voice_agent.machine import hardware as machine_hardware
from voice_agent.pipeline import Outcome, Pipeline, TurnResult
from voice_agent.timing import Stage

LABEL = "Single demo runs on one machine, not a benchmark."
NEAR_SILENCE_MS = 1_500.0


@dataclass(frozen=True, slots=True)
class Call:
    name: str
    text: str | None  # None: near-silence
    expected: Outcome


CALLS: tuple[Call, ...] = (
    Call("opening hours", "Hi, what time do you open on Saturday?", Outcome.ANSWERED),
    Call("services", "Which services does the clinic offer?", Outcome.ANSWERED),
    Call("emergency", "My father is having chest pain and can't breathe.", Outcome.EMERGENCY),
    Call("medical advice", "What dose of ibuprofen should I take?", Outcome.ANSWERED),
    Call("near-silence", None, Outcome.NO_SPEECH),
)

PATHS: dict[Outcome, str] = {
    Outcome.ANSWERED: "model",
    Outcome.EMERGENCY: "scripted emergency",
    Outcome.NO_SPEECH: "scripted no-speech",
    Outcome.ERROR: "scripted error",
}

Player = Callable[[Path], None]
Hardware = Callable[[], dict[str, Any]]


class DemoError(Exception):
    pass


def near_silence(sample_rate: int, duration_ms: float = NEAR_SILENCE_MS) -> bytes:
    """A 50 Hz hum at amplitude 30 of 32767, 16-bit mono PCM; the same bytes every time."""
    count = round(duration_ms * sample_rate / 1000.0)
    return b"".join(
        struct.pack("<h", round(30 * math.sin(2 * math.pi * 50 * n / sample_rate)))
        for n in range(count)
    )


async def caller_audio(tts: TextToSpeech, call: Call) -> Audio:
    if call.text is None:
        return Audio(near_silence(tts.sample_rate), tts.sample_rate)
    return Audio(b"".join([c async for c in tts.synthesize(call.text)]), tts.sample_rate)


def os_player(path: Path) -> None:
    """Play a WAV with the operating system's player and wait for it to finish."""
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
    else:
        player = ["afplay"] if sys.platform == "darwin" else ["aplay", "-q"]
        try:
            subprocess.run([*player, str(path)], check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"could not play {path.name}: {type(exc).__name__}", file=sys.stderr)


def warm_up_failure(error: SpokenError, url: str) -> str:
    if isinstance(error, Unavailable) and error.code == "gateway_unreachable":
        return f"the gateway at {url} could not be reached; is it running?"
    if isinstance(error, NotAuthorized):
        return f"the gateway refused the key (HTTP {error.status}); check GATEWAY_API_KEY"
    return f"the warm-up request to the gateway failed: {error}"


def ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def path_of(result: TurnResult) -> str:
    path = PATHS[result.outcome]
    if result.error is not None:
        path += f" ({type(result.error).__name__})"
    return path


def spoken_text(result: TurnResult) -> str:
    return result.reply or (result.error.spoken if result.error is not None else "")


def call_report(index: int, call: Call, result: TurnResult) -> list[str]:
    path = path_of(result)
    if result.outcome is not call.expected:
        path += f"  (expected {PATHS[call.expected]})"
    lines = [
        f"Call {index}: {call.name}",
        f"  transcript: {result.transcript!r}",
        f"  reply:      {spoken_text(result)!r}",
        f"  path:       {path}",
        f"  {'stage':<18}{'ms':>10}",
    ]
    lines += [f"  {stage!s:<18}{ms(result.times[stage]):>10}" for stage in Stage]
    return lines


def summary(results: Sequence[TurnResult]) -> list[str]:
    lines = [f"{'stage':<18}{'min ms':>10}{'max ms':>10}{'calls':>7}"]
    for stage in Stage:
        values = [v for r in results if (v := r.times[stage]) is not None]
        low, high = (min(values), max(values)) if values else (None, None)
        lines.append(f"{stage!s:<18}{ms(low):>10}{ms(high):>10}{len(values):>7}")
    return lines


def save(out_dir: Path, index: int, call: Call, result: TurnResult) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_wav(out_dir / f"reply_{index}.wav", result.audio)
    (out_dir / f"call_{index}.txt").write_text(
        f"call: {call.name}\npath: {path_of(result)}\n"
        f"transcript: {result.transcript}\nreply: {spoken_text(result)}\n",
        encoding="utf-8",
    )


async def run(
    args: argparse.Namespace,
    settings: Settings,
    clock: Clock,
    build: Builder,
    out: TextIO,
    player: Player,
    hardware: Hardware,
    temp_parent: Path | None,
) -> int:
    settings.require_key()
    folder = Path(tempfile.mkdtemp(prefix="voice-demo-", dir=temp_parent))
    try:
        parts = build(args, settings, clock)
        try:
            pipeline = Pipeline(parts.stt, parts.chat, parts.tts, load_clinic(), clock)
            inputs: list[Path] = []
            for index, call in enumerate(CALLS, 1):
                path = folder / f"caller_{index}.wav"
                write_wav(path, await caller_audio(parts.tts, call))
                inputs.append(path)
            error = await pipeline.warm_up()
            if error is not None:
                raise DemoError(warm_up_failure(error, settings.gateway_url))
            results: list[TurnResult] = []
            for index, (call, path) in enumerate(zip(CALLS, inputs, strict=True), 1):
                result = await pipeline.turn(read_wav(path))
                results.append(result)
                print("\n".join(call_report(index, call, result)), file=out, flush=True)
                if args.play:
                    reply = folder / f"reply_{index}.wav"
                    write_wav(reply, result.audio)
                    player(reply)
                if args.out is not None:
                    save(args.out, index, call, result)
                print(file=out)
        finally:
            if parts.close is not None:
                await parts.close()
    finally:
        shutil.rmtree(folder)
    print("Summary over the calls (warm-up excluded)", file=out)
    print("\n".join(summary(results)), file=out)
    print("Hardware:", file=out)
    for name, value in hardware().items():
        print(f"  {name}: {value}", file=out)
    print(f"Tier asked for: {settings.model} (VOICE_MODEL), at {settings.gateway_url}", file=out)
    print(f"Whisper: {args.whisper_dir.name} on {args.device}", file=out)
    print(LABEL, file=out)
    matched = all(r.outcome is c.expected for c, r in zip(CALLS, results, strict=True))
    return 0 if matched else 1


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--play", action="store_true", help="play each reply with the OS player")
    p.add_argument("--out", type=Path, help="write reply WAVs and transcripts here")
    p.add_argument("--whisper-dir", type=Path, default=DEFAULT_WHISPER_DIR)
    p.add_argument("--voice", type=Path, default=DEFAULT_VOICE, help="Piper .onnx voice")
    # Whisper runs on the CPU (docs/licenses.md: GPU Whisper was declined).
    p.set_defaults(device="cpu", compute_type=None)
    return p


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    clock: Clock | None = None,
    build: Builder = build_real,
    out: TextIO | None = None,
    player: Player = os_player,
    hardware: Hardware = machine_hardware,
    temp_parent: Path | None = None,
) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = parser().parse_args(argv)
    stream = out if out is not None else sys.stdout
    try:
        settings = Settings.from_env(os.environ if env is None else env)
        return asyncio.run(
            run(
                args,
                settings,
                clock or WallClock(),
                build,
                stream,
                player,
                hardware,
                temp_parent,
            )
        )
    except (ConfigError, DemoError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
