"""The six stage timestamps of one turn, on the injected clock.

Each stage is recorded the first time it happens; later marks are ignored. Results are
milliseconds after ``speech_end``. A stage that never happened (the gateway stages on the
emergency path, say) is ``None``, never 0.
"""

from __future__ import annotations

from enum import StrEnum

from voice_agent.clock import Clock


class Stage(StrEnum):
    SPEECH_END = "speech_end"
    TRANSCRIPT_READY = "transcript_ready"
    REQUEST_SENT = "request_sent"
    FIRST_TOKEN = "first_token"
    FIRST_SENTENCE = "first_sentence"
    FIRST_AUDIO_BYTE = "first_audio_byte"


StageTimes = dict[Stage, float | None]


class StageTimer:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._marks: dict[Stage, float] = {}

    def mark(self, stage: Stage) -> None:
        if stage not in self._marks:
            self._marks[stage] = self._clock.now_ms()

    def times(self) -> StageTimes:
        if Stage.SPEECH_END not in self._marks:
            raise RuntimeError("speech_end was never marked")
        origin = self._marks[Stage.SPEECH_END]
        return {
            stage: (self._marks[stage] - origin if stage in self._marks else None)
            for stage in Stage
        }
