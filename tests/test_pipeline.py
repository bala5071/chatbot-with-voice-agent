"""A whole turn on the fakes and a FakeClock: every stage time is exact."""

from __future__ import annotations

import pytest

from voice_agent.audio import Audio
from voice_agent.clinic import load_clinic
from voice_agent.clock import FakeClock
from voice_agent.errors import Busy, TimedOut
from voice_agent.fakes import Delta, FakeChatClient, FakeSpeechToText, FakeTextToSpeech, tone
from voice_agent.pipeline import NO_SPEECH_TEXT, Outcome, Pipeline
from voice_agent.safety import EMERGENCY_TEXT
from voice_agent.timing import Stage

UTTERANCE = Audio(tone(500, 16_000), 16_000)
REPLY = [
    Delta(200, "Hello"),
    Delta(50, " there."),
    Delta(40, " We open at 8 a.m. on Monday."),
]


def build(
    clock: FakeClock,
    transcript: str = "What are your hours on Monday?",
    script: list[Delta] | None = None,
    **chat: object,
) -> tuple[Pipeline, FakeChatClient, FakeTextToSpeech]:
    stt = FakeSpeechToText(clock, transcript, duration_ms=300)
    tts = FakeTextToSpeech(clock, first_chunk_ms=70)
    fake_chat = FakeChatClient(clock, REPLY if script is None else script, **chat)  # type: ignore[arg-type]
    return Pipeline(stt, fake_chat, tts, load_clinic(), clock), fake_chat, tts


async def test_stage_times_are_exact() -> None:
    clock = FakeClock(start_ms=10_000)
    pipeline, _, tts = build(clock)
    result = await pipeline.turn(UTTERANCE)
    assert result.outcome is Outcome.ANSWERED
    assert result.times == {
        Stage.SPEECH_END: 0.0,
        Stage.TRANSCRIPT_READY: 300.0,  # STT took 300 ms
        Stage.REQUEST_SENT: 300.0,  # sent at once
        Stage.FIRST_TOKEN: 500.0,  # 200 ms to the first token
        Stage.FIRST_SENTENCE: 590.0,  # "Hello there." ends when the third delta arrives
        Stage.FIRST_AUDIO_BYTE: 660.0,  # 70 ms to the first chunk of audio
    }
    assert tts.spoken == ["Hello there.", "We open at 8 a.m. on Monday."]
    assert result.reply == "Hello there. We open at 8 a.m. on Monday."
    assert result.audio.sample_rate == 16_000
    assert len(result.audio.pcm) > 0


async def test_warm_up_never_counts() -> None:
    cold_clock = FakeClock()
    cold, _, _ = build(cold_clock)
    cold_times = (await cold.turn(UTTERANCE)).times

    clock = FakeClock()
    warm, chat, tts = build(clock)
    assert await warm.warm_up() is None
    assert clock.now_ms() > 0  # warm-up took (fake) time
    assert len(chat.calls) == 1  # and exercised every stage
    assert tts.spoken
    result = await warm.turn(UTTERANCE)
    assert result.times == cold_times


async def test_a_failed_warm_up_returns_the_error_and_does_not_raise() -> None:
    clock = FakeClock()
    failure = Busy(429, "rate_limited")
    pipeline, chat, _ = build(clock, fail=failure)
    assert await pipeline.warm_up() is failure
    assert len(chat.calls) == 1


async def test_emergency_is_scripted_and_the_model_is_never_called() -> None:
    clock = FakeClock()
    pipeline, chat, tts = build(clock, transcript="My father has chest pain and can't breathe")
    result = await pipeline.turn(UTTERANCE)
    assert result.outcome is Outcome.EMERGENCY
    assert chat.calls == []
    assert tts.spoken == [EMERGENCY_TEXT]
    assert result.reply == EMERGENCY_TEXT
    assert result.times[Stage.REQUEST_SENT] is None
    assert result.times[Stage.FIRST_TOKEN] is None
    assert result.times[Stage.FIRST_SENTENCE] == 300.0
    assert result.times[Stage.FIRST_AUDIO_BYTE] == 370.0


async def test_no_speech_asks_again_without_calling_the_model() -> None:
    clock = FakeClock()
    pipeline, chat, tts = build(clock, transcript="   ")
    result = await pipeline.turn(UTTERANCE)
    assert result.outcome is Outcome.NO_SPEECH
    assert chat.calls == []
    assert tts.spoken == [NO_SPEECH_TEXT]


async def test_error_before_output_speaks_the_fixed_sentence() -> None:
    clock = FakeClock()
    pipeline, _, tts = build(clock, fail=Busy(429, "rate_limited"), fail_after=0)
    result = await pipeline.turn(UTTERANCE)
    assert result.outcome is Outcome.ERROR
    assert isinstance(result.error, Busy)
    assert tts.spoken == [Busy.spoken]
    assert result.reply == ""
    assert result.times[Stage.FIRST_TOKEN] is None


async def test_error_mid_reply_drops_the_partial_audio() -> None:
    clock = FakeClock()
    pipeline, _, tts = build(clock, fail=TimedOut(None, "deadline"), fail_after=3)
    script_tts = FakeTextToSpeech(FakeClock(), first_chunk_ms=0)
    expected = b"".join([c async for c in script_tts.synthesize(TimedOut.spoken)])

    result = await pipeline.turn(UTTERANCE)
    assert result.outcome is Outcome.ERROR
    assert tts.spoken[0] == "Hello there."  # the partial reply was synthesized ...
    assert tts.spoken[-1] == TimedOut.spoken
    assert result.audio.pcm == expected  # ... but only the error sentence is in the output


@pytest.mark.parametrize("deltas", [["Fine."], ["", "Fine."]])
async def test_empty_deltas_do_not_count_as_the_first_token(deltas: list[str]) -> None:
    clock = FakeClock()
    script = [Delta(100, text) for text in deltas]
    pipeline, _, _ = build(clock, script=script)
    result = await pipeline.turn(UTTERANCE)
    assert result.times[Stage.FIRST_TOKEN] == 300.0 + 100.0 * len(deltas)
