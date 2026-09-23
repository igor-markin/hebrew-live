# CLI and browser mode

This guide contains the command-line details intentionally kept out of the main
[desktop README](../README.md). The CLI opens the same local interface in a web browser
and preserves compatibility with the four-component model set, including the optional
multilingual ASR model.

## Supported platform

The runtime is native Apple Silicon macOS with working MLX/Metal. There is no Intel,
Rosetta, Linux, Docker, CUDA, cloud, or CPU-inference fallback. Python must be 3.12.

## Quick start from source

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
git clone https://github.com/igor-markin/hebrew-live.git
cd hebrew-live
./run.sh
```

The first interactive run explains dependency and model preparation before changing
anything. To review the model sources without downloading weights:

```sh
./run.sh model-info
```

If you accept the separately linked model terms, prepare and verify the environment:

```sh
./run.sh setup --accept-model-terms
./run.sh doctor
./run.sh listen
```

Later prepared launches use the frozen environment and can run without network access.

## Commands

| Command | Purpose |
| --- | --- |
| `./run.sh listen` | Open the local live interface and wait for you to start recording. |
| `./run.sh benchmark /path/to/audio.wav` | Process a local audio file for repeatable measurements. |
| `./run.sh devices` | List available audio input devices. |
| `./run.sh doctor` | Verify platform, Metal, model integrity, loading, and warmup. |
| `./run.sh model-info` | Print pinned model sources and terms without downloading. |
| `./run.sh languages` | Print the qualified translation-target registry. |
| `./run.sh storage` | Show effective data paths without creating or deleting them. |
| `./run.sh uninstall --dry-run` | Preview app-owned removal targets; it never deletes them. |
| `./run.sh report` | Print privacy-filtered diagnostic metadata. |

Useful recording options follow the subcommand:

```sh
./run.sh listen --direction he-en
./run.sh listen --direction he-ru --device 2 --start-paused
./run.sh listen --asr-backend multilingual
```

Run `./run.sh listen --help` or `./run.sh benchmark --help` for the complete option
list. The default input contract is Hebrew and the default target is English.

## Language controls

The Settings menu can change the translation target while recording. Audio already in
the ordered pipeline keeps its original target; newly captured audio starts a new
session part. Existing cards, files, retries, and archive metadata are never relabelled.

Interface language is a separate saved preference. Browser mode supports English,
Russian, and Hebrew/RTL. The desktop app deliberately exposes English and Russian only.

`./run.sh languages` prints the source-of-truth target list. The pinned MiLMMT model
provides 45 translation targets after excluding Hebrew-to-Hebrew. The optional
multilingual Whisper tokenizer has a wider upstream vocabulary, but that does not
expand Hebrew Live's qualified live-input contract.

## Compatible local models

The CLI accepts explicit local model paths:

```sh
./run.sh doctor \
  --asr-model /absolute/path/to/mlx-whisper \
  --translation-model /absolute/path/to/mlx-lm \
  --vad-model /absolute/path/to/silero_vad.onnx

./run.sh listen \
  --asr-model /absolute/path/to/mlx-whisper \
  --translation-model /absolute/path/to/mlx-lm \
  --vad-model /absolute/path/to/silero_vad.onnx
```

The ASR directory must contain compatible MLX Whisper configuration and weights. The
translator must match the MiLMMT prompt and tokenizer contract. The ONNX file must
match the [Silero VAD](https://github.com/snakers4/silero-vad/blob/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/src/silero_vad/data/silero_vad.onnx)
interface used to distinguish speech from silence.

Explicit paths must be outside the setup-managed `models/` directory, so they cannot
bypass the managed SHA-256 manifest. A matching directory layout is not proof of model
quality or compatibility; `doctor` is the required load-and-warmup check.

## Install as a persistent command

From a reviewed local checkout:

```sh
uv tool install --python 3.12 /absolute/path/to/hebrew-live
he-ru model-info
he-ru setup --accept-model-terms
he-ru doctor
he-ru listen
```

For a reproducible Git installation, use the same full reviewed commit for the source
and transitive constraints:

```sh
uv tool install --python 3.12 \
  --constraints 'https://raw.githubusercontent.com/igor-markin/hebrew-live/COMMIT_SHA/constraints.txt' \
  'git+https://github.com/igor-markin/hebrew-live.git@COMMIT_SHA'
```

Replace both `COMMIT_SHA` values with the same published full hash. Installing code
does not download model weights or accept their separate terms.

To build ordinary Python artifacts locally:

```sh
uv build
```

The wheel embeds the production browser assets and exposes the `he-ru` command from
the environment into which it was installed.

## Storage, archive, and deletion

The installed command normally uses:

```text
~/Library/Application Support/Hebrew Live CLI
```

Source-checkout behavior remains compatible with existing users. Inspect the exact
effective paths without creating or deleting anything:

```sh
./run.sh storage
./run.sh uninstall --dry-run

# Installed wheel or uv tool
he-ru storage
he-ru uninstall --dry-run
```

The uninstall command is preview-only. Quit Hebrew Live, review its output, and move
only the confirmed app-owned paths to Trash. Custom model paths are external user data
and are never included in the managed deletion preview.

Each session may contain microphone audio, recognized speech, translations, timing and
model metadata, and error details. The archive can delete a completed session after
confirmation; the current session is protected. There is no automatic retention
policy or secure-erasure guarantee. See [Privacy](../PRIVACY.md).

## Safe diagnostic reports

Generate a privacy-filtered report:

```sh
./run.sh report --output /tmp/hebrew-live-report.json
```

The report contains platform and package versions, pinned model revisions, model-choice
booleans, and manifest status. It excludes local paths, browser tokens, preferences,
captions, audio, and session logs. Review every file before sharing it.

## Troubleshooting

- **`setup requires --accept-model-terms`**: run `model-info`, review the linked terms
  and [third-party inventory](THIRD_PARTY.md), then acknowledge the download only if you
  accept them.
- **`Model not installed`**: rerun setup to restore the pinned managed model set.
- **Model integrity failure**: do not edit the manifest. Preserve the diagnostic report
  and rerun setup when network access and disk space are available.
- **No microphone**: run `./run.sh devices`, confirm the macOS microphone permission,
  and select the intended input device.
- **Missing browser UI**: rebuild it with `npm ci` and `npm run build` in
  `experiments/publication-ui-preview`, then rebuild the Python package.
- **Partial session warning**: open the archive entry. Known unprocessed audio and an
  unknown device-capture gap are reported separately.

For architecture, security boundaries, and release evidence, see
[Architecture](ARCHITECTURE.md), [Desktop acceptance](DESKTOP_TEST_REPORT.md), and
[Release readiness](RELEASE_READINESS.md).

