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

- **Emergencies are scripted, not generated.** If the transcript matches the emergency
  phrases, the agent says "If this is an emergency, hang up and call 911 now." and never asks
  the model. Matching is recall-first: it forgives how a transcript spells things (`cant`,
  `9-1-1`) and accepts false alarms (`docs/02-emergency-recall.md`). It reads only the
  transcript, so an emergency that speech-to-text mishears is missed. This is a known gap
  (`docs/threat-model.md`): it is a demo safeguard, not a triage system.
- **Requests for medical advice are scripted too.** If the transcript asks about a dose, a
  medicine, a diagnosis or a treatment, the agent says "I'm sorry, I can't give medical
  advice on this line, but one of our clinicians can. Would you like to book an appointment,
  or have a clinician call you back?" and never asks the model
  (`docs/05-medical-advice-guard.md`). The check is keyword-based and recall-first: it accepts
  false alarms and will miss unusual phrasing. When it misses, the model is told to answer
  only receptionist questions, and an instruction to a model is not a guarantee.
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
Piper), never a recording of a real person. Options: `--compute-type`, `--whisper-dir`,
`--voice`, `--show-text`. `VOICE_MODEL` picks the gateway model id (default `standard`).

**Whisper runs on the CPU.** Running it on an NVIDIA GPU needs NVIDIA's cuBLAS 12, which this
repository does not install: its license forbids use that would subject it to an open-source
license such as this repository's GPL, and excludes medical uses without an agreement with
NVIDIA (`docs/licenses.md` quotes both clauses). This is not legal advice. `--device cuda` is
left for anyone who installs cuBLAS 12 themselves; nothing here is measured with it.

## Run the demo

```sh
export GATEWAY_API_KEY=...                   # yourself; never printed
uv run python scripts/demo.py                # add --play to hear the replies
```

Five fixed calls to the mock clinic, through the real pipeline and the gateway: opening hours,
the services, an emergency ("My father is having chest pain and can't breathe."), a request for
medical advice ("What dose of ibuprofen should I take?") and near-silence. The callers' speech
is synthesized by Piper (near-silence is a quiet generated tone) into a temporary folder, and
that folder is deleted at the end.

Per call it prints the transcript, the reply, which path ran (the model, or the scripted
emergency, medical-advice or no-speech answer) and the stage times; then the min and max of
each stage, the hardware and the tier asked for. Neither the emergency call nor the
medical-advice call reaches the model. Every stage is warmed up first and the warm-up is not
counted. These are single demo runs on one machine, not a benchmark.

`--play` plays each reply with the OS player; `--out DIR` writes each reply WAV and its
transcript there. Without them nothing is written. A missing key, or a gateway that cannot be
reached or refuses the key, stops the demo with a message (exit 2). Exit 1 means a call took a
different path than expected; the output says which.

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
