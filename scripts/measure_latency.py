"""Measure the six stage times on this machine: one warm-up, then three turns.

    export GATEWAY_API_KEY=...   # yourself; never printed
    uv run python scripts/measure_latency.py [--device cpu|cuda] [--runs 3]

Needs the gateway running in front of Ollama, and the models in models/. The caller's speech
is synthesized here by Piper from a fixed mock question (CLAUDE.md, hard rule 6). The warm-up
is not counted. Every run must be answered by the model; a scripted or failed turn stops the
measurement rather than being counted.

Prints JSON: the hardware, the settings, every run's stage times, and the min and max of
each stage, labelled "one machine". Paste it into docs/latency.md with the commit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from voice_agent.audio import Audio
from voice_agent.cli import DEFAULT_VOICE, DEFAULT_WHISPER_DIR, build_real
from voice_agent.clinic import load_clinic
from voice_agent.clock import WallClock
from voice_agent.config import ConfigError, Settings
from voice_agent.machine import hardware
from voice_agent.pipeline import Outcome, Pipeline
from voice_agent.timing import Stage

QUESTION = "Hi, what time do you open on Saturday?"


async def measure(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    clock = WallClock()
    parts = build_real(args, settings, clock)
    try:
        speech = Audio(
            b"".join([c async for c in parts.tts.synthesize(QUESTION)]), parts.tts.sample_rate
        )
        pipeline = Pipeline(parts.stt, parts.chat, parts.tts, load_clinic(), clock)
        await pipeline.warm_up()
        runs: list[dict[str, float | None]] = []
        for index in range(args.runs):
            result = await pipeline.turn(speech)
            if result.outcome is not Outcome.ANSWERED:
                error = type(result.error).__name__ if result.error else None
                raise SystemExit(f"run {index + 1}: {result.outcome} ({error}); not counted")
            runs.append({str(stage): t for stage, t in result.times.items()})
    finally:
        if parts.close is not None:
            await parts.close()
    ranges = {}
    for stage in Stage:
        values = [v for r in runs if (v := r[str(stage)]) is not None]
        ranges[str(stage)] = {"min": min(values), "max": max(values)} if values else None
    return {"runs": runs, "range_ms": ranges}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    p.add_argument("--compute-type", default=None)
    p.add_argument("--whisper-dir", type=Path, default=DEFAULT_WHISPER_DIR)
    p.add_argument("--voice", type=Path, default=DEFAULT_VOICE)
    args = p.parse_args(argv)
    try:
        settings = Settings.from_env(os.environ)
        settings.require_key()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    measured = asyncio.run(measure(args, settings))
    report = {
        "label": "one machine",
        "command": " ".join(["uv run python scripts/measure_latency.py", *sys.argv[1:]]),
        "hardware": hardware(),
        "settings": {
            "gateway_url": settings.gateway_url,
            "model": settings.model,
            "whisper": f"{args.whisper_dir.name} on {args.device}"
            + (f" ({args.compute_type})" if args.compute_type else ""),
            "voice": args.voice.name,
            "question": QUESTION,
        },
        **measured,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
