"""Do Whisper and an Ollama tier fit on this GPU together? Measured, one machine, one run.

    uv run python scripts/gpu_budget.py [--voice-tier standard] [--compute-type int8_float16]

1. Before loading anything: GPU memory already in use (other processes, including any model
   Ollama already holds; listed from Ollama's /api/ps).
2. Load Whisper on CUDA and transcribe synthetic speech made by Piper on the CPU.
3. For each tier: load it in Ollama, then run a Whisper transcription and an Ollama generation
   at the same time, so both models' working memory is in use together. ``nvidia-smi -lms 100``
   samples memory throughout; the peak of each phase is recorded. Ollama's /api/ps says how
   much of the model it put in VRAM. Only a model this script loaded is unloaded afterwards.
4. A tier fits if all of it is in VRAM and the peak stays below total minus ``--headroom-mib``.

Prints JSON (hardware, every number, which tiers fit) and a summary. Exit 0 if the voice tier
fits with Whisper on the GPU; 1 if it does not, or Whisper could not run on CUDA; 2 if
nvidia-smi or Ollama cannot be reached. It talks to Ollama directly on loopback, not through
the gateway: it measures memory, not the gateway.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from voice_agent.audio import Audio
from voice_agent.clock import WallClock

ROOT = Path(__file__).resolve().parent.parent

# The gateway's tiers and the Ollama tags its Ollama backend config serves them with.
TIERS = {
    "economy": "llama3.2:1b-instruct-q4_K_M",
    "standard": "llama3.2:3b",
    "premium": "llama3.1:8b",
}
SPEECH = "Hello, I would like to book an appointment for next Tuesday morning, please."
MIB = 1024 * 1024


class Sampler:
    """``nvidia-smi -lms 100`` in the background; memory.used in MiB, one sample per line."""

    def __init__(self) -> None:
        self.samples: list[int] = []
        self._proc = subprocess.Popen(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
                "-lms",
                "100",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if line.isdigit():
                self.samples.append(int(line))

    def mark(self) -> int:
        return len(self.samples)

    def peak(self, since: int) -> int | None:
        window = self.samples[since:]
        return max(window) if window else None

    def stop(self) -> None:
        self._proc.terminate()
        self._proc.wait(timeout=10)


def query_gpu() -> dict[str, Any]:
    out = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.used",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    name, driver, total, used = (part.strip() for part in out.splitlines()[0].split(","))
    return {"name": name, "driver": driver, "total_mib": int(total), "used_mib": int(used)}


def memory_used() -> int:
    return int(query_gpu()["used_mib"])


@dataclass
class TierResult:
    tier: str
    ollama_model: str
    preloaded: bool = False
    size_mib: float | None = None
    vram_mib: float | None = None
    fully_in_vram: bool | None = None
    used_after_load_mib: int | None = None
    peak_together_mib: int | None = None
    fits: bool = False
    note: str = ""


@dataclass
class Report:
    label: str = "one machine, one run"
    command: str = ""
    hardware: dict[str, Any] = field(default_factory=dict)
    in_use_before_mib: int | None = None
    ollama_loaded_before: list[str] = field(default_factory=list)
    whisper: dict[str, Any] = field(default_factory=dict)
    headroom_mib: int = 0
    voice_tier: str = ""
    tiers: list[TierResult] = field(default_factory=list)


async def ollama_ps(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    response = await client.get("/api/ps")
    response.raise_for_status()
    return {m["name"]: m for m in response.json().get("models", [])}


async def ollama_generate(
    client: httpx.AsyncClient, model: str, prompt: str, keep_alive: str | int
) -> None:
    body: dict[str, Any] = {"model": model, "stream": False, "keep_alive": keep_alive}
    if prompt:
        body.update(prompt=prompt, options={"num_predict": 32, "temperature": 0})
    response = await client.post("/api/generate", json=body, timeout=600.0)
    response.raise_for_status()


async def wait_unloaded(client: httpx.AsyncClient, model: str) -> None:
    clock = WallClock()
    for _ in range(60):
        if model not in await ollama_ps(client):
            return
        await clock.sleep(500)


def synthetic_speech(voice: Path) -> Audio:
    """Speech made here by Piper on the CPU (CLAUDE.md, hard rule 6)."""
    from voice_agent.engines.piper import PiperTextToSpeech

    tts = PiperTextToSpeech(voice)

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in tts.synthesize(SPEECH)])

    return Audio(asyncio.run(collect()), tts.sample_rate)


async def measure(args: argparse.Namespace, report: Report) -> int:
    sampler = Sampler()
    stt = None
    try:
        speech = await asyncio.to_thread(synthetic_speech, args.voice)
        start = sampler.mark()
        try:
            from voice_agent.engines.faster_whisper import FasterWhisperSpeechToText

            stt = FasterWhisperSpeechToText(
                args.whisper_dir, device="cuda", compute_type=args.compute_type
            )
            transcript = await stt.transcribe(speech)
            report.whisper.update(
                loaded=True,
                compute_type=stt.compute_type,
                used_after_mib=memory_used(),
                peak_mib=sampler.peak(start),
                transcribed_words=len(transcript.split()),
            )
        except Exception as exc:  # the CUDA runtime is missing, out of memory, ...
            stt = None
            report.whisper.update(loaded=False, error=f"{type(exc).__name__}: {exc}")

        async with httpx.AsyncClient(
            base_url=args.ollama, trust_env=False, follow_redirects=False
        ) as client:
            for tier, model in TIERS.items():
                result = TierResult(tier, model, preloaded=model in report.ollama_loaded_before)
                report.tiers.append(result)
                phase = sampler.mark()
                try:
                    await ollama_generate(client, model, "Say OK.", "5m")
                    result.used_after_load_mib = memory_used()
                    together = ollama_generate(client, model, "Count from one to ten.", "5m")
                    if stt is not None:
                        await asyncio.gather(together, stt.transcribe(speech))
                    else:
                        await together
                    loaded = (await ollama_ps(client)).get(model)
                    result.peak_together_mib = sampler.peak(phase)
                    if loaded is not None:
                        result.size_mib = round(loaded["size"] / MIB, 1)
                        result.vram_mib = round(loaded["size_vram"] / MIB, 1)
                        result.fully_in_vram = loaded["size_vram"] >= loaded["size"]
                    limit = report.hardware["total_mib"] - args.headroom_mib
                    result.fits = bool(
                        stt is not None
                        and result.fully_in_vram
                        and result.peak_together_mib is not None
                        and result.peak_together_mib <= limit
                    )
                    if stt is None:
                        result.note = "Whisper not on the GPU; the tier was measured alone"
                    elif not result.fully_in_vram:
                        result.note = "Ollama put part of the model on the CPU"
                    elif not result.fits:
                        result.note = f"peak above {limit} MiB (total minus headroom)"
                except httpx.HTTPError as exc:
                    result.note = f"Ollama: {type(exc).__name__}: {exc}"
                finally:
                    if not result.preloaded:
                        try:
                            await ollama_generate(client, model, "", 0)
                            await wait_unloaded(client, model)
                        except httpx.HTTPError:
                            pass
    finally:
        sampler.stop()
    voice = next(t for t in report.tiers if t.tier == report.voice_tier)
    return 0 if voice.fits else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--voice-tier", choices=list(TIERS), default="standard")
    p.add_argument("--whisper-dir", type=Path, default=ROOT / "models/faster-whisper-small")
    p.add_argument("--compute-type", default="int8_float16")
    p.add_argument(
        "--voice",
        type=Path,
        default=ROOT / "models/piper-en_US-ljspeech-medium/en_US-ljspeech-medium.onnx",
    )
    p.add_argument("--headroom-mib", type=int, default=512)
    p.add_argument("--ollama", default="http://127.0.0.1:11434")
    args = p.parse_args(argv)

    report = Report(
        command=" ".join(["uv run python scripts/gpu_budget.py", *(argv or sys.argv[1:])]),
        headroom_mib=args.headroom_mib,
        voice_tier=args.voice_tier,
    )
    try:
        gpu = query_gpu()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"error: nvidia-smi failed: {exc}", file=sys.stderr)
        return 2
    report.hardware = {
        "gpu": gpu["name"],
        "driver": gpu["driver"],
        "total_mib": gpu["total_mib"],
        "cpu": platform.processor(),
        "os": platform.platform(),
        "python": platform.python_version(),
    }
    report.in_use_before_mib = gpu["used_mib"]
    try:
        report.ollama_loaded_before = sorted(asyncio.run(_ps_once(args.ollama)).keys())
    except httpx.HTTPError as exc:
        print(f"error: Ollama is not reachable at {args.ollama}: {exc}", file=sys.stderr)
        return 2

    code = asyncio.run(measure(args, report))
    print(json.dumps(asdict(report), indent=2))
    print()
    print(f"GPU: {gpu['name']}, {gpu['total_mib']} MiB; in use before: {gpu['used_mib']} MiB")
    if report.whisper.get("loaded"):
        print(f"Whisper on CUDA ({report.whisper['compute_type']}): loaded")
    else:
        print(f"Whisper on CUDA: FAILED ({report.whisper.get('error')})")
    for t in report.tiers:
        verdict = "fits" if t.fits else "does not fit"
        print(
            f"  {t.tier:8} {t.ollama_model:28} {verdict:12} peak {t.peak_together_mib} MiB, "
            f"in VRAM {t.vram_mib}/{t.size_mib} MiB {('- ' + t.note) if t.note else ''}"
        )
    print(
        f"Voice tier {args.voice_tier}: {'fits' if code == 0 else 'does NOT fit'}. "
        "One machine, one run."
    )
    return code


async def _ps_once(base_url: str) -> dict[str, dict[str, Any]]:
    async with httpx.AsyncClient(base_url=base_url, trust_env=False) as client:
        return await ollama_ps(client)


if __name__ == "__main__":
    sys.exit(main())
