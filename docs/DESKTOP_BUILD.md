# Local macOS desktop build

This procedure builds the unsigned, local-only `Hebrew Live.app`. It does not
publish, notarize, add a Developer ID signature, or enable automatic updates.

## Qualified host

The procedure below was exercised on exactly this machine:

- MacBook Air with Apple M5;
- 16 GiB unified memory;
- macOS 27.0;
- native `arm64` execution;
- Python 3.12.14, PyInstaller 6.22.3;
- Node.js 24, Electron 44.4.3, electron-builder 26.15.3.

This is a tested reference, not a proven minimum. A clean installation on a
different Mac has not been tested. The native libraries in this build require
macOS 27.0 or later; the preflight blocks older systems, Intel/Rosetta execution,
an unavailable Metal device, and insufficient target-disk space. Less than
16 GiB produces a warning and still allows an explicit continuation.

## Reproducible build

Run all commands from the repository root unless a command changes directory.
GigaAM-He and Silero are copied into the app from hash-verified local build
assets. MiLMMT is downloaded during first preparation or repair. The app also
packages the small `mlx-whisper` runtime; its 1,613,977,880-byte ivrit.ai model
is downloaded only after the user selects Accurate recognition. The model source,
revision, file sizes, and hashes are in `src/hebrew_live/desktop_accurate_model.json`.

```sh
uv sync --frozen --group desktop-build

cd experiments/publication-ui-preview
npm ci
npm test
npm run build
cd ../..

.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/build_macos_engine_app.py --skip-web-build \
  --bundle-models models

cd desktop/electron
npm ci
npm test
npm run dist:mac
# For a local unsigned DMG with English and Russian license prompts:
npm run dist:dmg
cd ../..
```

### Bundled model build assets

