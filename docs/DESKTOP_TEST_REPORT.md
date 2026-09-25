# Hebrew Live desktop acceptance report

Dates: 2026-09-22 through 2026-09-25

## Scope and host

The original 2026-09-22 acceptance in this report used Whisper. A separately
measured 2026-09-23 fast partial bundle and a later all-model bundle are
recorded below. All builds are local and unsigned. Publication, Developer ID
signing, notarization, automatic updates,
other platforms, system audio capture, and application-generated summaries
were not attempted.

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
| Native deployment scan | The current Electron build has 227 native files; the highest required deployment target is macOS 27.0 (three bundled libraries). This replaces the earlier macOS 26.2 result. |

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
and captured it through the physical microphone. The first translated the test
phrase as the Russian equivalent of “Hello, this is a live translation test.
Thank you very much, thank you very much.” The shorter second check produced the
same result with one closing “thank you very much.”

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
the expected Russian equivalent of “Hello, this is a live translation test.
Thank you very much.” without network access.

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
  run. Granted access was physically observed both with a detected input signal
  in the packaged Electron meter and with no audible signal. Denied and no-device
  states remain covered by code and automated tests only.
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

## Earlier fast desktop partial bundle (2026-09-23)

The earlier Electron app embedded the pinned GigaAM-He ONNX export (885,421,100
bytes for model, mel filters, and vocabulary). MiLMMT and Silero VAD remain
first-run downloads (2,219,097,850 bytes total). Recognition uses two ONNX
Runtime CPU threads; translation uses MLX/Metal. No Whisper second pass ran in
the fast sessions. That earlier app occupied about 1.7 GiB on this APFS volume:
roughly 844 MiB is the ONNX model file, 287 MiB is Electron Frameworks, and
the remainder is Python, MLX, ONNX Runtime, and other dependencies. This is a
directory allocation estimate, not the size of a compressed release asset.

One 50-second WAV replay through the final packaged Electron app produced nine
first translations. Median publication audio lag was 0.498 s, p95 about 0.733 s,
and maximum 0.803 s. A same-WAV packaged Whisper baseline also produced nine
first translations, with median 0.998 s, p95 about 1.662 s, and maximum 1.942 s.
This compares two local runs, not a controlled cross-device benchmark or an
independent accuracy score.

Three subsequent real-use local sessions, measured from accepted audio to first
visible translation, gave these results:

| Accepted audio | First translations | Median | p95 | Maximum |
| ---: | ---: | ---: | ---: | ---: |
| 165.0 s | 20 | 0.510 s | 0.645 s | 0.881 s |
| 7.9 s | 2 | 0.478 s | 0.500 s | 0.503 s |
| 38.3 s | 3 | 0.595 s | 0.701 s | 0.713 s |

The 165-second session recorded 108 ASR jobs (p95 0.208 s) and 90 translation
jobs (p95 0.955 s), with queue wait p95 0.312 s and maximum 0.528 s. These
sessions recorded no engine/runtime errors or recognition repetition-stop event.
MiLMMT warmup reported an MLX allocation peak near 2.235 GB in each session;
that is not total process RSS or total system memory. The sessions are too short
to establish long-run stability, a minimum RAM requirement, or human-reviewed
transcription accuracy. The user separately reported that the app worked well
in his real conversation.

## All-model desktop bundle (2026-09-23)

The rebuilt Electron app includes GigaAM-He, MiLMMT, and Silero VAD inside its
PyInstaller engine: 14 files and 3,104,518,950 model bytes. Every model file in
the Electron app matched the bundled SHA-256 manifest. The app also contains
the English and Russian Hebrew Live agreements, the dated Gemma Terms and
notice, GigaAM-He and Silero notices, and Electron/Chromium notices.

