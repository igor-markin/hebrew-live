# Hebrew Live desktop acceptance report

Date: 2026-09-22

## Scope and host

This report covers a local unsigned build only. Publication, Developer ID
signing, notarization, automatic updates, other platforms, new models, system
audio capture, and application-generated summaries were not attempted.

All physical testing was performed on one MacBook Air (`Mac17,3`) with an
Apple M5 (10 cores), 16 GiB unified memory, and macOS 27.0 (build 26A428),
running native `arm64`. No result in this report proves a minimum hardware
configuration. A clean installation on a different Mac remains untested.

## Built artifacts

| Artifact | Result |
| --- | --- |
| PyInstaller 6.22.3 `onedir` engine | `dist/desktop-engine/Hebrew Live.app` and `dist/desktop-engine/Hebrew Live` |
| Electron 44.4.3 shell | `dist/electron/mac-arm64/Hebrew Live.app` |
| Models | external three-component inventory; 13 files; 3,833,075,730 bytes |
| Native deployment scan | 214 native files in the engine app and 227 in Electron; highest required deployment target is macOS 26.2 |

Allocated directory sizes on the acceptance volume were approximately
591 MiB for the proof engine app, 590 MiB for its `onedir`, 914 MiB for the
Electron app, and 3.60 GiB for the models. Logical bundle sizes were
611,069,149 bytes for the engine app and 914,402,009 bytes for Electron.
APFS allocation and logical/archive
sizes are not interchangeable.

## Stage one: packaged Python engine

The proof app embedded Python 3.12 and the pinned runtime dependencies. Its
models and data/archive roots were outside the bundle under `/private/tmp`; no
user archive was modified. The app was opened through macOS LaunchServices,
not through the source launcher. The source checkout, `uv`, Node.js, and the
development virtual environment were not used by the running process.

Verified results:

- native Apple Silicon and Metal checks passed;
- the existing three-component model directory was verified without download;
- MLX/MiLMMT and the Hebrew ASR model loaded from the packaged process;
- microphone permission and the physical MacBook Air microphone worked;
- start, pause/continue, finish, archive, a second session, and full exit worked;
- no packaged engine or inference child remained after exit;
- a required Python prompt resource missing from the first package attempt was
  found by real retranslation and added to the PyInstaller spec; the successful
  run did not fall back to `.venv`.

Two acoustic Hebrew-to-Russian checks played speech through the Mac speakers
and captured it through the physical microphone:

1. `שלום, זאת בדיקה של התרגום החי. תודה רבה, תודה רבה.` became
   `Здравствуйте, это проверка живого перевода. Большое спасибо, большое спасибо.`
2. `שלום, זאת בדיקה של התרגום החי. תודה רבה.` became
   `Здравствуйте, это проверка живого перевода. Большое спасибо.`

The second short proof session measured MiLMMT load at 1.977 s, warmup at
2.533 s, MLX peak memory at 4,371,638,122 bytes, ASR p50/p95 at
0.804/0.870 s, translation p50/p95 at 0.413/0.496 s, and publication audio
lag p50/p95 at 1.571/2.416 s. MLX peak memory and process RSS are views of the
same unified memory and are not added together.

## Electron shell and first run

The first run was completed in an isolated data root. The following were
observed in the packaged app:

- three welcome pages with the real interface screenshots, Back/Next/Skip,
  and the default checked “do not show again” choice;
- hardware preflight showing native `arm64`, macOS 27.0, 16 GiB, Metal,
  current pressure/load, and target-disk availability;
- a preparation summary for ASR (1.61 GB), MiLMMT (2.22 GB), and VAD
  (2.3 MB), followed by verification and successful warmup;
- reuse of all verified model files without a duplicate download;
- independent interface and translation choices, including English UI with
  Russian translation, followed by a saved switch to Russian UI;
- explicit default-on source-audio consent;
- microphone device and level test that created no archive entry;
- the working screen remained at “Ready to begin” and did not open the audio
  stream until Start was pressed;
- archive browsing did not start capture;
- physical microphone capture, Hebrew-to-Russian translation, finish,
  archive display, and a second ready session;
- Help showed GitHub and safe diagnostic-copy actions without an empty contact
  placeholder;
- normal and minimum 760-by-620 renderer viewports, with the Russian settings
  panel entirely inside the working area (`settingsFits: true` in both cases).

A separate Finder-launched copy began with an empty isolated data root. It
downloaded the pinned 3,833,075,730 model bytes over the network. The transfer
was deliberately stopped with an ASR `.part` file of 693,108,736 bytes, the
application exited with no remaining process, and the next launch reduced the
missing total from 3.83 GB to 3.14 GB and resumed that file. The interval from
the earliest downloaded model-file timestamp to the final verified manifest
was 290.156 seconds; this includes the intentional pause and relaunch, so it is
an end-to-end recovery result rather than a pure network benchmark. Verification
and warmup completed before the language step was shown.

After preparation, the same copy was launched with `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`, and an unreachable HTTPS proxy. It reached “Ready to
begin”, captured the physical microphone, and translated the control phrase to
`Здравствуйте, это проверка живого перевода. Большое спасибо.` without network
access.

The reported layout defect in which the Russian Settings panel moved under the
left archive column was reproduced. The settings trigger now consumes the
remaining toolbar space and anchors the 460-pixel panel to the right side. The
rebuilt app was visually inspected at 1120-by-748 and 760-by-620 viewports.

