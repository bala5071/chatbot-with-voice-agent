"""The three interfaces the pipeline talks to. Each has a deterministic fake in ``fakes.py``
and a real implementation (``engines/`` and ``gateway_client.py``), so CI needs no model and
no network (CLAUDE.md, hard rule 2)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from voice_agent.audio import Audio


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


class SpeechToText(Protocol):
    async def transcribe(self, audio: Audio) -> str:
        """The final transcript of one utterance."""
        ...


class TextToSpeech(Protocol):
    @property
    def sample_rate(self) -> int: ...

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """16-bit mono PCM chunks at ``sample_rate``, in order."""
        ...


class ChatClient(Protocol):
    def stream(
        self, messages: Sequence[Message], on_sent: Callable[[], None]
    ) -> AsyncIterator[str]:
        """The reply as text deltas. ``on_sent`` is called once, just before the request is
        written. Raises a ``SpokenError`` on failure."""
        ...