An isolated first launch from the packaged `.app` displayed the agreement with
an unchecked acceptance box and disabled Continue button. The complete Gemma
text opened inside the onboarding screen. After explicit acceptance, the app
reported Apple Silicon, macOS 27.0, 16 GiB reference memory, and available
Metal; verified and warmed the bundled models; and advanced to language choice.
The isolated data root recorded the accepted agreement version and timestamp
without creating or downloading a model directory. After a restart it resumed
on language choice, saved Russian as the interface and target language, detected
an input signal on the built-in microphone, and opened the ready, paused
Hebrew-to-Russian working screen. The final all-model app did not run a new
recording or timed translation replay; the latency figures above come from the
earlier fast partial bundle with the same GigaAM-He and MiLMMT model files.

The final app has 4,115 bundle entries, 208 native files, and 3,903,787,049
logical bytes (about 3.64 GiB). The native deployment scan found a highest
minimum macOS version of 27.0.0 in three bundled dylibs. The generated
Electron-builder DMG with English and Russian license prompts is 3,110,351,044
bytes and passed `hdiutil verify`; the comparison ZIP is 3,111,887,555 bytes
and passed `unzip -tqq`. DMG is 1,536,511 bytes smaller (about 0.05%). The
embedded English and Russian DMG license texts round-trip exactly to the
source agreements. Both formats exceed GitHub Releases' 2 GiB per-file
limit. `codesign` reports an ad hoc signature with no TeamIdentifier. There is
no Developer ID signature, notarization, clean-second-Mac install, or external
download proof. The local test app and its test process were closed afterward.
The retained local test artifact is
`dist/electron/Hebrew-Live-0.1.0-arm64-BASELINE.dmg` with SHA-256
`0c64ab4bdde92c795f639d1b2bf1ed7df043571c8c2646893f30bc0797d9789b`.

The final working tree passed 312 Python tests, 28 frontend tests, and 10
Electron tests. An allowlisted source export passed its public-tree scan with
181 files and 4,052,384 bytes, excluding model weights, recordings, logs,
build output, and repository history.

## Lighter desktop candidate (2026-09-24)

The original all-model DMG was preserved before editing as
`dist/electron/Hebrew-Live-0.1.0-arm64-BASELINE.dmg` (3,110,351,044 bytes,
SHA-256 `0c64ab4bdde92c795f639d1b2bf1ed7df043571c8c2646893f30bc0797d9789b`).
The new unsigned local test DMG is
`dist/electron/Hebrew Live-0.1.0-arm64.dmg` (1,132,996,132 bytes,
SHA-256 `6f54b2223c0333ae23a0246c5d407b68b6dfcad5456900176b11aaca834844e1`).
It is 1,977,354,912 bytes smaller and is below the 1.8 GiB local target;
`hdiutil verify` passed. The generated app bundles only the three GigaAM-He
files and Silero VAD (887,748,624 model bytes); MiLMMT remains a pinned
first-preparation download. The current DMG was extracted to
`/private/tmp/hebrew-live-post-navigation-qa/Hebrew Live.app`; it contained the
same four bundled model files (GigaAM-He and Silero), no MiLMMT weights, and
the updated Electron navigation code. The packaged engine executable has the
same SHA-256 as the previously tested lighter candidate; the legal files were
present. All four model hashes in the final extraction matched its bundled
manifest.

The current tree passed 324 Python, 28 frontend, and 12 Electron tests. Tests
cover persistent shared/fallback location selection, optional corrupt CLI ASR,
atomic manifest merge under a process lock, full and partial `.part` files,
invalid `Content-Range`, HTTP 200/206/416, forced exit, disk-full recovery, and
backend-page navigation retries and timeout.
The public allowlist exported 188 source files and passed the
public-tree scanner; tracked Git files include no model, recording, log, or
DMG paths. A screenshot from the pre-navigation DMG at 2240 × 1560 showed
the entire agreement step, checkbox, and Continue button inside the window;
only the terms pane scrolls. After the user's explicit approval for this
isolated test, the agreement was accepted. From an empty isolated data root
the app downloaded and verified 2,216,770,326 MiLMMT bytes, reached 5/6,
then showed “Ready to begin” for Hebrew-to-Russian. The interval from the
model lock timestamp to the verified manifest was about 54 seconds, not a
complete UI-to-ready measurement. No `.part` files remained. Relaunching
the same extracted app reused the models and reached “Ready to begin”
without downloading again. The test app was closed.

