# Licenses

Every runtime dependency, development tool, model weight and voice used here, with its license
and source. `tests/test_repo_rules.py` fails if a package in `uv.lock` is missing from the
tables below, or if a model in `models.toml` is missing from this page.

Checked 2026-10-26 from each package's installed metadata (`importlib.metadata`), PyPI, and the
model repositories on Hugging Face.

## This repository: GPL-3.0-or-later

The text-to-speech engine, `piper-tts` 1.8.0, is GPL-3.0-or-later. It is imported into the
same Python process (`src/voice_agent/engines/piper.py`). A program that links GPL code that
way is a work based on it, so anyone distributing the combined program must distribute it
under the GPL. Rather than ship MIT code that can only be distributed under GPL terms anyway,
the repository is licensed **GPL-3.0-or-later** (`LICENSE`, `pyproject.toml`). That is the
reasoning behind the choice; it is not legal advice.

Text to speech sits behind the `TextToSpeech` interface (`src/voice_agent/interfaces.py`), and
Piper is imported by `engines/piper.py` only (an architecture test checks it). Another engine
can replace it without touching the rest.

The last MIT release of Piper (`piper-tts` 1.2.0, the archived `rhasspy/piper`) depends on
`piper-phonemize`, which has no Windows wheels, so it cannot be installed on the development
machine.

## Python packages (from `uv.lock`)

Runtime packages are installed by `uv sync`; dev packages are only used for checks.

| Package | Version | License | Use |
|---|---|---|---|
| `piper-tts` | 1.8.0 | GPL-3.0-or-later | runtime: text to speech (bundles espeak-ng and its data, GPL-3.0-or-later) |
| `faster-whisper` | 1.2.1 | MIT | runtime: speech to text |
| `ctranslate2` | 4.8.4 | MIT | runtime: Whisper inference (see bundled libraries below) |
| `av` | 16.0.1 | BSD-3-Clause | runtime: audio decoding for faster-whisper (bundles FFmpeg, see below); pinned below 19 because faster-whisper 1.2.1 passes an argument av 19 removed |
| `onnxruntime` | 1.31.1 | MIT | runtime: Piper and faster-whisper's VAD model |
| `httpx` | 0.28.1 | BSD-3-Clause | runtime: the gateway client and the model fetcher |
| `httpcore` | 1.0.9 | BSD-3-Clause | runtime, through httpx |
| `h11` | 0.16.0 | MIT | runtime, through httpcore |
| `anyio` | 4.15.1 | MIT | runtime, through httpx |
| `idna` | 3.20 | BSD-3-Clause | runtime, through httpx |
| `certifi` | 2026.10.23 | MPL-2.0 | runtime, through httpx |
| `numpy` | 2.5.4 (Python 3.12+), 2.4.6 (Python 3.11) | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | runtime, through ctranslate2 and onnxruntime |
| `tokenizers` | 0.23.3 | Apache-2.0 | runtime, through faster-whisper |
| `huggingface-hub` | 2.3.0 | Apache-2.0 | runtime, through faster-whisper (models load from `models/` with `local_files_only`; it downloads nothing here) |
| `hf-xet` | 1.7.0 | Apache-2.0 | runtime, through huggingface-hub |
| `httpx2` | 2.16.0 | BSD-3-Clause | runtime, through huggingface-hub |
| `httpcore2` | 2.16.0 | BSD-3-Clause | runtime, through httpx2 |
| `httpx2-jsfetch` | 1.0 | BSD-3-Clause | locked for Emscripten only; never installed here |
| `truststore` | 0.10.5 | MIT | runtime, through httpx2 |
| `click` | 8.5.0 | BSD-3-Clause | runtime, through huggingface-hub |
| `filelock` | 4.2.4 | MIT | runtime, through huggingface-hub |
| `fsspec` | 2026.9.0 | BSD-3-Clause | runtime, through huggingface-hub |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | runtime, through huggingface-hub and onnxruntime |
| `pyyaml` | 6.0.3 | MIT | runtime, through ctranslate2 |
| `tqdm` | 4.70.1 | MPL-2.0 AND MIT | runtime, through faster-whisper |
| `typing-extensions` | 4.16.0 | PSF-2.0 | runtime, through several |
| `flatbuffers` | 25.12.19 | Apache-2.0 | runtime, through onnxruntime |
| `protobuf` | 7.36.2 | BSD-3-Clause | runtime, through onnxruntime |
| `pathvalidate` | 3.3.1 | MIT | runtime, through piper-tts |
| `colorama` | 0.4.6 | BSD-3-Clause | runtime on Windows, through click and tqdm; dev, through pytest |
| `mypy` | 2.4.0 | MIT | dev |
| `mypy-extensions` | 1.1.0 | MIT | dev |
| `ast-serialize` | 0.13.1 | MIT | dev, through mypy |
| `librt` | 0.16.0 | MIT | dev, through mypy |
| `pathspec` | 1.1.1 | MPL-2.0 | dev, through mypy |
| `pytest` | 9.1.1 | MIT | dev |
| `pytest-asyncio` | 1.4.1 | Apache-2.0 | dev |
| `iniconfig` | 2.3.1 | MIT | dev, through pytest |
| `pluggy` | 1.7.0 | MIT | dev, through pytest |
| `pygments` | 2.21.0 | BSD-2-Clause | dev, through pytest |
| `ruff` | 0.17.2 | MIT | dev |

