"""Text to speech with Piper (piper-tts, GPL-3.0-or-later), from a local voice file.

This is the only module that imports Piper; because it runs in the same process, the
repository is licensed GPL-3.0-or-later (docs/licenses.md). Another engine can replace it
behind ``TextToSpeech``.

Piper gives one chunk per sentence it finds; synthesis runs in a worker thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from piper import PiperVoice


class PiperTextToSpeech:
    def __init__(self, voice_path: Path, *, use_cuda: bool = False) -> None:
        if not voice_path.is_file() or not voice_path.with_suffix(".onnx.json").is_file():
            raise FileNotFoundError(
                f"No Piper voice at {voice_path}; run scripts/fetch_models.py first."
            )
        self._voice = PiperVoice.load(voice_path, use_cuda=use_cuda)

    @property
    def sample_rate(self) -> int:
        return int(self._voice.config.sample_rate)

    def _synthesize(self, text: str) -> list[bytes]:
        return [chunk.audio_int16_bytes for chunk in self._voice.synthesize(text)]

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        for chunk in await asyncio.to_thread(self._synthesize, text):
            yield chunk
