# Changelog

## Unreleased

### Changed

- live translation stops a runaway loop: when the translation repeats a phrase of 3-15 words three times in a row, more often than the Hebrew does, the call ends after the first copy (`append_chunk` stop `repetition`, counted as `append.repetitions` in the summary); on a Maccabi Dent replay the eleven copies of «без лишних слов» became one;
- a card whose Hebrew has no word to translate (only single letters and marks, like «ם.» or «ת», the tail of a word cut at a pause) is shown without a translation instead of a made-up one («цеме.», «это сделать.»);
- the window's settings have a conversation text size: smallest, small, normal or large (translation 16, 18, 20 or 23 px; Hebrew and history in proportion, controls unchanged); the choice is saved with the other preferences (`text_size`), so it survives a restart although the window's address changes every launch;
- the translation worker keeps at most 256 MB of freed MLX buffers instead of as much as MLX allows (`mlx_cache_limit` event): on one 88 s replay the worker grew from 3.3 to 14 GB, with the limit it stays under 3.2 GB, with the same Russian text and the same delays;
- Hebrew to Russian and Hebrew to English are the only translation directions: the target list holds Russian and English, another target saved by an earlier release reads as Russian with a notice, Ctrl+T no longer switches the CLI to Russian-to-Hebrew, and `--direction` accepts `he-ru` and `he-en` only;
- Whisper is removed from the app and the build: speech is recognized only by the bundled streaming model, first preparation downloads MiLMMT alone (2.22 GB instead of 3.83 GB), `mlx-whisper` and its dependencies (torch, numba, scipy, tiktoken) leave the lock, and `--asr-model` is gone; a manifest that lists Whisper still verifies without its files, and the app stops with a clear error if the bundled streaming model is missing;
- the streaming recognizer also hears the audio between the speech segments the VAD finds (only the recognizer: the VAD still decides where a phrase ends, and nothing else reads that audio), so quiet speech the VAD rejects is not lost; a card with such words closes after 2 s without a new word (`HEBREW_LIVE_ALL_AUDIO=0` restores the VAD-only feed);
- the phone check starts the adb service first, with a limit of 15 s, and only then asks `adb devices` (still 3 s), so a service that is down no longer has to start within the 3 s; the window says "adb did not answer in time" without naming the seconds;
- live translation waits for a number the Hebrew has not said yet: a translation word with a number the source has not heard is held back until the next Hebrew word (`HEBREW_LIVE_NUMBER_WAIT=0` switches it off);
- pressing Start runs one discarded translation call (`mt_prewarm` event), so a model whose memory macOS moved to disk while the window waited is back before the first phrase needs it;
- recognition of a growing group continues from its frozen sentences instead of writing the whole group again: the frozen text is forced as the start of the Whisper decode, which then runs without timestamp tokens (ivrit.ai eval-d1 and eval-whatsapp in 20 s windows: 941 instead of 949 and 1586 instead of 1598 word errors, 0.20-0.24 s less per decode; `HEBREW_LIVE_TAIL_ONLY=0` restores whole-group decodes; `experiments/tail-only`);
- a sentence the translation ends early keeps a number the model already translated when it is said up to 3 words later ("הקישו | 2" - "нажмите 2."): no false "(Уточнение: …)" and no wrong number in the next sentence; the last call of a card no longer shows an unfinished last word when it reaches its limit;
- a failing microphone block or a full queue of finished phrases no longer stops the session: the gap is recorded, the oldest waiting phrase is skipped and listening continues;
- finished sentences of a growing draft group stay on screen as shown: once two recognitions in a row agree on a sentence that is followed by more speech, its translation is frozen and only the rest of the group is translated again, continuing from the shown translation; a streaming preview no longer replaces a longer visible version; translation text is 17 px instead of 20 px (2026-10-29 call replay: finished sentences rewritten 296 -> 66, bubble collapses 424 -> 12; `HEBREW_LIVE_FREEZE_SENTENCES=0` restores whole-group re-translation, the split-worker pipeline keeps it);
- translation drives `mlx_lm.generate_step` directly instead of `stream_generate`: the same text and finish reasons (84 of 84 compared sequences identical), without the per-call wired-memory toggling that cost 0.33-0.46 s per translation (`HEBREW_LIVE_MT_GENERATE=stock` restores it);
- the translation token budget grows with the source (96-512 tokens instead of a fixed 256) and a translation that still reaches it is shown with an explicit `[…]` instead of being dropped (`HEBREW_LIVE_MT_MAX_TOKENS=256` restores the old limit);
- a streaming translation can be cancelled between tokens: the engine process polls for a cancel message, so an abandoned or stale generation ends within one token instead of being drained for seconds or the process being killed; a refresh overtaken by newer queued audio is stopped, and the split-worker MT queue serves closing, first, then refresh jobs (`HEBREW_LIVE_MT_INTERRUPT=0` restores finishing every translation, in order);
- draft recognition no longer computes Whisper word timestamps (identical text on 41 of 41 compared windows; `HEBREW_LIVE_TEXT_ONLY_DRAFT=0` restores them);
- a Whisper decode that has become a certain loop (a letter repeated 12 times, or a word sequence three times in a row) is stopped inside the decoding loop instead of after all 224 tokens, and the check now also covers final windows; the same texts are accepted (87 of 87 and 17 of 17 accepted real windows identical, identical statuses on all 116) and a looping window now costs 0.4 s instead of 1.1-1.2 s (`HEBREW_LIVE_LOOP_STOP=0` restores the post-decode check on drafts only);
- translation keeps one streaming detokenizer per tokenizer instead of building a new one per call (building it walks the whole vocabulary: 0.10 s; the fast generation path built two per call, which cancelled its own gain);
- a phrase group that never got any recognised text now shows "Speech was not recognized" instead of "final version unavailable";
- the loopback UI receives state over Server-Sent Events instead of polling every 150-200 ms, falling back to polling by itself (`HEBREW_LIVE_UI_PUSH=0` switches the stream off);
- the Whisper encoder runs its self-attention through `mx.fast.scaled_dot_product_attention` by default (FLEURS Hebrew, 792 clips: WER 19.15 -> 19.18 %, CI -0.03...+0.07 pp; 16-19 % faster calls for windows up to 10 s; `HEBREW_LIVE_FUSED_ENCODER=0` restores the upstream implementation, and an unqualified `mlx-whisper` still falls back to it by itself);
- the first ASR snapshot of a fragment is taken after 1.0 s of speech instead of 1.5 s: the first visible draft appears 24 % sooner (median 2.38 -> 1.80 s on a 7-minute real replay, 1.71 s together with the fused encoder) but is about one word shorter and sometimes less exact; final texts are unchanged (the old value stays in a saved setting, or `HEBREW_LIVE_TIMING=1.5,1,0,4,0.6`);
- the desktop engine build refuses an MLX wheel without the macOS 26 neural-accelerator kernels (`macosx_26_0`);
- the speech detector hears its input amplified six times, so a speakerphone voice 10-20 dB quieter than the near speaker is no longer dropped before recognition (a real 280 s call: 45 instead of 39 of 47 reference lines reached recognition, unchanged first-draft latency); recognition still receives the original audio, and synthetic white/pink noise, mains hum and clicks up to -30 dBFS still produce no speech;
- a translation that repeats a phrase as many times as the speaker did ("זה הבעיה, זה הבעיה, זה הבעיה") is no longer cut as a generation loop; three real closing translations lost their whole phrase this way, and a loop still stops at one copy more than the source has.

