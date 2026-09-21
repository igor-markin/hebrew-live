# Privacy and data flow

## Runtime

After setup, ASR, translation, VAD, browser assets, and session indexing run locally.
The HTTP server binds to `127.0.0.1` and uses a random per-process URL. Responses use
no-store, no-referrer, nosniff, and a restrictive content-security policy. There is no
cloud inference fallback.

The runtime writes transcripts, translations, diagnostic events, timing/model metadata,
integrity counters, and local preferences. Source microphone audio is saved by default
but can be disabled for the next session in Settings or with `--no-save-raw-audio`.
Inference still uses transient audio in memory; disabling persistence means no session
WAV and no fragment retry. These records can expose highly sensitive conversations even
when the application itself does not transmit them.

## Network activity

Network access is expected only when installing dependencies or running `setup`.
Setup contacts Hugging Face for pinned model repositories and GitHub raw content for
the pinned Silero VAD file. The runtime sets Hugging Face, Transformers, and ONNX
telemetry/offline controls; this is an implementation control, not a claim about every
third-party package on the machine.

## Retention and deletion

There is no automatic retention period. Completed sessions may be deleted through the
archive UI after confirmation. The active session is protected. Models, settings, and
all remaining sessions can be removed manually in Finder after the process exits.
Low-space handling does not delete older archives automatically.
Normal filesystem deletion is not a secure-erasure guarantee, and backups or snapshots
may retain copies.

## Sharing diagnostics

`he-ru report` excludes audio, captions, logs, preferences, local paths, and the private
browser token. It is the preferred starting point for a bug report. Review it before
sharing. Do not attach recordings, transcripts, or session logs unless the recipient,
purpose, and exact files have been explicitly agreed.
