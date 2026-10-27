# 01: Push-to-talk loop with stage timing

What was decided in step 1, and why. The plan is `docs/voice-plan.md`.

**One turn, three interfaces.** `Pipeline.turn` takes audio and returns spoken audio. It talks
only to `SpeechToText`, `ChatClient` and `TextToSpeech` (`interfaces.py`). The real
implementations (`engines/faster_whisper.py`, `engines/piper.py`, `gateway_client.py`) are
built only in `cli.py`. Each interface has a deterministic fake in `fakes.py`, so every test
runs without a model or a network. An AST test keeps logic modules from importing an engine
or httpx.

**Time is injected.** Every stage time comes from the `Clock`. In tests that is `FakeClock`,
which moves only when the fakes advance it, so the test of a turn asserts exact numbers
(`tests/test_pipeline.py`). Timeouts sleep on the same clock: the timeout tests advance it
past the deadline instead of waiting. Ruff's banned-api rule refuses `time.*`,
`asyncio.sleep` and `datetime.now` outside `clock.py`.

**Stages.** `speech_end`, `transcript_ready`, `request_sent` (just before the POST is written),
`first_token` (the first non-empty delta), `first_sentence` (the first sentence handed to TTS),
and `first_audio_byte`. A stage that did not happen is `None`, never 0. On the emergency
path, for example, there is no request.

**Sentences go to TTS as soon as they are complete.** That way `first_audio_byte` follows
the first sentence, not the whole reply. The splitter waits for the white space after a full
stop, so it does not cut "8 a.m." or "Dr. Sample". In this step synthesis runs inline: the
stream waits while a sentence is synthesized. Overlapping them is left for later.

**Warm-up never counts.** `warm_up()` synthesizes a sentence, transcribes it, and sends one
short request, so the models are loaded and Ollama has the tier in memory. Its timer is
thrown away. A test checks that a warmed-up turn reports the same times as a cold one on the
fakes.

**Failures are spoken, in fixed words.** Every failure maps to a `SpokenError` with fixed text:
401, 403, 429, 5xx, other 4xx, transport errors, httpx timeouts, the clock's first-token
timeout and total timeout, and errors inside the stream. Before output, the mapping is by
status. Inside the stream, the status is 200, so it is by the gateway's error code. The
gateway's message is never kept, because it could echo input. A partial reply is dropped
and only the error sentence is in the output.

**The key.** It lives in a `Secret` (redacted `repr`, `str` and `format`; it cannot be pickled
or changed). `reveal()` is called in one function, which builds the header; an AST test pins
that. The httpx client follows no redirects and ignores proxy settings from the environment.
Plain `http` is refused unless the gateway is on loopback. `tests/test_leaks.py` puts a planted
key through every client path and scans logs (DEBUG, httpx included), errors, tracebacks,
reprs, stdout and stderr. A planted control proves the scan finds a leak when there is one.

**Nothing stored by default.** The CLI writes the `--out` file and nothing else. The transcript
and reply are printed only with `--show-text` and never logged. A test runs the CLI in an
empty directory with the temp-dir variables pointed inside it, and checks which files exist
afterwards.

**Emergencies are scripted.** `safety.py` checks the transcript against a fixed phrase list
before any model call. On a match the agent says one fixed sentence and the model is never
asked (a test checks the fake chat client received no call). The list is broad and certainly
incomplete; step 2 made it recall-first (`docs/02-emergency-recall.md`). The system prompt also tells the model to stay a receptionist and give no medical
advice, but an instruction to a model is not a guarantee.

**Models.** The models are faster-whisper `small` (CPU int8 by default, `--device cuda` to opt
in) and Piper `en_US-ljspeech-medium`. Both are pinned by commit and hash in `models.toml` and
fetched by `scripts/fetch_models.py` (`docs/licenses.md`). `av` is pinned to 16.0.1 because
faster-whisper 1.2.1 calls `av.open` with an argument that av 19 removed.

**GPU.** Whisper runs on the CPU. `ctranslate2` needs NVIDIA's cuBLAS 12 to run it on CUDA,
and adding cuBLAS 12 was evaluated and declined in step 2 because of its license
(`docs/licenses.md`).
