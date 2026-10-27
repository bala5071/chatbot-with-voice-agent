# Voice plan

A push-to-talk voice receptionist for a **mock** clinic. It calls the
[Multi-Model Inference Gateway](https://github.com/bala5071/Multi-Model-Inference-Gateway-Simulator)
over HTTP. This is a demo for synthetic data and is not HIPAA compliant. The rules it is built
under are in `CLAUDE.md`.

Status: **approved 2026-10-26**, with the answers in "Decisions (answered)" below.

## Step 1: scaffold and a push-to-talk loop with stage timing

Branch `voice/step-1-scaffold`, one draft PR against `main`.

### 1. Replace the chatbot

This repo holds the earlier multi-tenant chatbot (`backend/`, `frontend/`, `config/`,
`scripts/demo.ps1`, `docs/DEMO.md`, `docs/DESIGN.md`, `docs/img/chat.png`) and its CI. Its own
repo, `bala5071/inference-gateway-chat`, keeps the original. One ordinary commit removes those
files. The commit does not rewrite history, so `git log` keeps them. `.gitattributes` stays.
`LICENSE` becomes GPL-3.0 (decision 1).

Before any push, the whole history (every blob, path and commit message on every ref) is
scanned for secrets, with a planted control that must be found. If anything is found, work
stops and the repo starts again with fresh history after the secret is rotated.

### 2. Layout

```
pyproject.toml            uv project, ruff (with the banned-api rules), mypy strict, pytest
uv.lock
src/voice_agent/          the modules listed in CLAUDE.md
src/voice_agent/clinic.toml   mock clinic facts (visibly fake names, a 555 number); TOML
                          because tomllib is in the standard library, so no YAML dependency
tests/                    fakes and FakeClock only; real_models tests skipped by default
scripts/check_characters.py   tracked code is printable ASCII (as in the gateway)
scripts/gpu_budget.py     Whisper + the voice tier on the GPU together
docs/licenses.md          every dependency, weight and voice with its license and source
docs/01-push-to-talk.md   the design note for this step
docs/latency.md           the latency table, empty until a measured run fills it
.github/workflows/ci.yml  ruff, format check, mypy, pytest, check_characters; 3.11 and 3.12
.gitignore                .env*, *.env, audio (*.wav, *.mp3, *.flac, *.ogg, *.m4a),
                          model files (*.onnx, *.onnx.json, *.bin, *.gguf, models/)
README.md                 what it is, what it is not (synthetic data, no medical advice, not
                          HIPAA compliant), how to run it
```

### 3. GatewayClient

- `POST {GATEWAY_URL}/v1/chat/completions` with `stream: true` and
  `stream_options.include_usage`. It parses the gateway's OpenAI-shaped server-sent events
  (`chat.completion.chunk`, then `data: [DONE]`). `GATEWAY_URL` defaults to
  `http://127.0.0.1:8000`.
- `GATEWAY_API_KEY` is read once into `Secret`. It is redacted in `repr`/`str`/`format`, and
  `reveal()` is called in one function, the one that builds the `Authorization: Bearer` header.
  An AST test checks that. httpx's own logging of request headers is never enabled.
- It sends `model` (the voice tier's model name, configurable). The gateway answers 403
  `model_not_in_plan` if the key's plan does not allow it.
- Failures map to `SpokenError` subclasses. Each carries a fixed sentence the TTS can say, plus
  the status and the gateway's error code for logs. The gateway's message text is never spoken
  or logged, because it might echo input.

| Gateway result                           | Error type          | Spoken (fixed text)                                               |
|------------------------------------------|---------------------|-------------------------------------------------------------------|
| 401 (`api_key_required`, `invalid_api_key`) | `NotAuthorized`  | "I can't reach the clinic system right now. Please call back later." |
| 403 (`model_not_in_plan`, others)        | `NotPermitted`      | "I'm not able to help with that from here. Please call back later." |
| 429 (`rate_limited`, `budget_exhausted`, `queue_full`) | `Busy` (keeps `Retry-After`) | "We're very busy right now. Please try again in a minute." |
| 5xx (500, 502, 503, 504)                 | `Unavailable`       | "The clinic system is having trouble. Please call back later."    |
| connect/read timeout, first-token or total timeout on the injected clock | `TimedOut` | "Sorry, that took too long. Please try again." |
| connection refused                       | `Unavailable`       | (as for 5xx)                                                      |
| error inside the stream after output started | mapped by its code as above; the partial reply is dropped, not spoken |   |
| other 4xx (404, 422)                     | `Misconfigured`     | "Something is set up wrong on our side. Please call back later."  |

The fixed texts above are drafts and can be changed at review.

### 4. CLI: one push-to-talk turn

`python -m voice_agent --in in.wav --out out.wav [--whisper-size small] [--device cuda|cpu]
[--compute-type int8_float16|int8|float16|float32] [--voice en_US-ljspeech-medium]
[--timings]`

1. Warm up: load Whisper and Piper, transcribe one second of Piper-generated audio, synthesize
   one sentence, and send one short gateway request so Ollama has the model loaded. Warm-up
   runs on a separate `StageTimer` that is thrown away.
2. Read `in.wav` (16 kHz mono after resampling) and transcribe it with faster-whisper.
3. `safety.py` checks the transcript. If it matches the emergency script, the fixed emergency
   text is spoken, the model is never called, and the turn ends.
4. Stream the reply from the gateway. A system prompt built from `clinic.yaml` keeps it to
   receptionist tasks: hours, address, booking requests, transfer to staff.
5. `sentences.py` cuts the stream into sentences. Each sentence goes to Piper as soon as it is
   complete, and audio chunks are appended to the output.
6. Write `out.wav`, the only file the turn writes. `--timings` prints the six stage times.
   Transcript and reply text are printed only with `--show-text`, never logged.

### 5. Stage timestamps (`StageTimer`, injected clock)

Each stage is a millisecond offset from `speech_end`.

| Stage                  | Recorded when                                                          |
|------------------------|------------------------------------------------------------------------|
| `speech_end`           | the complete utterance is handed to STT (push-to-talk release; for a file, once it is read) |
| `transcript_ready`     | STT returns the final text                                             |
| `request_sent`         | just before the POST is written                                        |
| `first_token`          | the first non-empty content delta arrives                              |
| `first_sentence`       | the sentence splitter emits its first sentence                         |
| `first_audio_byte`     | TTS yields the first audio chunk of the first sentence                 |

In file mode nobody is speaking, so `speech_end` is a convention, and the latency doc says so.
On the emergency path the gateway stages are recorded as absent, never as zero.

### 6. scripts/gpu_budget.py

1. Before loading anything, record GPU memory already in use (by other processes) with
   `nvidia-smi`, and which models Ollama already has loaded (`/api/ps`).
2. Load Whisper with the chosen size and compute type on CUDA, and run one transcription of
   synthetic audio so its working buffers are allocated.
3. For each tier in turn (economy, standard, premium), load it in Ollama with
   `POST http://127.0.0.1:11434/api/generate` and a short prompt, with Whisper still loaded.
   This talks to Ollama directly, not through the gateway, because it measures memory, not the
   gateway. Peak memory is sampled throughout by `nvidia-smi -lms 100` running beside the
   load. `/api/ps` gives how much of the model Ollama put in VRAM. The script then unloads
   only the model it loaded (`keep_alive: 0`).
4. A tier fits if Ollama put all of it in VRAM and the peak stays below total minus a headroom
   (default 512 MiB). The script prints which tiers fit and which do not, and exits non-zero
   with a clear message if the chosen voice tier does not fit.
5. It prints the hardware and the numbers as JSON, labelled "one machine, one run", so the
   docs can quote them with the command and commit.

**Voice tier on this machine.** The GPU is an NVIDIA GeForce RTX 4060 Laptop GPU with 8188 MiB
(read with `nvidia-smi`, 2026-10-26). Ollama already has `llama3.2:1b`, `llama3.2:3b` and
`llama3.1:8b`, so the LLM needs no download. Which tier is used for voice will be decided by
`gpu_budget.py`'s output, not guessed. I expect standard (`llama3.2:3b`), because the gateway's
calibration already marked premium as hardware-limited on this laptop. The PR will report
whatever the script measured, including a failure.

### 7. Latency table (`docs/latency.md`)

The table holds one row per stage, with the min to max over three runs. It also records the
hardware (GPU, driver, CPU, RAM, OS), the model sizes, compute type, voice, tier, the command
and the commit. It is labelled "one machine". It stays empty in the PR unless the measured run
below happens.

The measured run needs (a) the models downloaded (see below), (b) the gateway running with its
real Ollama backend, and (c) a `GATEWAY_API_KEY` for an application whose plan allows the voice
tier. (c) is a dedicated short-lived key (economy and standard only, small budget) that you
export as `GATEWAY_API_KEY` yourself. It is never printed. Until you say it is set, the table
stays empty.

### 8. Tests (fakes and FakeClock only)

- **Exact stage timings.** Fakes advance the `FakeClock` by scripted amounts (STT 300 ms,
  first token after 200 ms, ...). The test asserts every stage offset exactly, and checks that
  warm-up stages never appear in the result.
- **Error mapping.** An `httpx.MockTransport` gateway returns each status in the table. For a
  first-token timeout, the transport waits on the `FakeClock`. Each case asserts the error type,
  the spoken text, and that nothing from the gateway's message is in it.
- **Key never leaked.** A planted key goes through every client path: success, each error, a
  timeout, a repr of the client and config, and logging at DEBUG. The test scans captured logs,
  exception strings and tracebacks, reprs, and pytest's captured stdout/stderr. The **planted
  control** writes the key into one log record on purpose and asserts the scanner finds it, so
  a scanner that sees nothing fails the test.
- **No audio written unless asked.** A full turn with the fakes runs in an empty `tmp_path`
  working directory with `TMPDIR` pointed into it. Afterwards the only file is the requested
  `--out`. Run without `--out`, no file is written at all.
- **Emergencies.** Each scripted trigger phrase gives the fixed text and the fake chat client
  is never called. Ordinary receptionist phrases never trigger it.
- **Mutation checks** (break, show the failing tests, restore byte for byte, show green): the
  redaction in `Secret.__repr__`, the 401/403/429/5xx branches, the emergency short-circuit, and
  the "write only `--out`" rule.
- `real_models` tests (skipped in CI) run Whisper on Piper-generated audio and check the
  round-trip transcript.

## Decisions (answered 2026-10-26)

1. **Piper and the license.** The repo uses `piper-tts` 1.8.0 (GPL-3.0-or-later), imported only
   in `engines/piper.py`. Importing GPL code into the same process makes the combined program a
   work based on it, so anyone distributing it must do so under the GPL. Rather than ship MIT
   code that can only be distributed under GPL terms, **this repository is licensed
   GPL-3.0-or-later**. TTS stays behind the `TextToSpeech` interface, so another engine can
   replace Piper. This is the reasoning behind the choice, not legal advice.
2. **Downloads approved:** `Systran/faster-whisper-small` and `en_US-ljspeech-medium`. Each is
   pinned to an exact Hugging Face commit, fetched over HTTPS from the official repo only, and
   checked file by file. LFS files are checked against the published SHA-256, and small
   non-LFS files against the published git blob id, with their SHA-256 then recorded. Both go
   in `docs/licenses.md` with the model card's license text quoted, and they are stored in the
   git-ignored `models/`.
3. **CI installs the engine packages but no weights.** That way mypy and import checks cover
   `engines/`. If the wheels make CI too slow, they move to an optional group.
4. **Emergency script.** It is a fixed list of trigger phrases matched on the normalized
   transcript. On a match it says one fixed sentence: "If this is an emergency, hang up and
   call 911 now." The list is conservative and certainly incomplete, and the docs say so.
5. The CLI reads and writes WAV only. Push-to-talk from a microphone is not built in this step.

## Not built in step 1

Microphone capture and live push-to-talk, barge-in, telephony, multi-turn memory, appointment
booking against any system, a web UI, FastAPI, and Docker.
