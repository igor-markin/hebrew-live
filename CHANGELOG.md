# Changelog

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
- public installation, privacy, security, support, architecture, dependency, and release
  documentation in English, plus a Russian quickstart;
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