A separate cold packaged-controller run in another isolated data root took
60.423 seconds from preparation request to `preparation_complete`, including
2,216,770,326 transferred MiLMMT bytes, verification, and warmup. This is a
network-dependent first-preparation measurement; the original build already
contained the model and has no comparable download step.

For an offline replay, Wi-Fi was switched off and `scutil --nwi` showed no
IPv4 state; a TCP connection to 1.1.1.1:443 was unreachable. The packaged
engine from the exact DMG translated a 50-second excerpt of the attached WAV
from an empty Hugging Face cache with no token, producing six first
translations (p50 0.427 s) and no engine error. With Wi-Fi still off and the
same isolated data root, the exact extracted Electron app reached “Ready to
begin” without opening the microphone. The app was closed, Wi-Fi was restored,
and no test app process remained. A later offline UI launch showed a blank
Electron renderer for several minutes, although its packaged backend logged
`audio_format` at 4.295 seconds with no engine error. The user then asked that
Wi-Fi no longer be disabled, so the attempt was stopped before UI translation.
Wi-Fi was restored, `scutil --nwi` showed reachable IPv4 and IPv6 on `en0`,
and the test app and its children exited. The engine's offline translation is
verified, but reliable offline Electron startup and UI translation are not.
These checks changed the Mac's real Wi-Fi power state. A review of system
events found that an earlier test left Wi-Fi off until it was manually
re-enabled, so automatic restoration was not reliable. The user asked that
Wi-Fi not be disabled again; no further network-off test is planned.

The 2026-09-24 lighter DMG adds bounded retries and a preparation-screen error if backend
page navigation fails. With Wi-Fi left on and only one test app running, the
app extracted from the final DMG reached “Ready to begin” using the prepared
isolated data root. Its local browser state reported an enabled Start button;
the app then exited and no Hebrew Live process remained. This single online
smoke test does not establish that the intermittent blank window is resolved
under every condition or that offline Electron translation works.

The engine executable and `app.asar` in the preserved all-model DMG have the
same SHA-256 hashes as the installed all-model app used for baseline timing.
Both manifests list identical MiLMMT and Silero file hashes. The preserved
DMG was mounted read-only for this check, then detached.

The preserved-DMG engine and the engine extracted from the pre-navigation
lighter DMG each ran
three complete replays of the attached 421.2-second WAV, with prepared models,
an empty Hugging Face cache, offline model loading, isolated data roots, and
the same `HEBREW_LIVE_DESKTOP_MANAGED` output mode. Run 2 reversed the build
order. A 20-second host-load gate preceded every replay. Each replay finished
without a reported error or partial result and produced 66 first translations.
The raw local measurements are in
`/private/tmp/hebrew-live-final-dmg-qa/performance-clean/comparison.json`.
That lighter DMG's engine executable has the same SHA-256
(`8d5f6aa3d052c91f44b7988151eb2b5d7e3d6df53b913816172df3d77dd98c2b`)
as the measured lighter engine. The Electron navigation change does not affect
those engine timings.

| Metric (median of 3 runs) | All-model baseline | Lighter DMG | Maximum allowed | Result |
| --- | ---: | ---: | ---: | --- |
| Controller model-file check | 1.288 s | 1.277 s | 3.288 s | Pass |
| Packaged engine launch to audio-ready | 5.536 s | 4.280 s | 6.536 s | Pass |
| Main-process peak RSS | 3,034 MiB | 117 MiB | 3,337 MiB | Pass |
| Process-tree peak RSS | 3,728 MiB | 2,732 MiB | 4,101 MiB | Pass |
| MLX peak reported at warmup | 2,132 MiB | 2,132 MiB | 2,388 MiB | Pass for warmup only |
| Accepted audio to first translation, p50 | 0.460 s | 0.459 s | 0.560 s | Pass |
| Accepted audio to first translation, p95 | 0.581 s | 0.577 s | 0.881 s | Pass |

