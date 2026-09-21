# Public-alpha release readiness

Status date: 2026-09-21 (Asia/Jerusalem).

The repository has a reviewable alpha distribution design: allowlisted source export,
Apache-2.0 for original code, embedded runtime UI, locked source bootstrap, synthetic
public fixtures, deterministic CI, package smoke, privacy-filtered bug reports, and
user-facing documentation. It remains an **alpha candidate**, not a public-ready or
stable release.

## Acceptance checklist

| Area | Status | Evidence or remaining work |
| --- | --- | --- |
| Allowlisted public composition | **Passed locally** | Export builder copies only named roots/files; scanner rejects repository history, models, logs, exports, ZIPs, caches, internal example data, symlinks, private paths, and missing synthetic provenance. |
| Clean source bootstrap | **Passed locally** | A temporary allowlisted export completed the earlier locked frontend/Python bootstrap and tests without repository-only UI assets or model downloads. The native launcher now also passes shell syntax and fake-tool first-run tests from a fresh export. A second physical Mac remains required. |
| Wheel and sdist independence | **Passed locally** | UI is served from `hebrew_live/web`; isolated `--no-deps` wheel and sdist-rebuilt-wheel probes imported only from their venv and fetched installed HTML, JS, CSS, fonts, bundled notices, and state over loopback HTTP. The clean source `uv sync` separately installed the locked dependency graph. |
| Python/frontend tests | **Passed locally** | The current clean-export smoke passed 254 Python tests and 27 frontend tests; its production build compiled 303 modules. The language/model regression set specifically covers the single managed MiLMMT contract, safe interpretation of retired preferences and manifests, target switching, archives, and rejection of removed CLI options. |
| Cross-contract fixtures | **Passed locally** | Shared synthetic API snapshots are parsed by frontend tests and checked against backend-required state keys. |
| Follow-latest and localized live UI regression | **Passed locally** | Deterministic observer test covers new children and later card resize callbacks. A rendered installed-wheel smoke polled synthetic state, loaded local fonts, stayed at bottom through card growth and a new group. A current production-asset fixture additionally verified the English default, Hebrew RTL, target switching with old/new group language metadata, outside-click closure, a server-error locale rollback with the selector disabled during the request, successful retry, and no console warnings/errors. |
| Model acquisition boundary | Implemented; runtime terms review remains | Weights are absent from source/wheel/sdist. Interactive first run asks separately before dependency bootstrap and model download; noninteractive setup requires the explicit acknowledgement flag. Setup prints sources and terms/evidence and writes a versioned per-file SHA-256 manifest. Compatible local paths skip managed download without bypassing the platform guard. Separately downloaded weights are not a code-distribution license grant. |
| User install/use docs | Implemented | English README plus Russian quickstart lead with `./run.sh`, document local-path `uv tool install` and exact-commit installs from the public repository, distinguish interactive and explicit noninteractive setup, state Apple-GPU-only MLX/Metal inference, and cover storage/deletion, BYO paths, limitations, and troubleshooting. A local-path `uv tool install --python 3.12` completed in an isolated tool directory and its installed UI/package probe passed. The publication check installs the pushed commit through its public Git URL before treating publication as complete. |
| Native launcher and platform boundary | **Passed locally** | `run.sh` rejects non-macOS, Intel, and Rosetta before downloads, accepts only a frozen environment confirmed by read-only `uv --check`, requires renewed consent to repair partial/stale environments, distinguishes missing MLX from missing Metal, keeps prepared runs offline with `--no-sync`, and preserves command arguments/status. The Python entry point repeats the runtime guard. |
| Privacy/security/support docs | Implemented with honest gaps | No private security intake address or public support URL has been invented. |
| Third-party/model/font inventory | **Bundled-material review passed locally; model terms remain separate** | Vite found 12 packages in the production output. Their installed license files, locked registry URLs, and integrity values ship in an automatically generated notice; both individual OFL texts remain. The build fails on missing bundled-package license evidence or lock provenance. Python dependencies are separately installed rather than vendored. |
| Original code license | **Passed** | Owner confirmed licensing authority and selected Apache-2.0; canonical `LICENSE` and SPDX package metadata are included in all artifacts. |

