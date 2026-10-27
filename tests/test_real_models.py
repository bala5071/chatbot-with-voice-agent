"""Real engines on the downloaded models: skipped unless VOICE_REAL_MODELS=1; CI never runs
them. The speech is synthesized here by Piper, never recorded (CLAUDE.md, hard rule 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from voice_agent.audio import Audio
from voice_agent.safety import normalize

ROOT = Path(__file__).resolve().parent.parent
VOICE = ROOT / "models/piper-en_US-ljspeech-medium/en_US-ljspeech-medium.onnx"
WHISPER = ROOT / "models/faster-whisper-small"

pytestmark = pytest.mark.real_models


async def test_piper_speech_round_trips_through_whisper_on_cpu() -> None:
    from voice_agent.engines.faster_whisper import FasterWhisperSpeechToText
    from voice_agent.engines.piper import PiperTextToSpeech

    text = "I would like to book an appointment for Tuesday morning."
    tts = PiperTextToSpeech(VOICE)
    pcm = b"".join([chunk async for chunk in tts.synthesize(text)])
    stt = FasterWhisperSpeechToText(WHISPER, device="cpu")
    transcript = await stt.transcribe(Audio(pcm, tts.sample_rate))
    assert normalize(transcript) == normalize(text)