The final active Electron soak sampled the full process tree every 30 seconds
for 1,800.038 seconds (61 samples). Process-tree RSS peaked at 416,530,432
bytes; the largest individual process peaked at 157,794,304 bytes. The macOS
`memory_pressure -Q` free percentage started at 37%, reached a minimum of 29%,
and ended at 32%. System-wide swap was already 8,855,685,693 bytes at the first
sample, peaked at 9,496,952,832 bytes, and ended at 8,483,105,669 bytes; the
peak is therefore reported as host state, not attributed wholly to Hebrew Live.

For that session MiLMMT load was 1.493 s, warmup was 2.204 s, and the MLX peak
was 4,371,638,122 bytes. ASR p50/p95 was 0.862/0.982 s, translation p50/p95 was
0.646/2.667 s, and publication audio lag p50/p95 was 1.584/3.530 s. The high
translation p95 includes an ambient false fragment and is not accuracy evidence.
The same control phrase translated correctly at both ends of the run. Its final
publication lag was 2.311 s near the beginning and 1.504 s near the end, versus
2.416 s in the stage-one proof on the same spoken phrase. This is a practical
same-host comparison, not a statistically controlled benchmark. MLX peak and
RSS are both views of unified memory and are not added together.

## Automated checks

- Python `unittest` discovery: 305 tests passed in the final rerun.
- Runtime lifecycle tests cover no microphone before Start and microphone open
  after Start.
- Desktop storage tests cover missing, verified, corrupt, and resumable files;
  less-than-16-GiB and current-load warnings are independent.
- Download tests cover range resume, a server without range support, a corrupt
  checksum, access denial, full connection loss, no-progress timeout, and the
  exact 2/5/15-second retry budget before pause.
- Old four-asset and new three-asset manifests are both accepted.
- Electron tests cover the versioned protocol-facing lifecycle decisions,
  private/atomic onboarding preferences, locale selection, English UI plus
  Russian translation, URL restrictions, preload allowlisting, and the packaged
  icon contract.
- Frontend tests: 28 passed; Electron tests: 9 passed.
- The public source export completed with 169 files and 3,967,563 bytes, then
  passed its allowlist/privacy scan with the explicit Electron source set.

## Lifecycle and recovery evidence

- Closing the packaged main process during a test caused the controller channel
  to close; the engine, inference worker, renderer, and helpers all exited.
- Normal completed-session exit released the physical microphone and left no
  app/backend child processes.
- During active recording, both “Stay” and “Finish recording and quit” were
  exercised through the native dialog. Confirmed exit finalized the session and
  left no child processes.
- During an active network transfer, both “Stay” and “Stop download and quit”
  were exercised. Confirmed exit retained the incomplete MiLMMT `.part` file
  and left no child processes.
- A second launch exited immediately and raised the existing window; only one
  main Electron process remained.
- Killing the packaged controller process closed its parent-watch pipe; the
  managed backend process group and both observed multiprocessing children
  exited. The still-running preparation window moved to
  `BACKEND_STOPPED_UNEXPECTEDLY`. “Restart engine” returned to “Ready to begin”
  without resuming capture. A separate copy with its engine executable
  unavailable showed `PACKAGED_ENGINE_MISSING`, while Help, diagnostics, retry,
  and Quit remained available.
- The backend never resumes recording automatically after a new session or
  process start; it returns to “Ready to begin”.
- Partial downloads are retained as `.part`; completed files are SHA-256 checked
  before reuse. Non-resumable servers replace only the incomplete file.

## Post-acceptance polish and cleanup

- The rebuilt Electron bundle uses the custom Hebrew Live 1024-pixel RGBA icon.
  `CFBundleIconFile` resolves to the generated `Contents/Resources/icon.icns`,
  and the rebuilt app was launched and quit successfully.
- After acceptance, the ten isolated QA app/data roots under `/private/tmp`
  were deleted. Their measured size before deletion was 13,440,147,446 bytes
  (12.52 GiB); a follow-up existence check found none of the ten paths.

## Known limitations and deferred gates

- This unsigned app is for local testing. Developer ID, hardened-runtime
  distribution signing, notarization, Gatekeeper distribution, and updates are
  not implemented or tested.
- A clean install on another Mac has not been tested.
- Physical microphone refusal was not re-created because the host already had
  permission; changing macOS privacy settings was not part of this unattended
  run. Denied/no-device/no-signal states are distinct in code and automated
  tests, but only granted/no-signal were physically observed.
- The measurements describe this Mac and this workload only. In particular,
  16 GiB is the tested reference, not a proven minimum, and the observed
  system-wide swap cannot be assigned entirely to the application.
- PyInstaller can emit a `multiprocessing.resource_tracker` warning about a
  semaphore already removed by a child during shutdown. No child process was
  left running, but the warning remains a packaging/runtime cleanup limitation.

## Final acceptance rows

These rows are filled from the final clean rerun; a checked row means the stated
evidence exists on the qualified host rather than being inferred from unit tests.

- [x] Fresh model download to an empty directory, interruption/resume, verify,
  warmup, and successful subsequent offline launch.
- [x] 30-minute active Electron session with beginning/end control phrase,
  process-tree RSS, macOS memory pressure, swap, MLX peak, and latency summary.
- [x] Moved Finder-launched Electron proof copy with an empty isolated data root.
- [x] Final Python, frontend, Electron, public-export, and bundle checks.