The standalone repository is
[github.com/igor-markin/hebrew-live](https://github.com/igor-markin/hebrew-live), which
publishes the reviewed source independently from its former private monorepository.
The standalone CI uses GitHub's current `macos-14` arm64 label and asserts
`uname -m=arm64`; the label is listed in the official
[runner-images table](https://github.com/actions/runner-images#available-images).

## Required before a tagged public-alpha release

- create a reviewed release tag, and configure a real private security intake channel
  and public support links;
- on a different clean Apple Silicon Mac, complete source and wheel install plus the
  privacy/storage/uninstall review; if the alpha advertises the default downloader,
  the trial must also exercise explicit setup/model terms, doctor, microphone,
  stop/cancel, archive, restart, and deletion;
- complete a focused security/privacy review of the loopback server, archive deletion,
  export composition, and bug-report boundary.

Separately downloaded model weights are absent from the code artifacts. Their open
conversion metadata and Gemma/other runtime terms do not become Apache-2.0 code-
distribution obligations. They remain a disclosed condition for users who choose
`setup`; compatible local models are an alternative. Do not describe model use as
rights-cleared until that separate review is complete.

## Required for broader support or a stable release

- qualify supported Safari and Chromium versions, narrow/mobile layouts, keyboard and
  assistive-technology behavior, and accessibility beyond the one-viewport installed
  browser smoke;
- use a rights-cleared quality corpus and long-session soak to establish measured
  accuracy, latency, memory, and stability limits;
- add signing/notarization and a wider system/browser matrix when a distribution
  channel beyond source and Python packages is selected.

## Deliberately outside this alpha slice

Stable 1.0 claims, new platforms, Homebrew or GUI installers, release signing and
notarization, full-size quality evaluation, long-duration production soak, release
upload, and new translation features.

## Local validation record

The current clean-export smoke ran with a fresh temporary npm cache sourced only from
locked `package-lock.json` registry URLs. It downloaded 36,867,891 bytes of npm cache
data, installed the locked frontend graph, compiled 303 Vite modules, passed 27
frontend tests and 254 Python tests, built wheel and sdist, installed the wheel in an
isolated environment, rebuilt a wheel from the unpacked sdist, and installed/probed
that rebuilt wheel. Both installed-package probes served the embedded HTML,
JavaScript, CSS, 14 font assets, 12 bundled dependency notices, and the state endpoint.
The temporary cache was deleted when the smoke finished; no browser binaries or model
weights were downloaded.

The bounded bundled-material review found 12 packages in the production Vite output:
two OFL-1.1 font packages, seven MIT packages, and three Apache-2.0 packages. Every
installed package supplied a license file and none supplied a separate NOTICE file.
The generated aggregate notice preserves those exact texts and lock provenance inside
the served and installed UI. Build-only Node packages and separately installed Python
dependencies are recorded in the lock inventory but are not copied into the wheel.

The first offline attempt stopped before tests because the empty temporary npm cache
lacked `use-sync-external-store@1.7.0`. A second attempt using the default user npm
cache failed with an existing permissions error, so it was not modified. The successful
third attempt used a separate temporary cache. These are environment/setup outcomes,
not product-test failures.

Final source-export composition, package license contents, current test result, and
artifact SHA-256 values are recorded in the review handoff generated alongside the
local artifacts. Artifact hashes cannot be embedded in the artifact itself without
changing those hashes. The rendered smoke used only synthetic state and one installed
in-app-browser viewport. No real model inference, microphone capture, accessibility
audit, security scan, quality run, or soak is represented by this record.

The current working tree passed 254 Python tests and 27 frontend tests. The focused
native-launcher slice passed all 19 launcher/platform tests against fake `uv`, OS, and
Metal responses, without microphone access or model downloads. The exported `run.sh`
passed `/bin/sh -n`; both the source ZIP and sdist preserve mode `0755`, while the wheel
correctly exposes only the installed `he-ru` entry point. A direct one-array MLX probe
on the development Mac confirmed Metal access without loading a model. An additional
fresh offline `uv sync` was attempted but stopped because the isolated cache lacked the
locked `torch` wheel; the launcher tests then used the already prepared project
environment while importing code from the clean export. This does not replace the
required clean second-Mac network bootstrap, model warmup, microphone, or quality trial.

The install-from-source check used `uv tool install --python 3.12` against the local
service path with isolated tool, binary, cache, Python, and application-data roots. It
resolved and installed the locked Python dependencies, exposed `he-ru`, printed the
current model/language/storage reports, and passed the installed-package probe. This
validates the local source build and entry point. It does not validate an unavailable
public Git URL, model downloads, model inference, microphone capture, or publication.
