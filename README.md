# Hebrew Live

[![macOS Apple Silicon](https://img.shields.io/badge/macOS-Apple%20Silicon-111111)](docs/DESKTOP_BUILD.md)
[![MLX + Metal](https://img.shields.io/badge/MLX%20%2B%20Metal-local-5E5CE6)](https://github.com/ml-explore/mlx)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-0B7285)](LICENSE)

**Fast live Hebrew transcription and translation that stays on your Mac.**

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
- a Finder-launchable macOS app with speech recognition and voice detection included.

Inference is local. The app has no account, analytics service, or cloud transcription
API. MiLMMT downloads at first preparation or when its files need repair. The optional
accurate recognition model downloads only when selected. Once the selected models are
prepared, recognition and translation work without a network connection.

## Build and open the app

You need:

- an Apple Silicon Mac running macOS 27.0 or later for the current local build;
- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 24;
- enough disk space for the app, the 2.217 GB translation download, and the 2 GiB working reserve; see the
  [current bundle measurements](docs/DESKTOP_TEST_REPORT.md).

The build requires verified GigaAM-He and Silero files under the ignored `models/`
directory. MiLMMT is downloaded by the installed app. The recognition asset is a local ONNX export of
[GigaAM-He](https://huggingface.co/asfberlin/fast-hebrew-asr/tree/f374969f14a6c7b9d5a829f8bfb80de041931f8b).
Prepare those files as described in the [build guide](docs/DESKTOP_BUILD.md#bundled-model-build-assets).

Copy and run this block in Terminal:

```sh
git clone https://github.com/igor-markin/hebrew-live.git
cd hebrew-live

uv sync --frozen --group desktop-build
npm --prefix experiments/publication-ui-preview ci
npm --prefix experiments/publication-ui-preview run build
.venv/bin/python scripts/build_macos_engine_app.py --skip-web-build \
  --bundle-models models
npm --prefix desktop/electron ci
npm --prefix desktop/electron run dist:mac

open "dist/electron/mac-arm64/Hebrew Live.app"
```

The finished app is at:

```text
dist/electron/mac-arm64/Hebrew Live.app
```

GigaAM-He and Silero are inside the app. The downloaded MiLMMT files, local
settings, and recordings stay in the Hebrew Live data folder.

For a reproducible build with tests, packaging details, and an isolated acceptance
copy, use the [desktop build guide](docs/DESKTOP_BUILD.md).

## First launch

The app guides you through the rest:

1. Read and explicitly accept the [desktop agreement](docs/legal/EULA.en.txt)
   and the bundled Gemma restrictions.
2. Review the Mac, Metal, memory, load, and disk checks.
3. Verify the included models, download MiLMMT if needed, and let the app warm them up.
4. Choose the interface language and translation language independently.
5. Confirm audio storage, grant microphone access, and check the input level.

Once the status says **Ready to begin**, press **Start recording**. Opening a
saved conversation never starts the microphone.

## Everyday controls

- **Start recording** begins microphone capture.
- **Finish recording** waits for admitted audio to finish processing.
- **Settings** changes the interface language, translation target, recognition mode,
  audio storage, and theme. The fast GigaAM-He mode is the default. Accurate ivrit.ai
  Whisper Turbo is slower and needs a separate 1.614 GB download on first use; mode
  changes are available before recording or after the current recording finishes.
- **Exit Hebrew Live**, the application menu, closing the last window, and **Command-Q**
  all perform the same complete shutdown.

![Language, audio, and appearance settings](docs/images/language-settings.jpg)

Saved conversations stay in the left sidebar and can be reopened without recording:

![A saved conversation in the local archive](docs/images/session-archive.jpg)

The screenshots above were captured from the packaged Electron application,
not a browser. They use synthetic conversation text and contain no private recording.

## Models

The desktop app uses three pinned components by default and one optional component:

| Component | Purpose | Placement and size |
| --- | --- | ---: |
| [GigaAM-He](https://huggingface.co/asfberlin/fast-hebrew-asr/tree/f374969f14a6c7b9d5a829f8bfb80de041931f8b) | Hebrew speech recognition, ONNX CPU export bundled in app | 885.4 MB in app |
| [MiLMMT-46-4B v1.0, 4-bit MLX](https://huggingface.co/translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX/tree/24877ecba801e4b198a5679445501022682d867c) | Translation | 2.217 GB downloaded to Application Support |
| [Silero VAD](https://github.com/snakers4/silero-vad/blob/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/src/silero_vad/data/silero_vad.onnx) | Detecting speech and silence | 2.33 MB in app, copied to model storage |
| [ivrit.ai Whisper Turbo MLX](https://huggingface.co/mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx) | Optional accurate Hebrew recognition | 1.614 GB downloaded only if selected |
| **Bundled model files** |  | **887.75 MB** |

Model weights are not covered by the repository's
Apache-2.0 license. Review the exact revisions, checksums, and terms in the
[third-party and model inventory](docs/THIRD_PARTY.md).

## How the fast path works

The app continuously listens for Hebrew speech with Silero VAD. A pinned
GigaAM-He export runs in ONNX Runtime on two CPU threads, producing a quick,
revisable Hebrew draft. MiLMMT translates that draft on the Apple GPU. As more
speech arrives, the visible transcript and translation can be revised; completed
versions are saved together. The fast path bounds each recognition window to
20 seconds and drops superseded intermediate work when the queue grows. It does
not run Whisper as a second recognition pass. Accurate mode runs Whisper instead
of GigaAM-He; it does not add a background recognition task. See [architecture](docs/ARCHITECTURE.md)
and [measured results](docs/DESKTOP_TEST_REPORT.md#fast-desktop-build-2026-09-23).

## Privacy and storage

- Fast recognition runs locally on the CPU. Accurate recognition and translation use
  MLX/Metal locally.
- Text is saved locally even when original-audio storage is turned off.
- A diagnostic report excludes conversations, recordings, tokens, and personal paths;
  always review it before sharing.

There is no automatic retention policy or secure-erasure guarantee. Read
[Privacy](PRIVACY.md) for the exact data and network boundaries.

## Current limits

- Apple Silicon and MLX/Metal are required for translation; the fast Hebrew
  recognition model itself runs on the CPU. Intel, Rosetta, Linux, CUDA, and cloud
  operation are not supported.
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
- [Public macOS distribution plan](docs/DISTRIBUTION.md)
- [Desktop software agreement (English)](docs/legal/EULA.en.txt)
- [Desktop software agreement (Russian)](docs/legal/EULA.ru.txt)
- [CLI and browser mode](docs/CLI.md)
- [Desktop acceptance report](docs/DESKTOP_TEST_REPORT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Third-party software and model terms](docs/THIRD_PARTY.md)
- [Release readiness](docs/RELEASE_READINESS.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)
