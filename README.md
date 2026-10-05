# Hebrew Live

Local Hebrew captions and translation for Apple Silicon Macs.

Hebrew Live listens after you press **Start recording**, shows the Hebrew transcript beside its translation, and keeps a local session archive.

> This is an unsigned alpha for **arm64 Apple Silicon and macOS 27.0 or later**. Developer ID signing and notarization are absent. One Apple M5 Mac with 16 GiB is the tested reference; a lower RAM minimum is not established. Installation on a second Mac and the downloaded/quarantined launch path remain untested.

## Install and first launch

Download the DMG from [GitHub Releases](https://github.com/igor-markin/hebrew-live/releases), verify its SHA-256 against the attached SHA256SUMS, open it and copy Hebrew Live.app to Applications. Python, Node, Homebrew and the source checkout are not required on the receiving Mac.

1. Read and accept the [software agreement](docs/legal/EULA.en.txt) and linked model terms.
2. Review the Mac, Metal, memory and disk checks.
3. Prepare the pinned Whisper Turbo and MiLMMT files. First preparation downloads about **3.83 GB**; Silero VAD is included in the app. Completed verified files are reused.
4. Choose the interface and translation languages, then confirm audio storage and microphone access.
5. At **Ready to begin**, press **Start recording**.

After preparation, recognition and translation run locally without a network connection. Opening a saved conversation does not start recording. The release uses one recognition mode: **ivrit.ai Whisper Turbo**, with **MiLMMT** translation. GigaAM-He, alternate recognition selection and the CoreML experiment are excluded from the desktop release.

## Models

| Component | Purpose | Placement |
| --- | --- | --- |
| [ivrit.ai Whisper Turbo MLX](https://huggingface.co/mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx/tree/53ad8c6cd8b32eb0303f093a404ae13c1b1d567f) | Hebrew recognition | 1.614 GB downloaded at preparation |
| [MiLMMT-46-4B, 4-bit MLX](https://huggingface.co/translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX/tree/24877ecba801e4b198a5679445501022682d867c) | Translation | 2.217 GB downloaded at preparation |
| [Silero VAD](https://github.com/snakers4/silero-vad/blob/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/LICENSE) | Speech and silence detection | 2.33 MB in the app, copied to model storage |

Weights have separate terms and are not covered by the code's Apache-2.0 license. See the [third-party inventory](docs/THIRD_PARTY.md). The documented provenance/legal review remains open.

## Controls and storage

**Start recording** opens microphone capture. **Finish recording** waits for admitted audio to finish. Settings control interface language, translation target, audio storage and theme. Exit, closing the last window and Command-Q perform complete shutdown.

Text is stored locally even when original-audio storage is off. Model files, local settings and archives live in the Hebrew Live data folder. No historical models or recordings are automatically removed by this release change. Diagnostics omit conversations, recordings, tokens and personal paths; review them before sharing. See [Privacy](PRIVACY.md).

## Build and limits

The [desktop build guide](docs/DESKTOP_BUILD.md) uses the frozen Python 3.12/Node 24 dependency locks, local Silero model input and source-manifest verification. Models are excluded from source, wheel and sdist.

Intel Macs, Rosetta, older macOS, Linux and CUDA are unsupported. System-audio capture, automatic updates and App Store distribution are not included. Historical tests in [DESKTOP_TEST_REPORT.md](docs/DESKTOP_TEST_REPORT.md) describe older builds and do not establish acceptance results for this DMG.

- [CLI/browser usage](docs/CLI.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Third-party software and model terms](docs/THIRD_PARTY.md)
- [Distribution and readiness](docs/DISTRIBUTION.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)
