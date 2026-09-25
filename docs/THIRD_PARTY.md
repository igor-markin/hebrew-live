# Third-party software, models, and fonts

This is an engineering inventory, not legal advice or a completed rights review. The
project's original code is Apache-2.0. The fast GigaAM-He ONNX export and Silero
VAD are bundled in the desktop app; MiLMMT is downloaded from its pinned source
when the app is prepared. No model weights are included in
the public source archive, wheel, or sdist. The source CLI downloads its own
model set separately.
The code license grants no additional rights to those weights or other third-party
material.

## Runtime model inventory

| Role | Pinned source | Current size | Stated terms/evidence | Checksum posture | Release status |
| --- | --- | ---: | --- | --- | --- |
| Fast desktop Hebrew ASR | [GigaAM-He](https://huggingface.co/asfberlin/fast-hebrew-asr) at `f374969f14a6c7b9d5a829f8bfb80de041931f8b` | 885,421,100 bytes for the three exported files | The model card states MIT for its weights and base [GigaAM](https://github.com/salute-developers/GigaAM/blob/7447938d791c4f3e643386ee22c33777004293a5/LICENSE), and asks to retain HebDB attribution. Training data is not bundled. | Source checkpoint, ONNX export, mel filters, and vocabulary are pinned by `fast_asr_manifest.json`; build verifies three export hashes. | Bundled only in the fast desktop app, with `fast_asr_notice.txt`. This is the publisher's stated license, not an independent rights warranty. |
| Optional accurate desktop and CLI Hebrew ASR | `mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx` at `53ad8c6cd8b32eb0303f093a404ae13c1b1d567f` | 1,613,977,880 bytes | The MLX conversion card does not state a license. Its named upstream `ivrit-ai/whisper-large-v3-turbo` card states Apache-2.0. | Pinned conversion revision and exact two-file SHA-256 inventory; separate desktop download and verification. | Downloaded only when Accurate recognition is selected; conversion metadata review remains open before public release. |
| Legacy multilingual CLI ASR | `mlx-community/whisper-large-v3-turbo` at `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb` | ~1.5 GB | MLX conversion of OpenAI Whisper; confirm conversion metadata and upstream MIT notice at the pinned revision. | Pinned revision plus local per-file SHA-256 manifest. | Optional CLI download; conversion metadata review remains open. |
| Default MT | `translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX` at `24877ecba801e4b198a5679445501022682d867c` | 2,216,770,326 bytes | The pinned model card declares `license: gemma`, identifies Xiaomi MiLMMT as the base, and links the [Gemma Terms of Use](https://ai.google.dev/gemma/terms) and prohibited-use policy. | Exact downloaded files are checked against the pinned desktop inventory before use and after repair. | Downloaded directly from the pinned source during desktop preparation; the app still supplies Gemma terms and use restrictions. Rights review remains open. |
| VAD | exact Silero VAD Git commit `867c2aa692646a1f1de3e94a15c9dd9f614c0acb` | 2,327,524 bytes | The [license at that exact commit](https://github.com/snakers4/silero-vad/blob/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/LICENSE) is MIT. This is the `silero-vad` repository, not the separately licensed `silero-models` repository. | SHA-256 `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3` is checked before bundling and on first launch. | Bundled in desktop app; retain the MIT notice. |

Primary model pages:

- [GigaAM-He model and attribution](https://huggingface.co/asfberlin/fast-hebrew-asr)
- [ivrit.ai training-data license](https://www.ivrit.ai/en/the-license/)
- [Pinned legacy Hebrew MLX conversion](https://huggingface.co/mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx/tree/53ad8c6cd8b32eb0303f093a404ae13c1b1d567f)
- [Upstream ivrit.ai model](https://huggingface.co/ivrit-ai/whisper-large-v3-turbo)
- [Pinned MiLMMT conversion](https://huggingface.co/translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX/tree/24877ecba801e4b198a5679445501022682d867c)
- [Pinned Silero VAD source file](https://github.com/snakers4/silero-vad/blob/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/src/silero_vad/data/silero_vad.onnx)

`--accept-model-terms` is a source CLI setup flag. It records no legal conclusion and transmits no acceptance record;
it prevents an accidental multi-gigabyte download before the user reviews this file.
`he-ru model-info` prints the pinned source, terms/evidence link, and unresolved review
note without downloading; setup repeats that information before starting the download.

## Bring-your-own compatible models

The CLI accepts explicit local paths for an MLX Whisper ASR directory, an MLX-LM
translation directory, and a Silero-compatible VAD ONNX file. These paths must be
outside the setup-managed `models/` directory. This prevents a path override from
silently bypassing the managed SHA-256 manifest. If any managed component is used,
the full managed manifest remains mandatory and is verified before loading models.

Directory-shape checks are only a fast compatibility guard. `doctor` still has to load
and warm up the model. The CLI supports the existing `turbo` or `multilingual` ASR
contracts and the MiLMMT translation prompt/tokenizer contract; it
does not promise arbitrary MLX architectures. Users remain responsible for obtaining
their chosen files and reviewing the associated licenses, acceptable-use conditions,
provenance, and integrity. Explicit paths are not copied into the package, report, or
diagnostic model metadata.

## Fonts and browser bundle

The production Vite output contains modules or assets from these 12 locked packages:

| Declared license | Packages included in the production output |
| --- | --- |
| OFL-1.1 | `@fontsource/noto-sans@5.3.0`, `@fontsource/noto-sans-hebrew@5.3.0` |
| MIT | `@heroui/react@3.2.4`, `@heroui/styles@3.2.4`, `clsx@2.1.1`, `react@19.3.0`, `react-dom@19.3.0`, `scheduler@0.28.0`, `tailwind-variants@3.3.1` |
| Apache-2.0 | `react-aria@3.52.1`, `react-aria-components@1.21.1`, `react-stately@3.50.0` |

Every listed installed npm package contains a license file. None contains a separate
`NOTICE` file. The Vite build now derives this list from the modules included in its
output and writes `web/licenses/THIRD-PARTY-NOTICES.txt` with each exact license text,
locked registry URL, and SHA-512 integrity value. The build fails if an included
package lacks a declared license, lock provenance, or an installed license/notice file.
The two individual OFL files remain beside the aggregated notice and packaged fonts.

Tailwind, Vite, TypeScript, and other build-only packages remain in `package-lock.json`
and `docs/DEPENDENCY_INVENTORY.json`; their package code is not copied into the runtime
output according to the Vite/Rollup module inventory. Rebuilding the UI repeats this
check instead of relying on the list above remaining current.

## Python and Node dependencies

`uv.lock` is the canonical full Python resolution for CPython 3.12. It records exact
versions and artifact SHA-256 hashes. `package-lock.json` is the canonical full Node
resolution and records exact versions, registry URLs, declared license identifiers,
and npm integrity hashes where supplied.

`docs/DEPENDENCY_INVENTORY.json` is a normalized, generated index of both lockfiles. It
is useful for review but does not override package license files or prove compatibility.
Regenerate and verify it with:

```sh
python3 scripts/generate_dependency_inventory.py --check
```

The project wheel and sdist do not vendor Python dependency packages. `pip`/`uv`
installs those distributions separately, with their own package metadata and license
files. The project artifacts therefore carry the original-code Apache license and the
license material for the web code/fonts actually embedded in `hebrew_live/web`; they do
not duplicate the full license directories of separately installed Python packages.

The desktop bundle includes `gemma_notice.txt`, the complete dated
`gemma_terms.txt`, `fast_asr_notice.txt`, and `silero_notice.txt`. The Electron
shell also carries the project agreement in English and Russian, privacy
statement, original-code license, Electron and Chromium notices from the exact
installed Electron binary, and this inventory. It requires explicit
first-launch acceptance of the agreement before model preparation or backend
start. The separate Gemma prohibited-use policy is incorporated by reference
and linked in the agreement and first-launch screen.

This is a bounded distribution-content review rather than a legal opinion.
Repeat it whenever a model, lockfile, frontend import, or packaged asset
changes. Qualified legal review is still needed for the public distribution,
including the enforceability of the Gemma use restrictions and the app's
liability limitations in the intended markets. Unlike the source wheel, the
PyInstaller desktop engine embeds Python runtime dependencies. Most copied
distribution metadata includes license files; the remaining Python license
and source-offer obligations, especially LGPL dependencies, must be checked
against the exact signed binary before publication.

Specific unresolved binary review items are the license and source obligations
for bundled `python-bidi` and `soxr` LGPL components, the `tqdm` MPL/MIT notice,
the Python runtime and PyInstaller bootloader, and the Homebrew-derived
`libcrypto.3.dylib`, `libssl.3.dylib`, and `liblzma.5.dylib`. The signed/notarized
binary must be scanned again because signing or dependency replacement can
change its contents. These open items are release blockers for a claim of
complete third-party compliance; a license label in a lockfile alone does not
complete them.
