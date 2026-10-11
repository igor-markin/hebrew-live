# Changelog

## Unreleased

### Changed

- translation drives `mlx_lm.generate_step` directly instead of `stream_generate`: the same text and finish reasons (84 of 84 compared sequences identical), without the per-call wired-memory toggling that cost 0.33-0.46 s per translation (`HEBREW_LIVE_MT_GENERATE=stock` restores it);
- the translation token budget grows with the source (96-512 tokens instead of a fixed 256) and a translation that still reaches it is shown with an explicit `[…]` instead of being dropped (`HEBREW_LIVE_MT_MAX_TOKENS=256` restores the old limit);
- a streaming translation can be cancelled between tokens: the engine process polls for a cancel message, so an abandoned or stale generation ends within one token instead of being drained for seconds or the process being killed; a refresh overtaken by newer queued audio is stopped, and the split-worker MT queue serves closing, first, then refresh jobs (`HEBREW_LIVE_MT_INTERRUPT=0` restores finishing every translation, in order);
- draft recognition no longer computes Whisper word timestamps (identical text on 41 of 41 compared windows; `HEBREW_LIVE_TEXT_ONLY_DRAFT=0` restores them);
- a Whisper decode that has become a certain loop (a letter repeated 12 times, or a word sequence three times in a row) is stopped inside the decoding loop instead of after all 224 tokens, and the check now also covers final windows; the rejected text is the same, only the wasted 1.3-1.6 s is saved (`HEBREW_LIVE_LOOP_STOP=0` restores the post-decode check on drafts only);
- a phrase group that never got any recognised text now shows "Speech was not recognized" instead of "final version unavailable";
- the loopback UI receives state over Server-Sent Events instead of polling every 150-200 ms, falling back to polling by itself (`HEBREW_LIVE_UI_PUSH=0` switches the stream off);
- the desktop engine build refuses an MLX wheel without the macOS 26 neural-accelerator kernels (`macosx_26_0`).

### Added

- diagnostics: `mlx_runtime` (wheel tags, device), `mt_generation`, `mt_cancel`, `mt_interrupted`, `mt_prioritized`; `scripts/diagnose_latency.py` now reports time to the first visible draft, normalized erasure, time to stable words, lost-speech rate, slow-down over time and the new events;
- opt-in experiments, all off by default: `HEBREW_LIVE_MT_SPECULATE=1` (drafting from the previous translation, 0.81x time but not output-identical), `HEBREW_LIVE_FUSED_ENCODER=1` (fused encoder attention: identical text on 84 of 87 real windows, 16-19 % faster calls), `HEBREW_LIVE_HOLD_LAST_WORD=1`, `HEBREW_LIVE_TIMING=first,interval,0,fragment,silence`;
- local measurement tooling in `experiments/corpus` (manifest, real-window replay, end-to-end A/B, metrics) and `experiments/nn-audit-2026-10`.

## 0.1.0-alpha.3 — 2026-10-06

### Changed

- the desktop app is signed ad hoc (`mac.identity` is `-`) with a valid bundle signature; macOS shows its standard "Apple could not verify" prompt with an Open Anyway entry in Privacy & Security, where the alpha.2 DMG was reported as damaged;
- the bundled privacy statement and third-party notices say that first preparation always downloads the pinned Whisper Turbo and MiLMMT files; documentation and one obsolete test match the Whisper Turbo and MiLMMT release.

Application code is unchanged from alpha.2; the bundled runtime moved to Python 3.12.15 and OpenSSL 3.6.5.

## 0.1.0-alpha.2 — 2026-10-05

### Added

- self-contained macOS desktop app for Apple Silicon: an Electron shell around the packaged Python engine, with guided model preparation, lifecycle recovery and a DMG;
- transient translation drafts streamed into the live UI.

### Changed

- one recognition mode, ivrit.ai Whisper Turbo (MLX), with MiLMMT translation; the optional multilingual ASR is retired and saved choices migrate to Turbo with a notice;
- retired recognition helpers are excluded from the wheel, sdist and public export.

### Known issue

- the DMG was built without a signing step, so its bundle signature is invalid and macOS reports a downloaded copy as damaged (fixed in alpha.3).

## 0.1.0-alpha.1 — 2026-09-21

### Added

- installable browser assets embedded in wheel and sdist builds;
- explicit user-data root for installed packages with source-checkout compatibility;
- pinned model/VAD inventory, VAD checksum verification, and model-terms acknowledgment;
- Apache-2.0 licensing for original project code, separate from model and dependency terms;
- explicit compatible local MLX Whisper, MLX-LM, and Silero VAD paths with managed-manifest isolation;
- privacy-filtered `he-ru report` output for reproducible bug reports;
- allowlisted standalone source export with synthetic fixtures and forbidden-path scan;
- clean-export CI and package/install smoke workflow;
- native one-command source launcher with explicit dependency/model consent, native
  arm64 and working-MLX/Metal guards, frozen-environment recovery after interrupted
  sync, offline `--no-sync` prepared launches, and BYO-path support;
- build-derived third-party notices with exact license texts and lock provenance for
  every package embedded in the production browser output;
- user-focused README plus task-specific installation, CLI, privacy, security,
  architecture, dependency, acceptance, and release documentation in English;
- English-default interface localization with Russian and Hebrew/RTL choices, persisted
  independently from the translation target;
- MiLMMT-scoped Hebrew translation targets (English by default), ordered live target
  changes serialized against model/stop/cancel actions, preserved in-flight metadata,
  explicit nonfatal preference-write failures, and a read-only language inventory;
- centralized fresh-install runtime/cache/model/session storage plus read-only `storage`
  and `uninstall --dry-run` path previews, while preserving existing source-local data.
- reproducible same-commit Git installation with exact direct requirements and complete
  transitive constraints derived from the frozen `uv.lock` graph;
- bounded spawned inference with controlled stop/cancel escalation, readable partial
  archives, and explicit known-unprocessed or unknown-capture outcomes;
- optional source-audio retention, truthful no-audio export/retry behavior, and
  low-space checks that preserve final metadata when the reserved space remains usable.

### Changed

- retired alternate translation-model support from setup, runtime selection, manifests,
  and public documentation; old saved selections migrate in memory to MiLMMT with a
  visible notice, while existing model files and archived sessions remain untouched;
- documented pinned `uv tool install` forms for reviewed local paths and future Git
  release tags without requiring publication to a package index.

### Preserved

- draft-only live publication behavior;
- nullable API-state handling and last-good browser snapshots;
- idempotent stop with a separate explicit cancellation action;
- variable-height history virtualization, archive/session protections, retry guards, and
  persistent follow-latest behavior across new content and resized cards.

### Deferred acceptance gates

- a second physical Apple Silicon Mac install and storage trial;
- real microphone and model inference acceptance, plus a long-session soak;
- focused security/privacy review and a dedicated private security intake channel.

Model conversion/terms review remains a separate condition for rights-cleared runtime
use of user-downloaded weights. A broader browser/accessibility matrix, quality corpus,
and long-session soak remain later stable-release work. An arbitrary stalled macOS
filesystem or audio-driver system call can still require restarting the application.