### Added

- `he-ru listen --phone` (or `HEBREW_LIVE_INPUT=phone`): the other side of a phone call taken digitally from an Android phone over USB through `scrcpy --audio-source=voice-call-downlink`, instead of the microphone;
- a Microphone / Phone switch in the live window before recording starts, saved as `input_source`: choosing the phone asks `adb devices` (3 s limit) and names what is missing (no cable, USB debugging not allowed, several devices, no scrcpy or adb, ...); Start stays off until the phone is ready, a phone that is gone when Start is pressed returns the window to the ready state with the reason, and a session whose phone audio stops ends with the reason instead of silently; the source is decided when Start is pressed, so a waiting session follows the switch; `--phone` and `HEBREW_LIVE_INPUT=phone` still force the phone and lock the switch;
- the owner's vocabulary (`vocabulary.json` in the data folder; `HEBREW_LIVE_VOCABULARY=0` ignores it): translation gets the entries that occur in the phrase together with their translations; handing the words to recognition as a prompt is off (`HEBREW_LIVE_VOCABULARY_ASR=1`) because a 29-term list raised word errors on speech without those words by 19-25 %; an empty vocabulary changes nothing;
- `number_guard`: compares the numbers of a phrase and of its translation; a closed phrase (frozen sentences included) whose translation lost or added a figure gets a calm note under its bubble, "Check the number: 30", separate from the failed-phrase status, and a `number_mismatch` event with the figures only; a growing phrase gets no note (`HEBREW_LIVE_NUMBER_CHECK=0` switches the check off);
- a vocabulary editor in the live window settings: list, add (Hebrew with Russian and/or English), edit and delete, at most 500 entries, a repeated Hebrew word replaces the old entry, an unreadable `vocabulary.json` is never overwritten, and two-letter words carry a warning that prefixes can make them match other words; the running engine re-reads the file when it changes, before its next translation, without a restart (`vocabulary_loaded` event, `terms` in `mt_generation`);
- diagnostics: `mlx_runtime` (wheel tags, device), `mt_generation`, `mt_cancel`, `mt_interrupted`, `mt_prioritized`; `scripts/diagnose_latency.py` now reports time to the first visible draft, normalized erasure, time to stable words, lost-speech rate, slow-down over time and the new events;
- opt-in experiments, all off by default: `HEBREW_LIVE_LOOP_TRIM=1` (a Whisper decode that ends in a loop keeps the words before it, and a closing decode that loops gets one retry at temperature 0.3), `HEBREW_LIVE_SENTENCE_SPLIT=1` (a growing group closes at a sentence end two snapshots agree on, with that text, and the live UI keeps such sentences in one bubble with the still open text grey), `HEBREW_LIVE_CALM_DRAFTS=1` (the live UI keeps a shown translation until a refresh is complete and fades in only changed words), `HEBREW_LIVE_MT_SPECULATE=1` (drafting from the previous translation, 0.81x time but not output-identical), `HEBREW_LIVE_HOLD_LAST_WORD=1`, `HEBREW_LIVE_TIMING=first,interval,0,fragment,silence`;
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
