# Architecture

```text
microphone / local WAV
        │
        ▼
 local audio stream ──► optional session WAV        CPU / Core Audio
        │
        ▼
 parent-owned queues, session state, and integrity ledger
        │ bounded request/response IPC
        ▼
 spawned inference process: GigaAM-He ONNX            two CPU threads
        │ changing source text
        ▼
 same inference process: MiLMMT via MLX-LM            Apple GPU / Metal
        │ revisable draft + final state
        ├──────────────► private local session files
        ▼
 Python loopback API (127.0.0.1 + random URL)
        ▼
bundled React browser UI
```

The desktop distribution adds a shell in front of the same runtime:

```text
Electron main process
  ├─ sandboxed preparation renderer + narrow preload API
  ├─ versioned JSONL controller over stdin/stdout
  │    └─ PyInstaller onedir Python controller
  │         └─ packaged backend + spawned inference child
  └─ existing tokenized loopback React working UI
```

The preparation renderer is independent of Python and can display a controller
startup failure. Once models are verified and warmed, Electron navigates only to the
validated `127.0.0.1` backend URL. Controller diagnostics and technical logs do not
share stdout with protocol messages. A closed controller channel terminates the
backend process group. The Electron engine directory is an `extraResource` outside
ASAR; GigaAM-He and Silero VAD are bundled with the engine. The pinned MiLMMT
files are downloaded to Application Support at first preparation or for repair.
The controller selects one external model root for preflight, warmup and backend
launch, copying Silero there after checking its bundled original. User settings
and session archives stay in Application Support.

`hebrew_live.cli` owns argument parsing, setup, model inventory, and top-level error
handling. `runtime.py`, `stream.py`, `feed.py`, and `retranslation.py` coordinate audio,
boundaries, inference workers, retries, and shutdown. `session.py` writes optional raw
audio plus text, integrity, and diagnostic records. `browser_ui.py` exposes a small same-origin
loopback API and serves assets from `hebrew_live/web`; it does not depend on a repository
checkout.

`RemoteEngine` starts one spawned child for the native MLX model lifecycle. The parent
keeps the session files, processors, UI state, and accepted/terminal ledgers durable.
Request IDs serialize recognition, streamed translation, model changes, and close over
bounded IPC. Stop first allows accepted work to drain for a conservative 120-second
budget; cancellation then gets three seconds before the child is terminated, with kill
as the final escalation if it does not exit. A
closed translation generator is drained only for a short cancellation grace period, so
tokens from an abandoned request cannot enter the next part. Constructor failures,
child crashes, and close timeouts close IPC handles and reap the process. Runtime model
checks remain offline inside the child.

The fast desktop path uses a pinned GigaAM-He ONNX export for Hebrew ASR. Its
ONNX Runtime session uses two CPU inference threads and does not require a
Whisper refinement pass. Silero VAD marks speech on the CPU; MiLMMT translates
on Metal. The draft processor accepts growing audio, caps recognition windows at
20 seconds, and can revise both visible lines as additional speech arrives.
It discards superseded intermediate refresh work to protect the next useful
translation. The models still share one serialized child request stream, so a
long translation can delay the next recognition request. The desktop can instead
run ivrit.ai Whisper Turbo when the user selects Accurate recognition before a
new recording. Its pinned model files are prepared outside the app and verified
separately; the inference worker then uses one ASR backend, never a concurrent
Whisper refinement pass. The default remains fast.

During a revisable translation, complete generated words may appear as a
transient draft at most once per 100 ms. The UI replaces that text with the
completed paired publication, or clears it if generation fails. Transient words
are not added to the session archive or revision history. The loopback UI polls
every 200 ms while recording, so a very short preview may finish before the
next poll. Diagnostics record the ASR queue age, repeated audio work, first MT
token, first transient draft, and completed translation separately. An optional
`HEBREW_LIVE_TEXT_ONLY_DRAFT=1` experiment skips Whisper word alignment for
nonfinal drafts; it remains off by default because a same-window benchmark did
not establish a reliable speed gain. Final recognition still uses word timing.

