# voice-agent-receptionist

A self-hosted, push-to-talk voice receptionist for a **mock** clinic. It transcribes a
caller's question with faster-whisper, asks a language model for the answer through the
[Multi-Model Inference Gateway](https://github.com/bala5071/Multi-Model-Inference-Gateway-Simulator)
over HTTP, and speaks the reply with Piper. It runs on one machine and calls no hosted service.

> **A demo for synthetic data only. It is not HIPAA compliant.** It is not a medical device and
> gives no medical advice. The clinic, its staff, its hours and every caller are made up. Do not
> use it with real patients or real patient data.

## What it does now (step 1)

One turn from a WAV file: audio in, transcript, a reply streamed from the gateway, spoken
audio out. It records six stage times on an injected clock (`speech_end`,
`transcript_ready`, `request_sent`, `first_token`, `first_sentence`, `first_audio_byte`).
Microphone capture, telephony and multi-turn calls are not built yet. See
`docs/voice-plan.md`.

- **Emergencies are scripted, not generated.** If the transcript matches a fixed list of
  emergency phrases, the agent says "If this is an emergency, hang up and call 911 now." and
  never asks the model. The list is broad but certainly incomplete: this is a demo safeguard,
  not a triage system.
- **No medical advice.** The model is told to answer only receptionist questions. An
  instruction to a model is not a guarantee.
- **Nothing is stored by default.** The only file written is the `--out` file you ask for. The
  transcript and reply are printed only with `--show-text` and never logged.
- **Failures are spoken in fixed words.** For example, a 429 from the gateway becomes "We're
  very busy right now. Please try again in a minute." The gateway's own message is never
  spoken or logged.

## Setup

Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run python scripts/fetch_models.py   # about 550 MB, pinned and hash-checked
```

`fetch_models.py` downloads faster-whisper `small` and the Piper voice `en_US-ljspeech-medium`
from Hugging Face at pinned commits into `models/` (git-ignored). It refuses any file whose
hash differs. Sources, licenses and hashes are in `docs/licenses.md`.

You also need the gateway running in front of Ollama (see the gateway's README), and an API
key for a gateway application whose plan allows the voice tier.

## Run one turn

```sh
export GATEWAY_URL=http://127.0.0.1:8000     # the default
export GATEWAY_API_KEY=...                   # from the environment only; never in a file
uv run python -m voice_agent --in question.wav --out reply.wav --timings
```

The input must be a mono 16-bit WAV file. Use synthetic speech (for example, generated with
Piper), never a recording of a real person. Options: `--device cuda` (Whisper on the GPU),
`--compute-type`, `--whisper-dir`, `--voice`, `--show-text`. `VOICE_MODEL` picks the gateway
model id (default `standard`).

## Measurements

- `docs/latency.md`: the stage-time table. **Empty until a measured run fills it.**
- `docs/gpu-budget.md`: whether Whisper and each gateway tier fit on this machine's GPU
  together (`scripts/gpu_budget.py`). One machine, one run.

## Development

```sh
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                                # fakes only: no models, no network
uv run python scripts/check_characters.py
VOICE_REAL_MODELS=1 uv run pytest -m real_models   # with the models downloaded
```

The rules this repository is built under are in `CLAUDE.md`.

## License

GPL-3.0-or-later (`LICENSE`). The text-to-speech engine, `piper-tts`, is GPL-3.0-or-later and
runs in the same process. Anyone distributing this program therefore has to do so under the
GPL, and the repository is licensed to match. Text to speech sits behind an interface, so
another engine could replace Piper. This is the reasoning, not legal advice. Every dependency,
model and voice is listed with its license in `docs/licenses.md`.
