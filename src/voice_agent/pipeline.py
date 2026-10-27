"""One push-to-talk turn: the caller's audio in, the agent's spoken reply out.

1. ``speech_end``: the complete utterance is handed over.
2. Transcribe it (``transcript_ready``).
3. Emergency? Say the fixed text; the model is never asked (``safety.py``). Then the same for
   a request for medical advice, with its own fixed text.
4. Otherwise stream the reply from the chat client (``request_sent``, ``first_token``), cut it
   into sentences (``first_sentence``) and synthesize each as soon as it is complete
   (``first_audio_byte``).
5. On a ``SpokenError``, any partial reply audio is dropped and the error's fixed sentence is
   said instead.

``first_sentence`` and ``first_audio_byte`` are about whatever the agent says first: the
model's reply, a scripted text, or an error sentence. ``outcome`` says which. (After an
error mid-reply they keep the times of the dropped audio; only answered turns are reported
as latency.)

Nothing here writes a file or logs text: the transcript and reply stay in the returned
result, in memory, for the caller to use or drop (CLAUDE.md, hard rule 8).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from voice_agent.audio import Audio
from voice_agent.clinic import Clinic, system_prompt
from voice_agent.clock import Clock
from voice_agent.errors import SpokenError
from voice_agent.interfaces import ChatClient, Message, SpeechToText, TextToSpeech
from voice_agent.safety import (
    EMERGENCY_TEXT,
    MEDICAL_ADVICE_TEXT,
    is_emergency,
    is_medical_advice_request,
)
from voice_agent.sentences import SentenceSplitter
from voice_agent.timing import Stage, StageTimer, StageTimes

log = logging.getLogger(__name__)

NO_SPEECH_TEXT = "Sorry, I didn't catch that. Could you say it again?"
WARM_UP_TEXT = "Hello, this is a warm up."
WARM_UP_PROMPT = "Reply with the single word: ready."


class Outcome(StrEnum):
    ANSWERED = "answered"
    EMERGENCY = "emergency"
    MEDICAL_ADVICE = "medical_advice"
    NO_SPEECH = "no_speech"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TurnResult:
    outcome: Outcome
    audio: Audio
    times: StageTimes
    transcript: str
    reply: str
    error: SpokenError | None = None


class Pipeline:
    def __init__(
        self,
        stt: SpeechToText,
        chat: ChatClient,
        tts: TextToSpeech,
        clinic: Clinic,
        clock: Clock,
    ) -> None:
        self._stt = stt
        self._chat = chat
        self._tts = tts
        self._system = Message("system", system_prompt(clinic))
        self._clock = clock

    async def warm_up(self) -> SpokenError | None:
        """Load and exercise every stage once. Its timings are thrown away: warm-up never
        counts. A gateway failure here is logged by type and returned, not raised; the CLI
        ignores it (the real turn will meet it again and say so), the demo stops on it."""
        timer = StageTimer(self._clock)
        pcm = b"".join([chunk async for chunk in self._tts.synthesize(WARM_UP_TEXT)])
        await self._stt.transcribe(Audio(pcm, self._tts.sample_rate))
        try:
            async for _ in self._chat.stream(
                [self._system, Message("user", WARM_UP_PROMPT)],
                lambda: timer.mark(Stage.REQUEST_SENT),
            ):
                pass
        except SpokenError as exc:
            log.warning("warm-up request failed: %s", exc)
            return exc
        return None

    async def turn(self, utterance: Audio) -> TurnResult:
        timer = StageTimer(self._clock)
        timer.mark(Stage.SPEECH_END)
        transcript = (await self._stt.transcribe(utterance)).strip()
        timer.mark(Stage.TRANSCRIPT_READY)

        if not transcript:
            return await self._scripted(timer, Outcome.NO_SPEECH, NO_SPEECH_TEXT, transcript)
        if is_emergency(transcript):
            return await self._scripted(timer, Outcome.EMERGENCY, EMERGENCY_TEXT, transcript)
        if is_medical_advice_request(transcript):
            return await self._scripted(
                timer, Outcome.MEDICAL_ADVICE, MEDICAL_ADVICE_TEXT, transcript
            )

        pcm: list[bytes] = []
        reply: list[str] = []
        splitter = SentenceSplitter()
        try:
            async for delta in self._chat.stream(
                [self._system, Message("user", transcript)],
                lambda: timer.mark(Stage.REQUEST_SENT),
            ):
                if not delta:
                    continue
                timer.mark(Stage.FIRST_TOKEN)
                reply.append(delta)
                for sentence in splitter.feed(delta):
                    await self._speak(timer, sentence, pcm)
            rest = splitter.flush()
            if rest is not None:
                await self._speak(timer, rest, pcm)
        except SpokenError as exc:
            log.warning("turn failed: %s", exc)
            spoken: list[bytes] = []
            await self._speak(timer, exc.spoken, spoken)
            return TurnResult(
                Outcome.ERROR, self._audio(spoken), timer.times(), transcript, "", exc
            )
        return TurnResult(
            Outcome.ANSWERED, self._audio(pcm), timer.times(), transcript, "".join(reply)
        )

    async def _scripted(
        self, timer: StageTimer, outcome: Outcome, text: str, transcript: str
    ) -> TurnResult:
        pcm: list[bytes] = []
        await self._speak(timer, text, pcm)
        return TurnResult(outcome, self._audio(pcm), timer.times(), transcript, text)

    async def _speak(self, timer: StageTimer, sentence: str, out: list[bytes]) -> None:
        timer.mark(Stage.FIRST_SENTENCE)
        async for chunk in self._tts.synthesize(sentence):
            if chunk:
                timer.mark(Stage.FIRST_AUDIO_BYTE)
                out.append(chunk)

    def _audio(self, chunks: list[bytes]) -> Audio:
        return Audio(b"".join(chunks), self._tts.sample_rate)
