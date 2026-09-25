# Public-alpha release readiness

Status date: 2026-09-25 (Asia/Jerusalem).

The repository has a reviewable alpha distribution design: allowlisted source export,
Apache-2.0 for original code, embedded runtime UI, locked source bootstrap, synthetic
public fixtures, deterministic CI, package smoke, privacy-filtered bug reports, and
user-facing documentation. It remains an **alpha prerelease**, not a production-ready or
stable release.

## Local desktop build (2026-09-22 and 2026-09-23)

The unsigned PyInstaller/Electron desktop work is evaluated separately in
[`DESKTOP_TEST_REPORT.md`](DESKTOP_TEST_REPORT.md). On the qualified MacBook Air
(Apple M5, 16 GiB, macOS 27.0), the packaged engine completed real physical-microphone
Hebrew-to-Russian inference and the Electron shell completed local first-run,
model-reuse, lifecycle, responsive-layout, and long-session checks. That evidence does
not close the clean-second-Mac, Developer ID, notarization, or distribution gates below.
The previous all-model desktop bundle included GigaAM-He (885,421,100 bytes),
MiLMMT (2,216,770,326 bytes), and Silero VAD (2,327,524 bytes), for
3,104,518,950 model bytes. The lighter candidate keeps GigaAM-He and Silero in
the app and downloads pinned MiLMMT files during first preparation or repair.
The desktop includes the Whisper runtime for an optional Accurate mode, but its
1,613,977,880-byte model files are downloaded only on selection. The source CLI
also retains optional Whisper paths.
The earlier all-model Electron build passed isolated first launch, model
warmup, microphone check, and ready working screen on this Mac. The lighter
candidate's exact unsigned compressed size, cold-download measurement, and
offline checks are recorded in the desktop report. The first download and
offline engine translation passed; a later offline Electron launch showed a
blank window despite a ready backend. Offline desktop acceptance remains open,
and the user has asked that testing never switch off this Mac's Wi-Fi again.
The final DMG includes bounded backend-page navigation retries. An app extracted
from that DMG completed first run with prepared isolated models, reached the ready
screen, switched between Fast and Accurate, and showed the optional model-download
screen when Accurate weights were absent. The latest extracted copy also showed
Fast ready and optional Accurate preparation in an active macOS window. A blank
capture of the inactive window cleared on activation; the earlier offline
desktop-startup observation remains unresolved. A fresh extraction of the
same final DMG completed first download in an empty isolated data root, a
microphone input check, Fast ready, and a repeat ready launch without another
download. Its packaged engine translated the reported WAV with an empty
Hugging Face cache and process-local offline flags. The Mac's Wi-Fi was not
disabled, so the system-network-disabled desktop acceptance gate remains open.
A clean install on a second Mac remains a release gate.

## Acceptance checklist