The fast path accepts Hebrew source audio only. Its ONNX file, mel filters and
vocabulary are pinned by `src/hebrew_live/fast_asr_manifest.json`. The original
[GigaAM-He checkpoint](https://huggingface.co/asfberlin/fast-hebrew-asr/tree/main)
does not include ONNX; export it once with `scripts/export_fast_hebrew_onnx.py`
using the pinned GigaAM source revision and a separate build environment with
PyTorch, torchaudio and ONNX. The script checks the checkpoint and output hashes.
Place those three files in the ignored `models/fast-asr` directory and Silero
ONNX at `models/silero.onnx`. MiLMMT is not a build asset; the installed app
downloads it from its pinned Hugging Face revision during first preparation or
repair. The exact revisions, sizes, and SHA-256 values are in
`src/hebrew_live/desktop_models.json`. The engine command verifies only the
four files entering the bundle and fails if one is missing or different.

Do not commit the model files. GigaAM-He uses two CPU threads; MiLMMT uses
Metal. At first launch the app verifies its included files, downloads missing
MiLMMT files, copies Silero to external model storage, then warms the models.
The fast mode does not run Whisper. Accurate mode uses ivrit.ai Whisper instead
of GigaAM-He, after its separate pinned download and verification. Switching
is allowed only before recording or after a finished recording, so both models
never compete for the live inference queue. The fast model's CTC word times
are approximate and its unpunctuated drafts may change
as more audio arrives.

Outputs:

- stage-one engine app: `dist/desktop-engine/Hebrew Live.app`;
- PyInstaller `onedir` embedded by Electron: `dist/desktop-engine/Hebrew Live`;
- final desktop app: `dist/electron/mac-arm64/Hebrew Live.app`.

The source application icon is `desktop/electron/assets/icon.png` (1024 by
1024 RGBA). Electron Builder converts it to the bundled `icon.icns` during the
macOS build.

The Electron build keeps the engine under `Contents/Resources/engine`, outside
ASAR. The renderer remains sandboxed, has context isolation enabled, has Node.js
disabled, and receives only the allowlisted preload commands. The engine binds
its HTTP UI to `127.0.0.1` and retains the random URL token and Host/Origin
checks. Controller messages on stdin/stdout use schema version 1; backend logs
use a separate descriptor/file.
The app also embeds `Contents/Resources/legal`: the English and Russian
first-launch agreement, Gemma terms and notice, model notices, privacy text,
project license, and the matching Electron and Chromium notices. The Electron
main process rejects preparation and backend
start until the current agreement version has been explicitly accepted; that
version and acceptance time are stored locally in the private desktop settings.

## Finder acceptance copy

The final app normally preserves the existing CLI location:
`~/Library/Application Support/Hebrew Live CLI`. For a Finder acceptance test
with an empty isolated data root, create a throwaway copy:

```sh
.venv/bin/python scripts/prepare_desktop_proof_app.py \
  --source-app "dist/electron/mac-arm64/Hebrew Live.app" \
  --destination-app "/private/tmp/Hebrew Live Finder QA.app" \
  --data-home /private/tmp/HebrewLiveFinderQAData
```

Open the copied `.app` from Finder. The helper refuses to overwrite either a
destination app or a non-empty data root. It adds a local proof configuration
only to the copy; the normal build does not contain that file.

## Model set and disk calculation

The desktop inventory is `src/hebrew_live/desktop_models.json`. It pins 14
files across three components; four files enter the app:

| Component | Revision | Files | Bytes | Placement |
| --- | --- | ---: | ---: | --- |
| GigaAM-He ONNX | `f374969f14a6c7b9d5a829f8bfb80de041931f8b` | 3 | 885,421,100 | App |
| MiLMMT (`translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX`) | `24877ecba801e4b198a5679445501022682d867c` | 10 | 2,216,770,326 | Downloaded model storage |
| Silero VAD | `867c2aa692646a1f1de3e94a15c9dd9f614c0acb` | 1 | 2,327,524 | App; verified copy in model storage |
| **Total** |  | **14** | **3,104,518,950** |  |

The separate optional Accurate inventory adds two files from
`mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx` at revision
`53ad8c6cd8b32eb0303f093a404ae13c1b1d567f`: `asr/config.json` (268 bytes)
and `asr/weights.safetensors` (1,613,977,612 bytes). Both download into model
storage only on selection; neither enters the DMG. Together with the default
set, 16 files use 4,718,496,830 logical bytes before local session data.

The pinned file list used for build and first-launch SHA-256 verification is:

| Component | Relative file | Bytes |
| --- | --- | ---: |
| ASR | `fast-asr/multilingual_ctc_ft.onnx` | 885,379,394 |
| ASR | `fast-asr/mel_filters.npy` | 41,344 |
| ASR | `fast-asr/vocab.json` | 362 |
| MiLMMT | `milmmt-4b-4bit/README.md` | 5,795 |
| MiLMMT | `milmmt-4b-4bit/added_tokens.json` | 35 |
| MiLMMT | `milmmt-4b-4bit/chat_template.jinja` | 62 |
| MiLMMT | `milmmt-4b-4bit/config.json` | 2,890 |
| MiLMMT | `milmmt-4b-4bit/generation_config.json` | 210 |
| MiLMMT | `milmmt-4b-4bit/model.safetensors` | 2,183,295,977 |
| MiLMMT | `milmmt-4b-4bit/model.safetensors.index.json` | 79,768 |
| MiLMMT | `milmmt-4b-4bit/special_tokens_map.json` | 662 |
| MiLMMT | `milmmt-4b-4bit/tokenizer.json` | 33,384,123 |
| MiLMMT | `milmmt-4b-4bit/tokenizer_config.json` | 804 |
| VAD | `silero.onnx` | 2,327,524 |

The same JSON inventory stores every SHA-256 and the exact terms/source URLs;
the table above is deliberately not a second source of hashes.

The packaged desktop reads GigaAM-He from its own resources and MiLMMT from
the selected external model directory. A valid shared CLI directory is reused;
an incompatible one causes a persistent separate desktop directory. Silero is
verified in the app and copied atomically into the selected directory. CLI and
Electron serialize writes to a shared directory, while desktop integrity checks
ignore broken optional CLI ASR files. The preflight retains a 2 GiB free-space
reserve and a 64 MiB working allowance during preparation. Model file size is
not a RAM requirement.

## Local measurement

`scripts/measure_macos_processes.py` samples the Electron process tree, macOS
memory-free percentage, and swap without treating MLX peak memory as separate
GPU RAM:

```sh
.venv/bin/python scripts/measure_macos_processes.py \
  --root-pid PID_OF_HEBREW_LIVE \
  --duration-seconds 1800 \
  --interval-seconds 30 \
  --output build/desktop-measurements/electron-30m.json
```

Use `scripts/macos_bundle_report.py` on either `.app` to inspect native deployment
targets. The measured results and acceptance limitations are recorded in
`docs/DESKTOP_TEST_REPORT.md`.
