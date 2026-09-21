# Third-party software, models, and fonts

This is an engineering inventory, not legal advice or a completed rights review. The
project's original code is Apache-2.0. Model weights are downloaded separately by the
user during setup and are not included in the public source archive, wheel, or sdist.
The code license grants no additional rights to those weights or other third-party
material.

## Runtime model inventory

| Role | Pinned source | Current size | Stated terms/evidence | Checksum posture | Release status |
| --- | --- | ---: | --- | --- | --- |
| Hebrew ASR | `mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx` at `53ad8c6cd8b32eb0303f093a404ae13c1b1d567f` | ~1.5 GB | The MLX conversion card does not state a license. Its named upstream `ivrit-ai/whisper-large-v3-turbo` card states Apache-2.0. | Pinned conversion revision; setup records SHA-256 for every downloaded file. No publisher-signed checksum is claimed. | Separate user download; conversion metadata review remains open before claiming rights-cleared model use. |
| Multilingual ASR | `mlx-community/whisper-large-v3-turbo` at `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb` | ~1.5 GB | MLX conversion of OpenAI Whisper; confirm the conversion repository metadata and upstream MIT notice at the pinned revision. | Pinned revision plus local per-file SHA-256 manifest. | Separate user download; conversion metadata review remains open. |
| Default MT | `translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX` at `24877ecba801e4b198a5679445501022682d867c` | ~2.1 GB | The pinned model card declares `license: gemma`, identifies Xiaomi MiLMMT as the base, and links the [Gemma Terms of Use](https://ai.google.dev/gemma/terms) and prohibited-use policy. | Pinned revision plus local per-file SHA-256 manifest. | Separate user download; the user must review the linked terms for the intended use. |
| VAD | exact Silero VAD Git commit `867c2aa692646a1f1de3e94a15c9dd9f614c0acb` | ~2.2 MB | The [license at that exact commit](https://github.com/snakers4/silero-vad/blob/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/LICENSE) is MIT. This is the `silero-vad` repository, not the separately licensed `silero-models` repository. | Expected SHA-256 `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3` is checked before write and recorded in the manifest. | Separate setup download; retain the linked terms/evidence and review notice handling. |

Primary model pages:

- [Pinned Hebrew MLX conversion](https://huggingface.co/mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx/tree/53ad8c6cd8b32eb0303f093a404ae13c1b1d567f)
- [Upstream ivrit.ai model](https://huggingface.co/ivrit-ai/whisper-large-v3-turbo)
- [Pinned MiLMMT conversion](https://huggingface.co/translate-studio/MiLMMT-46-4B-v1.0-4bit-MLX/tree/24877ecba801e4b198a5679445501022682d867c)
- [Pinned Silero VAD source file](https://github.com/snakers4/silero-vad/blob/867c2aa692646a1f1de3e94a15c9dd9f614c0acb/src/silero_vad/data/silero_vad.onnx)

`--accept-model-terms` records no legal conclusion and transmits no acceptance record;
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

This was a bounded distribution-content review rather than a legal opinion. Repeat it
whenever the lockfile, frontend imports, or packaged assets change; the build-time
notice check enforces the mechanical part of that requirement.

Separate runtime-download follow-up:

1. confirm the two MLX Whisper conversion repositories' metadata at the pinned revisions;
2. review the Gemma Terms and prohibited-use policy for each intended use;
3. confirm notice handling for the Silero VAD download;
4. do not turn any of these findings into a statement that Apache-2.0 covers the weights.
