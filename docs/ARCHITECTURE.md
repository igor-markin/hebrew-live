# Architecture

```text
microphone / local WAV
        │
        ▼
 local audio stream ──► immutable session WAV       CPU / Core Audio
        │
        ▼
 pinned or explicit compatible MLX ASR              Apple GPU / Metal
        │ changing source text
        ▼
 pinned or explicit compatible MLX-LM model         Apple GPU / Metal
        │ revisable draft + final state
        ├──────────────► private local session files
        ▼
 Python loopback API (127.0.0.1 + random URL)
        ▼
 bundled React browser UI
```

`hebrew_live.cli` owns argument parsing, setup, model inventory, and top-level error
handling. `runtime.py`, `stream.py`, `feed.py`, and `retranslation.py` coordinate audio,
boundaries, inference workers, retries, and shutdown. `session.py` writes immutable
audio plus text and diagnostic records. `browser_ui.py` exposes a small same-origin
loopback API and serves assets from `hebrew_live/web`; it does not depend on a repository
checkout.

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
runtime guard. ASR and translation require MLX/Metal; orchestration, audio handling, and
the ONNX Silero VAD also use the CPU. No CPU/CUDA inference fallback is selected.

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
Explicit local model paths use the same MLX Whisper, MLX-LM prompt-family, and Silero
VAD interfaces; they are shape-checked and warmed by `doctor`, not converted or
treated as universally compatible.