The per-run first-translation p95 values were 0.574/0.594/0.581 s for the
baseline and 0.580/0.570/0.577 s for the lighter DMG. The 1-minute system
load at each run's start ranged from 1.58 to 2.71; no competing heavy test
process was observed. Peak RSS is sampled process memory and can count shared
pages in more than one process; it must not be added to MLX allocation. The
main-process RSS depends on which process owns model memory, so process-tree
RSS is the more useful host comparison.

The MLX diagnostic reports peak allocation at warmup; the existing packaged
binaries do not emit a full-session MLX peak. That specific acceptance metric
remains unverified. The measured launch-to-ready value is for the packaged
engine's `audio_format` event, not a timed Electron screen transition.

An earlier exploratory six-run comparison had lighter-build p95 values of
0.609/1.258/2.957 s. Its two builds used different output-mode settings, and
other host load was present; the exact cause of the slow runs is not proven.
The matched run above is the acceptance comparison. The earlier slow results
remain recorded rather than being treated as evidence that every future run
will stay near 0.58 s.

## Optional accurate recognition candidate, 2026-09-25

The reported 36.8-second Hebrew→Russian WAV was replayed through the new packaged
Python engine in both desktop modes, with local models and Hugging Face offline
flags. No model weights or conversation files were put in the app. This is a
single recording, not a corpus accuracy score or a human-verified transcript.
The two modes have separate ASR inference; Whisper does not run behind the fast
mode. The fast mode remained the default.

| Measured on the same five speech groups | Reported fast session | New packaged fast | New packaged accurate |
| --- | ---: | ---: | ---: |
| First nonempty translation lag, median | 0.483 s | 0.506 s | 0.955 s |
| ASR step, p50 / p95 across 13 fragments | 0.071 / 0.106 s | 0.066 / 0.098 s | 0.447 / 0.469 s |
| Packaged benchmark start to warmup finished | — | 4.362 s | 38.845 s |
| MLX peak reported at warmup | — | 2,235,072,432 B | 4,371,638,122 B |

The original fast output for the first count was `אח שתיים שלוש אר4ע חמ ש`
and its translation was `Брат 2, 3, AR4, ХМ 5`. Packaged fast reproduced it.
Packaged accurate output `אחת, שתיים, שלוש, ארבע, חמש, שש` and translated it
as `один, два, три, четыре, пять, шесть`. The second and fifth counts also
became coherent. For the longer zero-based count, Whisper produced
`0, 1, 2, 3, 4, 5, 6, 8, 9`; it omitted 7 on repeated local segmentations, and
the actual spoken sequence has not been independently verified by a listener.
Whisper therefore improved this recording without establishing perfect accuracy.

The optional pinned 1,613,977,880-byte model was separately downloaded into
`/private/tmp/hebrew-live-accurate-download-qa/models`, without a Hugging Face
token. Both files passed size and SHA-256 checks; the existing working model
directory was not changed. File timestamps put the large file's write at about
31 seconds on this connection and 32.5 seconds from creation of the small
config file to the weight file's final write. These are approximate transfer
times, excluding earlier verification, later hashing, warmup, and UI steps.
A later packaged desktop-controller check recognized the prepared model in
0.58 seconds and completed a repeat Accurate preparation, including file checks
and warmup, in 13.15 seconds without downloading another byte. The 38.845-second
benchmark warmup above was the first packaged invocation in that run; these
single timings do not establish a stable startup percentile.
An isolated controller smoke test started Fast, observed a local backend state
with `recording_started=false`, stopped it, then did the same for Accurate. Both
backend processes exited before the next mode started. The local URL's
`backend_ready` event is only a server-readiness signal, so its short timing is
not treated as model-ready time.