The process boundary bounds native inference startup, shutdown, and close hangs. A
native call is not given a new wall-clock SLA while recording remains active; the
deadline begins at stop or cancel. Python queue delivery and joins also have deadlines,
and every started source, recording, segment, and inference thread is tracked. If one
survives teardown, the application writes only the independent integrity snapshot,
blocks a new session, and requires restart rather than closing files under that worker.
It cannot force an arbitrary filesystem or audio-driver syscall to return; the parent
does not claim that such an OS-level hang was cleanly interrupted.

Raw audio retention is separate from transient inference audio. New installs save WAV
files by default for archive playback and retry; the preference applies to the next
session. When disabled, PCM remains in bounded memory only long enough for processing,
while text, diagnostics, duration counters, and `session.json` are still persisted.
Existing sessions remain readable by inspecting whether their WAV files exist.

`languages.py` is the backend source of truth for translation capabilities and exact
model prompt names. The normal live source remains Hebrew. A target change is inserted
into the same admission FIFO as audio: older `Captured` objects retain their immutable
settings, then a `Boundary` flushes old ASR/MT work, and later audio starts a new session
part. Direction remains part of the retranslation fingerprint and every visible group,
retry request, filename, and archive record. The frontend receives only targets valid
for the active prompt contract. Interface locale is a separate preference; UI text is
never sent to a model.

The source `run.sh` launcher qualifies macOS and native arm64 before bootstrap, uses
`uv` to prepare the frozen CPython 3.12 environment only after an explicit first-run
prompt or setup flag, and performs a real MLX array evaluation to prove Metal access
before model download or model loading. The installed `he-ru` entry point repeats the
runtime guard. The source CLI defaults to MLX Whisper ASR, whereas the packaged
fast desktop selects CPU ONNX ASR by default; optional accurate mode selects
MLX Whisper ASR after its model is prepared. Translation still
requires MLX/Metal; audio handling and Silero VAD also use the CPU. Intel,
Rosetta, CUDA, and cloud inference are unsupported.

Environment readiness is the read-only result of
`uv sync --frozen --offline --check`, not the presence of `.venv/bin/python`. An
interrupted or stale environment requires a new interactive confirmation or the source
launcher `--bootstrap` flag before repair. Runtime commands use `uv run --no-sync` after
that check. MLX import and Metal-device probes are separate, so a missing package is not
reported as a hardware failure.

For a fresh source checkout, the launcher places its project environment, uv-owned
Python, package/model-transfer caches, models, preferences, and session data below the
single app root returned by `HEBREW_LIVE_HOME` (default macOS Application Support).
The source checkout and the shared `uv` executable remain separate. A checkout with
existing source-local managed files stays in legacy mode without migration. Read-only
storage and uninstall previews enumerate the exact effective roots; BYO model paths are
always external and excluded.
Installed-command previews also report explicit global `--models` and `--log-dir`
overrides and exclude them from inferred root ownership. The shell preview rejects
those Python-only override forms and points to `HEBREW_LIVE_HOME`. Browser theme
`localStorage` is browser-profile site data outside the filesystem root. Shared uv,
unreported shared caches, and previously installed shared Python runtimes are outside
the application-owned removal boundary.

The live contract is a sequence of revisioned groups. The frontend validates every
snapshot before replacing the last-good state. Long histories render a bounded
variable-height window. Follow-latest remains enabled through DOM additions and card
resizes until the user deliberately scrolls upward.

PostgreSQL, Redis, remote APIs, analytics, accounts, and cloud storage are not part of
the architecture. Setup/download traffic is separate from runtime inference traffic.
Explicit local model paths use the supported ONNX GigaAM-He or MLX Whisper,
MLX-LM prompt-family, and Silero VAD interfaces. They are shape-checked and
warmed by `doctor`, not converted or treated as universally compatible.
