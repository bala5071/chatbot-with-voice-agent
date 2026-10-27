"""Audio as 16-bit mono PCM in memory, and WAV in and out.

Nothing here writes a file on its own: ``write_wav`` is called only by the CLI, for the
output file the user asked for (CLAUDE.md, hard rule 8).
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from pathlib import Path

SAMPLE_WIDTH = 2  # bytes: 16-bit PCM


class AudioFormatError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Audio:
    pcm: bytes  # signed 16-bit little-endian, mono
    sample_rate: int

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise AudioFormatError("sample rate must be positive")
        if len(self.pcm) % SAMPLE_WIDTH:
            raise AudioFormatError("16-bit PCM must have an even number of bytes")

    @property
    def duration_ms(self) -> float:
        return len(self.pcm) / SAMPLE_WIDTH / self.sample_rate * 1000.0

    def to_wav_bytes(self) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(SAMPLE_WIDTH)
            out.setframerate(self.sample_rate)
            out.writeframes(self.pcm)
        return buffer.getvalue()


def read_wav(path: Path) -> Audio:
    """A mono 16-bit PCM WAV file. Anything else is refused with a clear message."""
    with wave.open(str(path), "rb") as src:
        if src.getnchannels() != 1 or src.getsampwidth() != SAMPLE_WIDTH:
            raise AudioFormatError(
                f"{path.name}: need mono 16-bit PCM WAV, got {src.getnchannels()} channel(s) "
                f"of {8 * src.getsampwidth()}-bit"
            )
        return Audio(src.readframes(src.getnframes()), src.getframerate())


def write_wav(path: Path, audio: Audio) -> None:
    path.write_bytes(audio.to_wav_bytes())