The final unsigned test DMG is 1,177,129,198 bytes (SHA-256
`03ed6c5a43091c056bdb8b15dedbb2509ff02575021f2cd4f949f50dbcd18026`).
The preserved fast-only DMG is 1,132,996,132 bytes (SHA-256
`6f54b2223c0333ae23a0246c5d407b68b6dfcad5456900176b11aaca834844e1`).
The 44,133,066-byte difference includes the packaged Whisper runtime and its
Numba/LLVM dependencies; no Whisper or MiLMMT weight file is present inside
the new `.app`. The final DMG remains below the 1.8 GiB local target.

After the final download-preservation fix, the current source passed 328 Python,
28 frontend, and 13 Electron tests. The final DMG was mounted after accepting
its 2026-09-25 agreement for an isolated test and copied outside the source tree.
With prepared isolated models and process-local `HF_HUB_OFFLINE=1`, its first-run
agreement and button fit in the 1120 × 780 CSS-pixel window without page scrolling;
the app checked models, detected the MacBook Air microphone without archiving a
sample, and reached the ready screen. Selecting Accurate restarted the backend,
reached ready, and persisted the selected mode; switching back to Fast also reached
ready. With Whisper absent from a second isolated model root, selecting Accurate
showed the optional-download page and its Fast fallback returned to ready without
downloading. Only one Electron app was running at a time, and both test runs exited.

The engine extracted from that final DMG also replayed the supplied WAV with
custom paths to the prepared isolated models, `HF_HUB_OFFLINE=1`, and no saved
audio. The accurate-mode benchmark exited 0 and reproduced the coherent first
count and the longer count missing 7 reported above. Python emitted a
`resource_tracker` leaked-semaphore warning on CLI benchmark shutdown; no
Hebrew Live process remained. The process-local offline flag does not establish
that the whole Mac had no network access; system Wi-Fi was left untouched at the
user's request. A fresh allowlisted public export passed the private-content
scanner (189 copied source files; 190 including the generated manifest). The
optional model's conversion card does not clearly declare its license; legal
review remains required before public distribution.

After the final copy and repaint changes, the 2026-09-25 DMG passed
`hdiutil verify`. Its extracted packaged engine executable matched the built
engine by SHA-256. The bundled model directory contained GigaAM-He ONNX,
vocabulary and mel filters, plus Silero ONNX, with no MiLMMT or Whisper weights.
The extracted app was launched through macOS with an isolated data-home pointer
added to that test copy; executable and model files were unchanged. The active
window visibly reached the Fast ready screen, then returned to the optional
Accurate preparation screen after selection. A capture of the inactive Electron
window showed a blank surface, while activating the same window displayed its
loaded page. This distinguishes that capture state from a proven empty active
page; it does not resolve the earlier offline desktop-startup observation.
Only one test app was running, it exited normally, and no engine child remained.
The current source reran 328 Python, 28 frontend, and 13 Electron tests.

A second extraction from the same final DMG was started through macOS with an
empty isolated data root; only a test data-home pointer was added to the copy.
The app displayed the 2026-09-25 agreement in one 1120 × 780 window, including
its checkbox and Continue button, while only the terms pane scrolled. After the
user's approval for this version in an isolated test, the app downloaded and
verified MiLMMT in that root. The manifest appeared about 60 seconds after
Prepare was pressed, and no `.part` file remained. The preparation screen
showed transferred bytes, reusable partial bytes, and verified-file bytes
separately. The microphone test detected the built-in input without creating
an archive entry; source-audio saving was disabled for this test. The app then
reached the Fast ready screen without starting capture. On the next process
launch it reached ready again with the same manifest timestamp and no download.
Both launches exited with no remaining app or engine process. The Mac's Wi-Fi
state was not changed.

The packaged engine from this extracted copy also replayed the 36.8-second
reported WAV against those freshly downloaded models with a new empty Hugging
Face cache, no token, and `HF_HUB_OFFLINE=1`. It exited 0, accepted all 36.8
seconds, closed five speech groups, marked the archive non-partial, saved no
source audio, and reported no error event. This confirms packaged Fast
translation with the final DMG's model-acquisition path; it does not replace a
human-reviewed accuracy evaluation or a whole-computer network-disconnected
Electron test.