## Native libraries bundled inside those wheels

Not separate packages, but shipped inside the wheels above (Windows wheels, as installed on the
development machine):

- **`ctranslate2`** bundles NVIDIA **cuDNN 9** (`cudnn64_9.dll`), under NVIDIA's cuDNN
  license agreement: proprietary, redistributable, **not open source**. It also bundles the
  Intel OpenMP runtime (`libiomp5md.dll`), under Intel's license. Both come with the
  `ctranslate2` wheel whether or not a GPU is used.
- **`av`** bundles FFmpeg's libraries together with x264 and x265 (`libx264-*.dll`,
  `libx265-*.dll`), which are GPL, plus libvpx, dav1d, SVT-AV1, opus and others under
  permissive licenses. The FFmpeg build that includes them is distributed under the GPL.
  This is compatible with the GPL licence of this repository.
- **`piper-tts`** bundles espeak-ng (`espeakbridge`) and its data, GPL-3.0-or-later.
- **`onnxruntime`** ships its own DLLs under MIT.

## Evaluated and declined: Whisper on the GPU (NVIDIA cuBLAS 12)

`ctranslate2` needs CUDA's **cuBLAS 12** (`cublas64_12.dll`) to run Whisper on an NVIDIA GPU. It
is not bundled and **this repository does not install, pin, require or redistribute it**:
Whisper runs on the CPU. Decided 2026-10-27, in the review of PR #2.

What was evaluated (from PyPI's JSON API and the wheels' own `METADATA` and `License.txt`; nothing
was installed):

| Package | Version | Windows wheel | SHA-256 | License |
|---|---|---|---|---|
| `nvidia-cublas-cu12` | 12.9.2.10 | `py3-none-win_amd64`, 553,162,896 bytes, uploaded 2026-04-08 | `623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661` | `LicenseRef-NVIDIA-Proprietary` (NVIDIA CUDA EULA) |
| `nvidia-cuda-nvrtc-cu12` (required by the first) | 12.9.86 | `py3-none-win_amd64`, 76,408,187 bytes, uploaded 2025-06-05 | `72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349` | the same EULA |

