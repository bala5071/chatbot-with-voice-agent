"""Deterministic fakes for the three interfaces (CLAUDE.md, hard rule 2).

Each takes its durations from the caller and advances the injected ``FakeClock`` by exactly
that much, so a test can assert every stage time exactly. Nothing reads real time or a global
random source. The fake TTS makes a synthetic tone whose length follows the text, so test
audio is generated here, never recorded (hard rule 6).
"""

from __future__ import annotations

import math
import struct
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field

from voice_agent.audio import Audio
from voice_agent.clock import FakeClock
from voice_agent.errors import SpokenError
from voice_agent.interfaces import Message


class FakeSpeechToText:
    def __init__(self, clock: FakeClock, transcript: str, duration_ms: float) -> None:
        self._clock = clock
        self.transcript = transcript
        self.duration_ms = duration_ms
        self.calls = 0

    async def transcribe(self, audio: Audio) -> str:
        self.calls += 1
        self._clock.advance(self.duration_ms)
        return self.transcript


def tone(duration_ms: float, sample_rate: int, hz: float = 440.0) -> bytes:
    """A synthetic sine tone, 16-bit mono PCM; the same bytes every time."""
    count = round(duration_ms * sample_rate / 1000.0)
    return b"".join(
        struct.pack("<h", round(8000 * math.sin(2 * math.pi * hz * n / sample_rate)))
        for n in range(count)
    )


class FakeTextToSpeech:
    """``first_chunk_ms`` passes before each sentence's first chunk; each sentence yields
    ``chunks`` chunks of tone, ``ms_per_char`` of audio per character in all."""

    def __init__(
        self,
        clock: FakeClock,
        first_chunk_ms: float,
        *,
        sample_rate: int = 16_000,
        chunks: int = 2,
        ms_per_char: float = 5.0,
    ) -> None:
        self._clock = clock
        self.first_chunk_ms = first_chunk_ms
        self._sample_rate = sample_rate
        self.chunks = chunks
        self.ms_per_char = ms_per_char
        self.spoken: list[str] = []

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        self.spoken.append(text)
        self._clock.advance(self.first_chunk_ms)
        per_chunk = len(text) * self.ms_per_char / self.chunks
        for _ in range(self.chunks):
            yield tone(per_chunk, self._sample_rate)


@dataclass(frozen=True, slots=True)
class Delta:
    after_ms: float  # time that passes before this delta arrives
    text: str


@dataclass
class FakeChatClient:
    """Calls ``on_sent``, then yields each delta of ``script`` after its ``after_ms``.
    ``fail`` is raised after ``fail_after`` deltas (0: before any output)."""

    clock: FakeClock
    script: Sequence[Delta]
    fail: SpokenError | None = None
    fail_after: int = 0
    calls: list[Sequence[Message]] = field(default_factory=list)

    async def stream(
        self, messages: Sequence[Message], on_sent: Callable[[], None]
    ) -> AsyncIterator[str]:
        self.calls.append(messages)
        on_sent()
        for index, delta in enumerate(self.script):
            if self.fail is not None and index == self.fail_after:
                raise self.fail
            self.clock.advance(delta.after_ms)
            yield delta.text
        if self.fail is not None and self.fail_after >= len(self.script):
            raise self.fail
