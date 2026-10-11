# Corpus tooling (plan, Phase 0)

Local, opt-in tools. Audio stays in the app's archive (`~/Library/Application Support/Hebrew Live CLI`);
nothing here writes speech text, and reports carry counts and timings only. Run from the repository
root with `.venv/bin/python`; keep a single MLX job at a time.

| File | Purpose |
| --- | --- |
| `manifest.py` | build `manifest.json` (relative audio path, sha256, duration, date, scenario) from the session archive; labels already set are kept |
| `windows.py` | replay the audio ranges the shipped build transcribed (`live_asr` events) as 16 kHz arrays with the recorded text |
| `asr_window_identity.py SESSION_DIR` | do the current ASR defaults reproduce the recorded text on those windows (byte-identical, normalised, WER) |
| `asr_speed_ab.py SESSION_DIR [--reference REF.json]` | fused encoder attention on the real windows: identity vs stock, paired time, and WER against the reference |
| `asr_floor_probe.py SESSION_DIR FLOOR` | encoder context truncation (plan 3.1) on the real windows through the audit patch (not in the app): how far the transcript moves |
| `make_asr_reference.py AUDIO OUT.json` | reference transcript with ivrit.ai Large-v3 (faster-whisper, CPU int8, beam 5); run with the separate environment in `~/Library/Caches/hebrew-live-refs`; the JSON holds speech and stays in the app data root |
| `e2e_ab.py SESSION_DIR` | end-to-end A/B of the live pipeline at 1x on a real stretch: stock rollback switches vs current defaults, metrics from `scripts/diagnose_latency.py` |
| `normalize.py`, `metrics.py` | ivrit.ai-leaderboard text normalisation, WER, chrF++ (no dependencies); `test_metrics.py` is run with `python -m unittest discover -s experiments/corpus` |

Rollback switches used by `e2e_ab.py` (all default to the new behaviour): `HEBREW_LIVE_MT_GENERATE=stock`,
`HEBREW_LIVE_MT_INTERRUPT=0`, `HEBREW_LIVE_TEXT_ONLY_DRAFT=0`, `HEBREW_LIVE_MT_MAX_TOKENS=256`,
`HEBREW_LIVE_MT_SPECULATE=0`, `HEBREW_LIVE_LOOP_STOP=0`. Experiment switches (default off): `HEBREW_LIVE_FUSED_ENCODER=1`,
`HEBREW_LIVE_HOLD_LAST_WORD=1`, `HEBREW_LIVE_MT_SPECULATE=1` (+ `HEBREW_LIVE_MT_SPECULATE_TOLERANCE=0.3`), `HEBREW_LIVE_TIMING=first,interval,0,fragment,silence`.