Both are published by the PyPI organization `nvidia` (author "Nvidia CUDA Installer Team",
project URL https://developer.nvidia.com/cuda-zone). They are proprietary and not open source.

Why it was declined: two limitations in that agreement ("License Agreement for NVIDIA Software
Development Kits", section 1.2), quoted from the wheel's `License.txt`:

> 5. You may not use the SDK in any manner that would cause it to become subject to an open
> source software license. As examples, licenses that require as a condition of use,
> modification, and/or distribution that the SDK be:
>
> a. Disclosed or distributed in source code form;
>
> b. Licensed for the purpose of making derivative works; or
>
> c. Redistributable at no charge.

> 6. Unless you have an agreement with NVIDIA for this purpose, you may not use the SDK with any
> system or application where the use or failure of the system or application can reasonably be
> expected to threaten or result in personal injury, death, or catastrophic loss. Examples
> include use in avionics, navigation, military, medical, life support or other life critical
> applications. NVIDIA does not design, test or manufacture the SDK for these critical uses and
> NVIDIA shall not be liable to you or any third party, in whole or in part, for any claims or
> damages arising from such uses.

This repository is GPL-3.0-or-later and loads GPL code (Piper, espeak-ng) in the same process
as Whisper (clause 5), and its subject is a clinic's phone line with an emergency path, even
though the clinic is a mock (clause 6). This is a reading of the text, not legal advice.

The CLI still accepts `--device cuda`; it works only where someone has installed cuBLAS 12
themselves, under their own acceptance of NVIDIA's terms. No measurement in this repository uses
it.

## Models (pinned in `models.toml`, fetched by `scripts/fetch_models.py`)

Each is fetched over HTTPS from the official Hugging Face repository at the pinned commit
into the git-ignored `models/`. Each file is checked against the published SHA-256 if it is
an LFS file, or against the published git blob id if it is a small file with no published
SHA-256. Either way, its SHA-256 is recorded below.

### `Systran/faster-whisper-small`

- Source: https://huggingface.co/Systran/faster-whisper-small
- Revision: `536b0662742c02347bc0e980a01041f333bce120`
- License: **MIT** (the conversion). Model card (`README.md` at that revision), quoted:

  > ```
  > license: mit
  > library_name: ctranslate2
  > ```
  > This repository contains the conversion of
  > [openai/whisper-small](https://huggingface.co/openai/whisper-small) to the
  > [CTranslate2](https://github.com/OpenNMT/CTranslate2) model format.

- Upstream weights: `openai/whisper-small`, whose Hugging Face model card declares
  `license: apache-2.0`. The converted weights are a derivative of them, so the Apache-2.0
  terms apply to them as well.

| File | Bytes | SHA-256 | Checked by |
|---|---|---|---|
| `model.bin` | 483546902 | `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671` | published SHA-256 |
| `config.json` | 2370 | `b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828` | git blob `e5047537059bd8f182d9ca64c470201585015187` |
| `tokenizer.json` | 2203239 | `fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab` | git blob `7818adb6de9fa3064d3ff81226fdd675be1f6344` |
| `vocabulary.txt` | 459861 | `34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913` | git blob `c9074644d9d1205686f16d411564729461324b75` |
| `README.md` | 1998 | `329373481008c7c38654aff8ecdcf0163c211557cc7ba8e2ef6f2f84b4f75ec8` | git blob `16511f6106ead2fbc3a1480957a217c2661a5a98` |

### Piper voice `en_US-ljspeech-medium` (`rhasspy/piper-voices`)

- Source: https://huggingface.co/rhasspy/piper-voices, folder `en/en_US/ljspeech/medium/`
- Revision: `5041a7a49ae5b3a0f30e6837769eb03fdbb231bd`
- License: **MIT** for the voice repository (its `README.md` front matter: `license: mit`).
  Training data: LJ Speech, **public domain**. The voice's `MODEL_CARD` at that revision,
  quoted:

  > ## Dataset
  >
  > * URL: https://keithito.com/LJ-Speech-Dataset/
  > * License: public domain
  >
  > ## Training
  >
  > See: https://brycebeattie.com/files/tts/

- This voice was picked over the more common `lessac` voice because the Lessac training data
  (Blizzard 2013) has its own license. That license page could not be reached when this was
  checked.

| File | Bytes | SHA-256 | Checked by |
|---|---|---|---|
| `en_US-ljspeech-medium.onnx` | 63531379 | `6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22` | published SHA-256 |
| `en_US-ljspeech-medium.onnx.json` | 4972 | `141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860` | git blob `73ecdec4f6ab17a437936652dfe3a925bb19e098` |
| `MODEL_CARD` | 517 | `fbee1529c89d36b3fe76d7e9f3f832dce17f44900a52d76a9bda735654766b4d` | git blob `324d7470296a501e3c6396310f9b218fdbd7ed1e` |

## Language models

None are downloaded by this repository. The voice agent calls the inference gateway, which
serves Llama 3.2 1B, Llama 3.2 3B and Llama 3.1 8B through a local Ollama. Those models, and
their license (the Llama 3.2 and Llama 3.1 Community License Agreements), belong to the
gateway's setup, not to this repository.
