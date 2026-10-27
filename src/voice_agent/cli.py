"""``python -m voice_agent``: one push-to-talk turn from a WAV file. The only wiring point.

    uv run python -m voice_agent --in question.wav --out reply.wav --timings

It reads ``GATEWAY_URL`` and ``GATEWAY_API_KEY`` from the environment, warms up every stage
(warm-up never counts), runs one turn, and writes the reply to ``--out`` if given. That file
is the only one it writes. ``--timings`` prints the six stage times as JSON; ``--show-text``
prints the transcript and the reply. Neither is ever logged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from voice_agent.audio import AudioFormatError, read_wav, write_wav
from voice_agent.clinic import load_clinic
from voice_agent.clock import Clock, WallClock
from voice_agent.config import ConfigError, Settings
from voice_agent.interfaces import ChatClient, SpeechToText, TextToSpeech
from voice_agent.pipeline import Pipeline

log = logging.getLogger("voice_agent")

DEFAULT_WHISPER_DIR = Path("models/faster-whisper-small")
DEFAULT_VOICE = Path("models/piper-en_US-ljspeech-medium/en_US-ljspeech-medium.onnx")


@dataclass(frozen=True, slots=True)
class Components:
    stt: SpeechToText
    tts: TextToSpeech
    chat: ChatClient
    # Called when the turn is over (closes the HTTP client).
    close: Callable[[], Awaitable[None]] | None = None


Builder = Callable[[argparse.Namespace, Settings, Clock], Components]


def build_real(args: argparse.Namespace, settings: Settings, clock: Clock) -> Components:
    key = settings.require_key()
    # Imported here so that tests and CI, which never load a model, never import the engines.
    from voice_agent.engines.faster_whisper import FasterWhisperSpeechToText
    from voice_agent.engines.piper import PiperTextToSpeech
    from voice_agent.gateway_client import GatewayClient, make_http_client

    http = make_http_client(settings.gateway_url)
    chat = GatewayClient(
        http,
        key,
        clock,
        model=settings.model,
        max_tokens=settings.max_tokens,
        first_token_timeout_ms=settings.first_token_timeout_ms,
        total_timeout_ms=settings.total_timeout_ms,
    )
    stt = FasterWhisperSpeechToText(
        args.whisper_dir, device=args.device, compute_type=args.compute_type
    )
    tts = PiperTextToSpeech(args.voice)
    return Components(stt, tts, chat, http.aclose)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="voice_agent", description=__doc__.splitlines()[0])
    p.add_argument("--in", dest="input", type=Path, required=True, help="mono 16-bit WAV")
    p.add_argument("--out", type=Path, help="write the reply here (nothing is written without it)")
    p.add_argument("--whisper-dir", type=Path, default=DEFAULT_WHISPER_DIR)
    p.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    p.add_argument(
        "--compute-type",
        choices=["int8", "int8_float16", "int8_float32", "float16", "float32"],
        help="default: int8 on cpu, int8_float16 on cuda",
    )
    p.add_argument("--voice", type=Path, default=DEFAULT_VOICE, help="Piper .onnx voice")
    p.add_argument("--timings", action="store_true", help="print the stage times as JSON")
    p.add_argument("--show-text", action="store_true", help="print transcript and reply")
    return p


async def run(
    args: argparse.Namespace,
    settings: Settings,
    clock: Clock,
    build: Builder,
    out: TextIO,
) -> int:
    utterance = read_wav(args.input)
    parts = build(args, settings, clock)
    try:
        pipeline = Pipeline(parts.stt, parts.chat, parts.tts, load_clinic(), clock)
        await pipeline.warm_up()
        result = await pipeline.turn(utterance)
    finally:
        if parts.close is not None:
            await parts.close()
    if args.out is not None:
        write_wav(args.out, result.audio)
    log.info("turn finished: %s", result.outcome)
    if args.show_text:
        print(f"caller: {result.transcript}", file=out)
        print(f"agent:  {result.reply or (result.error.spoken if result.error else '')}", file=out)
    if args.timings:
        report = {
            "outcome": str(result.outcome),
            "error": type(result.error).__name__ if result.error else None,
            "stages_ms": {str(stage): t for stage, t in result.times.items()},
        }
        print(json.dumps(report, indent=2), file=out)
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    clock: Clock | None = None,
    build: Builder = build_real,
    out: TextIO | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parser().parse_args(argv)
    stream = out if out is not None else sys.stdout
    try:
        settings = Settings.from_env(os.environ if env is None else env)
        return asyncio.run(run(args, settings, clock or WallClock(), build, stream))
    except (ConfigError, AudioFormatError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
