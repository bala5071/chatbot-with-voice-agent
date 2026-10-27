# 04: the demo script

`scripts/demo.py` runs five fixed calls through the real pipeline and the gateway, so the
paths can be seen working end to end: two questions the model answers, an emergency, a request
for medical advice, and near-silence.

**What was decided, and why.**

- **The calls are fixed and synthetic.** Piper speaks the four sentences; near-silence is a
  50 Hz tone at amplitude 30 of 32767, generated in code, because Piper cannot speak silence. No
  recording of a person is used (hard rule 6).
- **The caller WAVs go through a file**, written to a folder from `tempfile.mkdtemp` and read
  back with `read_wav`, so the demo uses the same input path as the CLI. The demo deletes that
  folder, which it created and recorded, and nothing else, in a `finally` (also on failure).
- **Nothing is kept by default** (hard rule 8). `--play` writes each reply into the temporary
  folder for the OS player (`winsound` on Windows, `afplay` on macOS, `aplay` on Linux).
  `--out DIR` is the only way to keep replies, and it keeps the transcript and reply text
  beside each WAV.
- **The warm-up decides whether to go on.** `Pipeline.warm_up` now returns the gateway error
  instead of only logging it. The demo stops on it with one sentence: unreachable, key refused,
  or the error's type, status and code. It never prints the gateway's message or the key. The
  CLI ignores the value, as before. A missing key stops the demo before any model loads.
- **The path is the pipeline's outcome**, printed with the expected one when they differ, and
  the exit is 1 then. The medical-advice call is expected to reach the model: no rule here
  scripts a refusal. The system prompt asks the model to stay a receptionist, which is not a
  guarantee. The demo shows what it says.
- **The timings are labelled single demo runs on one machine, not a benchmark.** The demo
  measures nothing: `docs/latency.md` is filled by `scripts/measure_latency.py`.
- **Whisper runs on the CPU**, with no `--device` option (GPU Whisper was declined,
  `docs/licenses.md`).
- `hardware()` moved from `scripts/measure_latency.py` to `voice_agent.machine`, so that both
  scripts can use it when run as files.

Tests (`tests/test_demo.py`) run the demo on the fakes and `FakeClock`. They check each path
and its exact stage times, that the emergency call never reaches the model, that the temporary
folder is deleted and nothing else, that files appear only with `--out`, playback, the
refusals, and that the key is never printed or logged.
