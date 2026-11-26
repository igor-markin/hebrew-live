# Local macOS desktop build

Current desktop profile (0.1.0-alpha.4): streaming zipformer recognition and MiLMMT
translation only. Two models are bundled: Silero VAD (2,327,524 bytes) and the streaming
Hebrew recognizer zipformer2-66m-streaming-he (72,316,960 bytes). The pinned MiLMMT files
are the only download at first preparation (2,216,770,326 bytes, ~2.22 GB), then reused
offline. Whisper, GigaAM-He, CoreML helpers/models and experimental recognition selection
are excluded. The alpha has no Developer ID signature and is not notarized. Older
measurements and build profiles below are historical; they are not acceptance evidence for
the current DMG.


This procedure builds the local `Hebrew Live.app`, signed ad hoc only. It does not
publish, notarize, add a Developer ID signature, or enable automatic updates.

## Qualified host

The procedure below was exercised on exactly this machine:

- MacBook Air with Apple M5;
- 16 GiB unified memory;
- macOS 27.0.1;
- native `arm64` execution;
- Python 3.12.14 (alpha.2) and 3.12.15 (alpha.3), PyInstaller 6.22.3;
- Node.js 24, Electron 44.4.3, electron-builder 26.15.3.

The current profile was last built on 2026-11-26 from `stable-release` on a MacBook Air
(Apple M5, 16 GiB) with macOS 27.3, Python 3.12.16, PyInstaller 6.22.3, Node.js 26.13.1
(the packages declare Node 24; the build and tests passed), Electron 44.4.3 and
electron-builder 26.15.3.

This is a tested reference, not a proven minimum. A clean installation on a
different Mac has not been tested. The native libraries in this build require
macOS 27.0 or later; the preflight blocks older systems, Intel/Rosetta execution,
an unavailable Metal device, and insufficient target-disk space. Less than
16 GiB produces a warning and still allows an explicit continuation.

## Reproducible build

Run all commands from the repository root unless a command changes directory.
Silero VAD and the streaming recognizer are copied into the app from hash-verified local
build assets. The MiLMMT files are downloaded during first preparation or repair; the app
packages the MLX runtime but not the translation weights. The sources, revisions, file
sizes and hashes are in `src/hebrew_live/desktop_models.json` (Silero, MiLMMT) and
`src/hebrew_live/streaming_asr_manifest.json` (the streaming recognizer).

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
# The build stops unless the installed mlx and mlx-metal wheels are the macosx_26_0
# builds: wheels for older macOS (uv.lock also pins macosx_14_0 and 15_0) work but run
# without the M5 neural-accelerator kernels. Build on macOS 26 or newer.

