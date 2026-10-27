# GPU budget: Whisper and a gateway tier on one GPU

Measured with `scripts/gpu_budget.py`. **One machine, one run.** These numbers say nothing about
any other GPU, driver or Ollama version.

- Command: `uv run python scripts/gpu_budget.py` (defaults: voice tier `standard`, headroom
  512 MiB, Whisper `faster-whisper-small` with compute type `int8_float16` on CUDA)
- Commit: `bcc8f7a017f039180abbd4382e767c0456024451`
- Date: 2026-10-27
- Hardware: NVIDIA GeForce RTX 4060 Laptop GPU, 8188 MiB, driver 592.82; CPU "Intel64 Family 6
  Model 170 Stepping 4, GenuineIntel"; Windows 11 10.0.26200; Python 3.12.10; Ollama 0.12.6
- Exit code: 1 (the voice tier was not shown to fit)

## Result

GPU memory in use before anything was loaded: 0 MiB. Ollama had no model loaded.

**Whisper did not load on CUDA**: `RuntimeError: Library cublas64_12.dll is not found or cannot
be loaded`. CTranslate2 needs the CUDA 12 cuBLAS runtime. This machine has CUDA 13.1, and the
copy of cuBLAS 12 that Ollama ships stays inside Ollama's folder. Because Whisper never ran on
the GPU, no tier could be measured *together with* Whisper, and so the script reports that no
tier fits. Each tier was still loaded and measured on its own:

| Tier     | Ollama model                  | Size (MiB) | In VRAM (MiB) | Peak used (MiB) | Fits with Whisper |
|----------|-------------------------------|-----------:|--------------:|----------------:|-------------------|
| economy  | `llama3.2:1b-instruct-q4_K_M` | 1672.8     | 1672.8        | 1524            | not measured      |
| standard | `llama3.2:3b`                 | 3156.8     | 3156.8        | 2944            | not measured      |
| premium  | `llama3.1:8b`                 | 5817.0     | 5817.0        | 5570            | not measured      |

"Size" and "In VRAM" come from Ollama's `/api/ps`. "Peak used" is the highest `nvidia-smi` sample
(every 100 ms) while that tier was loaded and generating. All three tiers fitted entirely in
VRAM when loaded alone.

## Voice tier

The voice tier is **standard** (`llama3.2:3b`, the default `VOICE_MODEL`), and **Whisper runs on
the CPU** (`--device cpu`, int8, the CLI's default). Measured alone, standard used 2944 MiB at
peak and fitted entirely in VRAM. With Whisper on the CPU, the GPU holds only the gateway's model.

This run does not show whether Whisper and standard fit on the GPU together. That needs the
cuBLAS 12 runtime, which is proprietary NVIDIA software and would be a new dependency, so it has
not been installed. Premium is not chosen: on this laptop the gateway's own calibration already
marks it hardware-limited, and this run gives no evidence either way about it sharing the GPU
with Whisper.

## Full output

```json
{
  "label": "one machine, one run",
  "command": "uv run python scripts/gpu_budget.py",
  "hardware": {
    "gpu": "NVIDIA GeForce RTX 4060 Laptop GPU",
    "driver": "592.82",
    "total_mib": 8188,
    "cpu": "Intel64 Family 6 Model 170 Stepping 4, GenuineIntel",
    "os": "Windows-11-10.0.26200-SP0",
    "python": "3.12.10"
  },
  "in_use_before_mib": 0,
  "ollama_loaded_before": [],
  "whisper": {
    "loaded": false,
    "error": "RuntimeError: Library cublas64_12.dll is not found or cannot be loaded"
  },
  "headroom_mib": 512,
  "voice_tier": "standard",
  "tiers": [
    {
      "tier": "economy",
      "ollama_model": "llama3.2:1b-instruct-q4_K_M",
      "preloaded": false,
      "size_mib": 1672.8,
      "vram_mib": 1672.8,
      "fully_in_vram": true,
      "used_after_load_mib": 1524,
      "peak_together_mib": 1524,
      "fits": false,
      "note": "Whisper not on the GPU; the tier was measured alone"
    },
    {
      "tier": "standard",
      "ollama_model": "llama3.2:3b",
      "preloaded": false,
      "size_mib": 3156.8,
      "vram_mib": 3156.8,
      "fully_in_vram": true,
      "used_after_load_mib": 2944,
      "peak_together_mib": 2944,
      "fits": false,
      "note": "Whisper not on the GPU; the tier was measured alone"
    },
    {
      "tier": "premium",
      "ollama_model": "llama3.1:8b",
      "preloaded": false,
      "size_mib": 5817.0,
      "vram_mib": 5817.0,
      "fully_in_vram": true,
      "used_after_load_mib": 5570,
      "peak_together_mib": 5570,
      "fits": false,
      "note": "Whisper not on the GPU; the tier was measured alone"
    }
  ]
}
```
