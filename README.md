# Hebrew Live

[![macOS Apple Silicon](https://img.shields.io/badge/macOS-Apple%20Silicon-111111)](docs/DESKTOP_BUILD.md)
[![MLX + Metal](https://img.shields.io/badge/MLX%20%2B%20Metal-local-5E5CE6)](https://github.com/ml-explore/mlx)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-0B7285)](LICENSE)

**Live Hebrew transcription and translation that stays on your Mac.**

Hebrew Live listens only after you press **Start recording**, shows the Hebrew
transcript beside its translation, and keeps a local session archive that you can
return to later.

![Hebrew speech with a live English translation](docs/images/live-translation.jpg)

> [!IMPORTANT]
> This is an alpha source build. The app is unsigned and not notarized. It has been
> tested on one MacBook Air with Apple M5, 16 GiB unified memory, and macOS 27.0.
> A clean installation on another Mac has not yet been verified.

## What you get

- live Hebrew speech recognition and translation into 45 available target languages;
- an English or Russian desktop interface;
- local transcripts and an optional local copy of the original audio;
- a Finder-launchable macOS app that works offline after its models are prepared.

Inference is local. The app has no account, analytics service, or cloud transcription
API. Internet access is needed only to download the pinned models during preparation.

## Build and open the app

You need:

- an Apple Silicon Mac running macOS 26.2 or later;
- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 24;
- about 6 GB of free disk space for the app, models, temporary download data, and the
  required 2 GiB safety reserve.

Copy and run this block in Terminal:

```sh
git clone https://github.com/igor-markin/hebrew-live.git
cd hebrew-live

uv sync --frozen --group desktop-build
npm --prefix experiments/publication-ui-preview ci
npm --prefix experiments/publication-ui-preview run build
.venv/bin/python scripts/build_macos_engine_app.py --skip-web-build
npm --prefix desktop/electron ci
npm --prefix desktop/electron run dist:mac

open "dist/electron/mac-arm64/Hebrew Live.app"
```

The finished app is at:

```text
dist/electron/mac-arm64/Hebrew Live.app
```

After the build, you can move that app to another folder and open it from Finder. The
models remain outside the app bundle in the Hebrew Live data folder.

For a reproducible build with tests, packaging details, and an isolated acceptance
copy, use the [desktop build guide](docs/DESKTOP_BUILD.md).

## First launch

The app guides you through the rest:

1. Review the Mac, Metal, memory, load, and disk checks.
2. Review the three model components and approve the 3.83 GB download.
3. Choose the interface language and translation language independently.
4. Confirm audio storage, grant microphone access, and check the input level.

Preparation resumes after a restart and reuses files that already passed integrity
checks. Once the status says **Ready to begin**, press **Start recording**. Opening a
saved conversation never starts the microphone.

## Everyday controls

- **Start recording** begins microphone capture.
- **Finish recording** waits for admitted audio to finish processing.
- **Settings** changes the interface language, translation target, audio storage, and
  theme.
- **Exit Hebrew Live**, the application menu, closing the last window, and **Command-Q**
  all perform the same complete shutdown.

![Language, audio, and appearance settings](docs/images/language-settings.jpg)

Saved conversations stay in the left sidebar and can be reopened without recording:

![A saved conversation in the local archive](docs/images/session-archive.jpg)

The screenshots above were captured from the packaged Electron application,
not a browser. They use synthetic conversation text and contain no private recording.

## Models

The desktop setup downloads exactly three pinned components:

| Component | Purpose | Download size |
| --- | --- | ---: |
| [ivrit.ai Whisper Large v3 Turbo for MLX](https://huggingface.co/mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx/tree/53ad8c6cd8b32eb0303f093a404ae13c1b1d567f) | Hebrew speech recognition | 1.61 GB |
| [MiLMMT-46-4B v1.0, 4-bit MLX](https://huggingface.co/translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX/tree/24877ecba801e4b198a5679445501022682d867c) | Translation | 2.22 GB |
| [Silero VAD](https://github.com/snakers4/silero-vad/blob/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/src/silero_vad/data/silero_vad.onnx) | Detecting speech and silence | 2.33 MB |
| **Total** |  | **3.83 GB** |

Model weights are downloaded separately and are not covered by the repository's
Apache-2.0 license. Review the exact revisions, checksums, and terms in the
[third-party and model inventory](docs/THIRD_PARTY.md) before downloading them.

## Privacy and storage

- Transcription and translation run locally through MLX/Metal.
- Text is saved locally even when original-audio storage is turned off.
- A diagnostic report excludes conversations, recordings, tokens, and personal paths;
  always review it before sharing.

There is no automatic retention policy or secure-erasure guarantee. Read
[Privacy](PRIVACY.md) for the exact data and network boundaries.

## Current limits

- Apple Silicon and MLX/Metal are required; there is no Intel, Rosetta, Linux, CUDA,
  cloud, or CPU-inference fallback.
- 16 GiB is the tested reference, not a proven minimum. Smaller-memory Macs show a
  warning and allow an explicit attempt.
- Developer ID signing, notarization, automatic updates, App Store distribution, and a
  clean second-Mac test are not included yet.
- System-audio capture and app-generated meeting summaries are not included.

Measured startup, memory, latency, 30-minute processing, Finder launch, microphone,
offline, lifecycle, and recovery results are in the
[desktop acceptance report](docs/DESKTOP_TEST_REPORT.md).

## More documentation

- [Desktop build and packaging](docs/DESKTOP_BUILD.md)
- [CLI and browser mode](docs/CLI.md)
- [Desktop acceptance report](docs/DESKTOP_TEST_REPORT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Third-party software and model terms](docs/THIRD_PARTY.md)
- [Release readiness](docs/RELEASE_READINESS.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)
