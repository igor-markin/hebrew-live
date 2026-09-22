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
different Mac has not been tested. The pinned MLX binaries in this build require
macOS 26.2 or later; the preflight blocks older systems, Intel/Rosetta execution,
an unavailable Metal device, and insufficient target-disk space. Less than
16 GiB produces a warning and still allows an explicit continuation.

## Reproducible build

Run all commands from the repository root unless a command changes directory.
Models are never copied into either application bundle.

```sh
uv sync --frozen --group desktop-build

cd experiments/publication-ui-preview
npm ci
npm test
npm run build
cd ../..

.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/build_macos_engine_app.py --skip-web-build

cd desktop/electron
npm ci
npm test
npm run dist:mac
cd ../..
```

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

## Stage-one proof app

To exercise Finder launch without touching the normal archive, first create a
fresh three-component model directory from already verified local models, then
embed only its absolute location and an isolated data location in the proof app:

```sh
.venv/bin/python scripts/prepare_desktop_proof_models.py \
  --source-models /absolute/path/to/existing-models \
  --destination /private/tmp/HebrewLiveStage1/models

.venv/bin/python scripts/build_macos_engine_app.py --skip-web-build \
  --proof-models /private/tmp/HebrewLiveStage1/models \
  --proof-home /private/tmp/HebrewLiveStage1/data
```

Open `dist/desktop-engine/Hebrew Live.app` from Finder. This proof configuration
contains machine-local absolute paths and is not a distributable build. Rebuild
the engine without the two `--proof-*` arguments before packaging Electron.

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

The desktop inventory is `src/hebrew_live/desktop_models.json`. It pins 13 files
across exactly three components:

| Component | Revision | Files | Bytes |
| --- | --- | ---: | ---: |
| Hebrew ASR (`mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx`) | `53ad8c6cd8b32eb0303f093a404ae13c1b1d567f` | 2 | 1,613,977,880 |
| MiLMMT (`translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX`) | `24877ecba801e4b198a5679445501022682d867c` | 10 | 2,216,770,326 |
| Silero VAD | `867c2aa692646a1f1de3e94a15c9dd9f614c0acb` | 1 | 2,327,524 |
| **Total** |  | **13** | **3,833,075,730** |

The pinned file list used for both download accounting and SHA-256 verification is:

| Component | Relative file | Bytes |
| --- | --- | ---: |
| ASR | `asr/config.json` | 268 |
| ASR | `asr/weights.safetensors` | 1,613,977,612 |
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

The desktop downloader does not fetch the optional multilingual CLI ASR model.
Existing four-asset CLI manifests remain valid. Space required before each
write is the remaining unverified bytes, minus only a confirmed resumable
partial, plus 64 MiB downloader working allowance and a 2 GiB reserve. Verified
files are not counted again. Model file size is not used as a RAM requirement.

The downloader owns a finite retry budget: three retries after 2, 5, and
15 seconds, with a 30-second no-progress read timeout. It retains `.part` files,
verifies every SHA-256, reuses completed files, distinguishes access/disk/hash
errors from transient network failures, and enters a paused state after the
budget is exhausted.

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