| Area | Status | Evidence or remaining work |
| --- | --- | --- |
| Allowlisted public composition | **Passed locally** | Export builder copies only named roots/files; scanner rejects repository history, models, logs, exports, ZIPs, caches, internal example data, symlinks, private paths, and missing synthetic provenance. |
| Clean source bootstrap | **Passed locally** | A temporary allowlisted export completed the earlier locked frontend/Python bootstrap and tests without repository-only UI assets or model downloads. The native launcher now also passes shell syntax and fake-tool first-run tests from a fresh export. A second physical Mac remains required. |
| Wheel and sdist independence | **Passed locally** | A fresh ordinary wheel install resolved and installed real dependencies, and package/report/embedded UI probes passed. A second wheel install and the sdist-rebuilt wheel install used `constraints.txt`; every applicable installed version matched the transitive `uv.lock` export. No model weights were downloaded. |
| Python/frontend/Electron tests | **Passed locally** | The current working tree passed 328 Python tests, 28 frontend tests, and 13 Electron shell tests. Coverage includes model resume and manifest locking, optional accurate-mode verification, overload/low-space partial archives, no-audio sessions, spawned inference transport/crash/hang cleanup, stalled Python workers, cancel/retry, language/model compatibility, archive schema fallback, agreement preference persistence, backend-page navigation retries, and the desktop IPC allowlist. |
| Cross-contract fixtures | **Passed locally** | Shared synthetic API snapshots are parsed by frontend tests and checked against backend-required state keys. |
| Follow-latest and localized live UI regression | **Passed locally** | Deterministic observer test covers new children and later card resize callbacks. A rendered installed-wheel smoke polled synthetic state, loaded local fonts, stayed at bottom through card growth and a new group. A current production-asset fixture additionally verified the English default, Hebrew RTL, target switching with old/new group language metadata, outside-click closure, a server-error locale rollback with the selector disabled during the request, successful retry, and no console warnings/errors. |
| Model acquisition boundary | Implemented; rights review remains | Weights are absent from source/wheel/sdist. The lighter desktop candidate bundles hash-verified GigaAM-He and VAD with separate notices; it downloads pinned MiLMMT files on first preparation or repair and optional ivrit.ai Whisper files only on selection. After preparation, selected-model inference works without a network connection. The code license does not cover model weights. The MLX conversion license metadata still needs review before public release. |
| User install/use docs | Implemented | The user-focused English README links to task-specific English guides for desktop builds, CLI/browser use, local-path and same-commit Git installs, model terms, storage/deletion, compatible local models, limitations, and troubleshooting. A pushed commit was installed through its public Git URL with constraints from the same SHA; the final prerelease commit receives the same check before tagging. |
| Native launcher and platform boundary | **Passed locally** | `run.sh` rejects non-macOS, Intel, and Rosetta before downloads, accepts only a frozen environment confirmed by read-only `uv --check`, requires renewed consent to repair partial/stale environments, distinguishes missing MLX from missing Metal, keeps prepared runs offline with `--no-sync`, and preserves command arguments/status. The Python entry point repeats the runtime guard. |
| Privacy/security/support docs | Implemented with honest gaps | No private security intake address or public support URL has been invented. |
| Third-party/model/font inventory | **Partially verified; legal review open** | Vite found 12 packages in the production output and built their notices. The binary also carries model notices, Gemma terms, Electron and Chromium notices, and most Python distribution license metadata. The PyInstaller engine vendors Python dependencies, so the remaining per-package notices and any source-offer obligations need review against this exact binary. |
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
  clean Apple Silicon Mac; exercise agreement acceptance, offline model verification,
  microphone, stop/cancel, archive, restart, and deletion there;
- resolve and verify the intermittent blank Electron window before treating
  prepared-model offline desktop startup as accepted;
- run real microphone/model inference acceptance and a long-session soak;
- complete a focused security/privacy review of the loopback server, archive deletion,
  export composition, and bug-report boundary.

Model weights are absent from the source, wheel, and sdist. The desktop app
contains GigaAM-He and Silero; MiLMMT is obtained from its pinned source under
Gemma terms during preparation. The first-launch
agreement and bundled Gemma text address documented distribution conditions,
but the intended public release still needs qualified legal review. These
models do not become Apache-2.0 code. Do not present a publisher's license
statement as an independent rights warranty.

## Required for broader support or a stable release

- qualify supported Safari and Chromium versions, narrow/mobile layouts, keyboard and
  assistive-technology behavior, and accessibility beyond the one-viewport installed
  browser smoke;
- use a rights-cleared quality corpus and long-session soak to establish measured
  accuracy, latency, memory, and stability limits;
- add Developer ID signing, notarization, and a clean second-Mac install before
  advertising a public macOS binary download.
- verify the exact first-launch agreement, model attribution, and third-party
  dependency notices and source obligations with qualified counsel before a
  broad public binary release.

## Deliberately outside this alpha slice

Stable 1.0 claims, new platforms, Homebrew installers, full-size quality
evaluation, long-duration fast-build soak, release upload, and new translation
features.

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

The earlier 2026-09-22 working tree passed 305 Python tests, 28 frontend tests, and 9 Electron
shell tests. The focused
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
