"""Speech to text with faster-whisper (MIT), from a local model directory.

The model is loaded from ``models/`` (``scripts/fetch_models.py``); nothing is downloaded
here. Audio is decoded and resampled to 16 kHz in memory: no temporary file is written.
Transcription runs in a worker thread so the event loop keeps going.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio

from voice_agent.audio import Audio

WHISPER_RATE = 16_000


def default_compute_type(device: str) -> str:
    return "int8_float16" if device == "cuda" else "int8"


class FasterWhisperSpeechToText:
    def __init__(
        self,
        model_dir: Path,
        *,
        device: str = "cpu",
        compute_type: str | None = None,
        language: str = "en",
        beam_size: int = 1,
    ) -> None:
        if not (model_dir / "model.bin").is_file():
            raise FileNotFoundError(
                f"No Whisper model in {model_dir}; run scripts/fetch_models.py first."
            )
        self.device = device
        self.compute_type = compute_type or default_compute_type(device)
        self._language = language
        self._beam_size = beam_size
        self._model: Any = WhisperModel(
            str(model_dir), device=device, compute_type=self.compute_type, local_files_only=True
        )

    def _transcribe(self, audio: Audio) -> str:
        samples = decode_audio(io.BytesIO(audio.to_wav_bytes()), sampling_rate=WHISPER_RATE)
        segments, _info = self._model.transcribe(
            samples, language=self._language, beam_size=self._beam_size, vad_filter=False
        )
        return " ".join(str(segment.text).strip() for segment in segments).strip()

    async def transcribe(self, audio: Audio) -> str:
        return await asyncio.to_thread(self._transcribe, audio)