cd desktop/electron
npm ci
npm test
npm run dist:mac
# For a local ad-hoc-signed DMG with English and Russian license prompts:
npm run dist:dmg
cd ../..
```

### Bundled model build assets

Two models enter the app. Place them in the ignored `models` directory, or pass another
directory with `--bundle-models`:

```text
models/silero.onnx                                  2,327,524 bytes
models/streaming-asr/sherpa-onnx/encoder.int8.onnx 70,478,964 bytes
models/streaming-asr/sherpa-onnx/decoder.int8.onnx  1,049,105 bytes
models/streaming-asr/sherpa-onnx/joiner.int8.onnx     771,805 bytes
models/streaming-asr/sherpa-onnx/tokens.txt            17,086 bytes
```

Silero comes from the pinned `snakers4/silero-vad` revision in
`src/hebrew_live/desktop_models.json`; the four recognizer files come from
`ivrit-ai/zipformer2-66m-streaming-he` at the revision in
`src/hebrew_live/streaming_asr_manifest.json`. The engine command checks every file's
size and SHA-256 against those inventories, embeds them with a bundle manifest, and stops
with `Bundled model missing or wrong size: …` or `Bundled model checksum mismatch: …` if
one is missing or different, or if PyInstaller omits or changes it. MiLMMT is not a build
asset: the installed app downloads it from its pinned Hugging Face revision during first
preparation or repair. The builder also fails if the MiLMMT folder appears in the bundle.

Do not commit the model files. MiLMMT runs on Metal through MLX; Silero VAD and the
streaming recognizer (sherpa-onnx) run on the CPU. At first launch the app verifies its
bundled files, downloads missing MiLMMT files, copies Silero to external model storage,
then warms the models.

With the uv, npm and Electron caches already filled by an earlier build, the dependency
steps run without network access: `uv sync --frozen --group desktop-build --offline` and
`npm ci --offline` in both frontend folders. The 2026-11-26 build reused the Electron zip
in `~/Library/Caches/electron` (its file time did not change), although the log still
prints `Downloading Electron binary...`.

Outputs:

- stage-one engine app: `dist/desktop-engine/Hebrew Live.app`;
- PyInstaller `onedir` embedded by Electron: `dist/desktop-engine/Hebrew Live`;
- final desktop app: `dist/electron/mac-arm64/Hebrew Live.app`.

The source application icon is `desktop/electron/assets/icon.png` (1024 by
1024 RGBA). Electron Builder converts it to the bundled `icon.icns` during the
macOS build.

The recipe supplies model-download TLS roots from the copied, pinned
`certifi` package. The installed app does not need a Homebrew CA directory.
The recipe excludes installer-origin metadata,
including editable `direct_url.json`, from the public bundle. If npm skips
Electron's lifecycle script, `dist:mac` and `dist:dmg` explicitly run the locked
Electron installer without changing npm's script policy.

For a reviewable local source snapshot, pass `--source-manifest PATH` to the
engine builder after generating the web assets. The manifest records each
relative source file, size and SHA-256, the canonical file-list hash, the base
commit, candidate version and honest uncommitted status. The builder verifies
it before and after PyInstaller and embeds its compact identity; the source
archive and full manifest remain separate deliverables.

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

## Code signature

`mac.identity` in `desktop/electron/package.json` is `-`, so electron-builder signs
the app ad hoc through `@electron/osx-sign`: the application, its Electron helpers
and frameworks, and the engine's main executable. The engine's other native files
keep the ad-hoc signatures PyInstaller gave them and are sealed into the bundle as
resources. electron-builder then verifies the bundle (`strictVerify` stays on), so
the build fails if the signature is invalid.
Hardened runtime stays off (`hardenedRuntime: false`) as in earlier builds; with
ad-hoc signing it would need the `com.apple.security.cs.disable-library-validation`
entitlement, and the packaged Python/MLX engine has not been qualified under it.

An ad-hoc signature carries no certificate, Team ID, name or timestamp: only file
hashes, the bundle identifier `com.hebrew-live.desktop`, and paths relative to the
bundle. It makes the bundle internally consistent. It does not identify a developer
and gives Gatekeeper no reason to trust the app, so a downloaded copy is still
blocked (see [DISTRIBUTION.md](DISTRIBUTION.md#opening-the-alpha-on-macos)).

Check a build:

```sh
APP="dist/electron/mac-arm64/Hebrew Live.app"
codesign --verify --deep --strict --verbose=2 "$APP"          # exit status 0
codesign -dv "$APP" 2>&1 | grep -E 'Signature|TeamIdentifier'  # Signature=adhoc, TeamIdentifier=not set
spctl --assess --type execute -vv "$APP"                       # rejected: no Developer ID, not notarized
```

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
only to the copy; the normal build does not contain that file. A file added
inside the signed bundle makes `codesign --verify --strict` report the copy as
modified (`file added`). The copy is never quarantined and is for local testing
only; verify the signature on the build itself.

## Model set and disk calculation

The desktop inventory is `src/hebrew_live/desktop_models.json` (Silero and MiLMMT); the
streaming recognizer has its own inventory, `src/hebrew_live/streaming_asr_manifest.json`.
Together they pin 15 files across three components; five enter the app and ten are
downloaded:

| Component | Revision | Files | Bytes | Placement |
| --- | --- | ---: | ---: | --- |
| MiLMMT (`translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX`) | `24877ecba801e4b198a5679445501022682d867c` | 10 | 2,216,770,326 | Downloaded model storage |
| zipformer2-66m-streaming-he (`ivrit-ai/zipformer2-66m-streaming-he`) | `ee769a2a13b887f91572eec349458bfb0fe79e7a` | 4 | 72,316,960 | App |
| Silero VAD | `867c2aa692646a1f1de3e94a15c9dd9f614c0acb` | 1 | 2,327,524 | App; verified copy in model storage |
| **Total** |  | **15** | **2,291,414,810** |  |

The pinned file list used for build and first-launch SHA-256 verification is:

| Component | Relative file | Bytes |
| --- | --- | ---: |
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
| ASR | `streaming-asr/sherpa-onnx/encoder.int8.onnx` | 70,478,964 |
| ASR | `streaming-asr/sherpa-onnx/decoder.int8.onnx` | 1,049,105 |
| ASR | `streaming-asr/sherpa-onnx/joiner.int8.onnx` | 771,805 |
| ASR | `streaming-asr/sherpa-onnx/tokens.txt` | 17,086 |
| VAD | `silero.onnx` | 2,327,524 |

The two JSON inventories store every SHA-256 and the exact terms/source URLs; the
tables above are deliberately not a second source of hashes.

The packaged desktop reads MiLMMT from the selected external model directory and the
streaming recognizer from the app. A valid shared CLI directory is reused; an
incompatible one causes a persistent separate desktop directory. Silero is verified in
the app and copied atomically into the selected directory. CLI and Electron serialize
writes to a shared directory, while desktop integrity checks cover only the pinned
desktop files and ignore files of retired models (Whisper Turbo, the multilingual ASR):
a manifest that still lists Whisper verifies without its files. The preflight retains a
2 GiB free-space reserve and a 64 MiB working allowance during preparation. Model file
size is not a RAM requirement.

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
