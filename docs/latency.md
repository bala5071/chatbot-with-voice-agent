# Latency: one push-to-talk turn

**Not measured yet.** The table stays empty until a measured run fills it. A run needs the
gateway running in front of Ollama and a `GATEWAY_API_KEY` exported in the terminal (a
dedicated short-lived key, economy and standard tiers only). Nothing in this table may be
estimated, copied from elsewhere, or taken from the fakes.

How to fill it:

```sh
uv run python scripts/measure_latency.py --runs 3
```

The script warms up every stage once (that run is not counted), then runs three turns on the
same synthetic question ("Hi, what time do you open on Saturday?", spoken by Piper). It prints
each run and the min and max of each stage. Copy the ranges below with the command, the commit
and the hardware it printed.

Each stage is milliseconds after `speech_end` (`src/voice_agent/timing.py`). In file mode
nobody is speaking, so `speech_end` is the moment the complete utterance is handed to speech
to text. It is a convention, not the end of a real person's speech.

## Result

One machine. Three runs. Ranges are min to max.

| Stage | Range (ms) |
|---|---|
| `transcript_ready` | |
| `request_sent` | |
| `first_token` | |
| `first_sentence` | |
| `first_audio_byte` | |

- Command:
- Commit:
- Date:
- Hardware (CPU, GPU, RAM, OS):
- Whisper (size, device, compute type):
- Voice:
- Gateway model (tier) and its Ollama model:
