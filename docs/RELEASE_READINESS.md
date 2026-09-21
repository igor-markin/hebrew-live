# Public-alpha release readiness

Status date: 2026-09-21 (Asia/Jerusalem).

The repository has a reviewable alpha distribution design: allowlisted source export,
Apache-2.0 for original code, embedded runtime UI, locked source bootstrap, synthetic
public fixtures, deterministic CI, package smoke, privacy-filtered bug reports, and
user-facing documentation. It remains an **alpha prerelease**, not a production-ready or
stable release.

## Acceptance checklist

| Area | Status | Evidence or remaining work |
| --- | --- | --- |
| Allowlisted public composition | **Passed locally** | Export builder copies only named roots/files; scanner rejects repository history, models, logs, exports, ZIPs, caches, internal example data, symlinks, private paths, and missing synthetic provenance. |
| Clean source bootstrap | **Passed locally** | A temporary allowlisted export completed the earlier locked frontend/Python bootstrap and tests without repository-only UI assets or model downloads. The native launcher now also passes shell syntax and fake-tool first-run tests from a fresh export. A second physical Mac remains required. |
| Wheel and sdist independence | **Passed locally** | A fresh ordinary wheel install resolved and installed real dependencies, and package/report/embedded UI probes passed. A second wheel install and the sdist-rebuilt wheel install used `constraints.txt`; every applicable installed version matched the transitive `uv.lock` export. No model weights were downloaded. |
| Python/frontend tests | **Passed locally** | The current clean-export smoke passed 274 Python tests and 28 frontend tests; its production build compiled 303 modules. Coverage includes overload/low-space partial archives, no-audio sessions, spawned inference transport/crash/hang cleanup, stalled Python workers, cancel/retry, language/model compatibility, and archive schema fallback. |
| Cross-contract fixtures | **Passed locally** | Shared synthetic API snapshots are parsed by frontend tests and checked against backend-required state keys. |
| Follow-latest and localized live UI regression | **Passed locally** | Deterministic observer test covers new children and later card resize callbacks. A rendered installed-wheel smoke polled synthetic state, loaded local fonts, stayed at bottom through card growth and a new group. A current production-asset fixture additionally verified the English default, Hebrew RTL, target switching with old/new group language metadata, outside-click closure, a server-error locale rollback with the selector disabled during the request, successful retry, and no console warnings/errors. |
| Model acquisition boundary | Implemented; runtime terms review remains | Weights are absent from source/wheel/sdist. Interactive first run asks separately before dependency bootstrap and model download; noninteractive setup requires the explicit acknowledgement flag. Setup prints sources and terms/evidence and writes a versioned per-file SHA-256 manifest. Compatible local paths skip managed download without bypassing the platform guard. Separately downloaded weights are not a code-distribution license grant. |
| User install/use docs | Implemented | English README plus Russian quickstart document local-path installs and same-commit Git source plus transitive constraints, distinguish setup/model terms, state Apple-GPU-only MLX/Metal inference, and cover optional raw audio, partial archives, storage/deletion, BYO paths, limitations, and troubleshooting. A pushed commit was installed through its public Git URL with constraints from the same SHA; the final prerelease commit receives the same check before tagging. |
| Native launcher and platform boundary | **Passed locally** | `run.sh` rejects non-macOS, Intel, and Rosetta before downloads, accepts only a frozen environment confirmed by read-only `uv --check`, requires renewed consent to repair partial/stale environments, distinguishes missing MLX from missing Metal, keeps prepared runs offline with `--no-sync`, and preserves command arguments/status. The Python entry point repeats the runtime guard. |
| Privacy/security/support docs | Implemented with honest gaps | No private security intake address or public support URL has been invented. |
| Third-party/model/font inventory | **Bundled-material review passed locally; model terms remain separate** | Vite found 12 packages in the production output. Their license files, locked registry URLs, and integrity values ship in the notice. Python direct requirements are exact, `constraints.txt` matches the full `uv.lock` export, and the generated inventory records both lock graphs. Python dependencies remain separately installed rather than vendored. |
| Original code license | **Passed** | Owner confirmed licensing authority and selected Apache-2.0; canonical `LICENSE` and SPDX package metadata are included in all artifacts. |

The standalone repository is
[github.com/igor-markin/hebrew-live](https://github.com/igor-markin/hebrew-live), which
publishes the reviewed source independently from its former private monorepository.
The standalone CI uses GitHub's current `macos-14` arm64 label and asserts
`uname -m=arm64`; the label is listed in the official
[runner-images table](https://github.com/actions/runner-images#available-images).

## Open gates after this public-alpha prerelease

- configure a real private security intake channel and public support links;
- complete a source and wheel install plus privacy/storage/uninstall review on a second
  clean Apple Silicon Mac; if a later release advertises the default downloader, also
  exercise explicit setup/model terms, doctor, microphone, stop/cancel, archive,
  restart, and deletion there;
- run real microphone/model inference acceptance and a long-session soak;
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
data, installed the locked frontend graph, compiled 303 Vite modules, passed 28
frontend tests and 274 Python tests, and built wheel and sdist. It installed the wheel
normally with dependencies, installed it again with the complete transitive constraints,
rebuilt a wheel from the unpacked sdist, and installed that build with the same
constraints. All three installed-package probes served the embedded HTML,
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

The current working tree passed 274 Python tests and 28 frontend tests. The focused
native-launcher slice passed all 19 launcher/platform tests against fake `uv`, OS, and
Metal responses, without microphone access or model downloads. The exported `run.sh`
passed `/bin/sh -n`; both the source ZIP and sdist preserve mode `0755`, while the wheel
correctly exposes only the installed `he-ru` entry point. A direct one-array MLX probe
on the development Mac confirmed Metal access without loading a model. An additional
fresh offline `uv sync` was attempted but stopped because the isolated cache lacked the
locked `torch` wheel; the launcher tests then used the already prepared project
environment while importing code from the clean export. This does not replace the
required clean second-Mac network bootstrap, model warmup, microphone, or quality trial.

The reliability tests use synthetic PCM and fake inference. They prove contracts for a
queue overload after more than four finals, known versus unknown capture gaps,
deferred/failed translation outcomes, low-space reserve metadata, no-audio archives,
child startup/crash/transport/stream/close deadlines, no orphaned fake child,
subsequent sessions, and a recording worker stalled while holding the session lock.
They do not prove that macOS can interrupt an arbitrary filesystem or Core Audio kernel
call, or that real MLX models meet the synthetic timing bounds.

The publication check used `uv tool install --python 3.12` against a pushed full commit
SHA and `constraints.txt` fetched from that same SHA, with isolated tool, binary, cache,
Python, and application-data roots. It resolved the complete constrained dependency
graph, exposed `he-ru`, printed the privacy-filtered report and model inventory, and
passed the installed-package/embedded-UI probe. No model weights or microphone data
were used. This does not validate a second Mac, model inference, microphone capture,
or a long-session soak.
