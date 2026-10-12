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
| `fleurs_asr.py {whisper,parakeet} OUT.json` | hypotheses for FLEURS he_il test (792 clips): Whisper Turbo as the app runs it (`--fused` for the fused encoder) or Parakeet-he (run it with the separate `venv-parakeet`); text goes to `OUT.json`, keep it outside the repo |
| `flores_mt.py {4bit,5bit,1b8bit} OUT.json [--units REF.json]` | translations of 300 seeded FLORES-200 devtest sentences (he-en, he-ru) or of own reference units by one MiLMMT build, through `Engine.translate`; one MT model at a time |
| `apple_mt.py OUT.json [--units REF.json] [--loop SECONDS] [--watch-memory]` (+ `apple_mt.swift`) | Apple Translation (on device, he-en/he-ru) over the same sentences as `flores_mt.py`, same OUT.json schema (`first` = `total`, no tokens); `--loop` is background load for the ASR contention run; the Swift helper is built into `~/Library/Caches/hebrew-live-refs/apple_mt` |
| `ivrit_extract.py DIR` | unpack an ivrit.ai eval parquet (`ivrit-eval-d1`, `ivrit-eval-whatsapp` in the references folder) into 16 kHz WAV files and `texts.json`; run it with `venv-parquet/bin/python -I -B` (pyarrow lives only there) |
| `ivrit_eval_asr.py {d1,whatsapp} OUT.json [--fused] [--mode {leaderboard,app}]` | whole recordings of the ivrit.ai eval sets through Whisper Turbo as the app loads it (`leaderboard`: mlx-whisper defaults; `app`: greedy, no conditioning); score with `compare.py asr ... --set ivrit-d1` or `ivrit-whatsapp` |
| `compare.py {asr,mt} A.json B.json` | paired comparison with a bootstrap 95 % interval: WER per clip (asr), chrF++ per sentence (mt), timings |
| `normalize.py`, `metrics.py` | ivrit.ai-leaderboard text normalisation, WER, chrF++ (no dependencies); `test_metrics.py` is run with `python -m unittest discover -s experiments/corpus` |

`e2e_ab.py` honours `E2E_VARIANTS` and `E2E_MODELS`. Saved preferences (`<models>/../.local-settings/preferences.json`) override `HEBREW_LIVE_TIMING`, so schedule variants must run with `E2E_MODELS` pointing at a models folder of symlinks that has no `.local-settings` beside it.

Rollback switches used by `e2e_ab.py` (all default to the new behaviour): `HEBREW_LIVE_MT_GENERATE=stock`,
`HEBREW_LIVE_MT_INTERRUPT=0`, `HEBREW_LIVE_TEXT_ONLY_DRAFT=0`, `HEBREW_LIVE_MT_MAX_TOKENS=256`,
`HEBREW_LIVE_MT_SPECULATE=0`, `HEBREW_LIVE_LOOP_STOP=0`, `HEBREW_LIVE_FUSED_ENCODER=0`, `HEBREW_LIVE_TIMING=1.5,1,0,4,0.6` (the last two: defaults since 2026-10-12 are the fused encoder and `first_seconds` 1.0; the `stock` variant pins the old values, `previous` is Phase 1 with the old values only). Experiment switches (default off):
`HEBREW_LIVE_HOLD_LAST_WORD=1`, `HEBREW_LIVE_MT_SPECULATE=1` (+ `HEBREW_LIVE_MT_SPECULATE_TOLERANCE=0.3`); `HEBREW_LIVE_TIMING=first,interval,0,fragment,silence` sets the schedule.

## External references (outside the repository)

Downloaded 2026-10-11 into `~/Library/Caches/hebrew-live-refs/` (next to the reference Whisper environment). They are evaluation material and candidate models, not product models: `models/manifest.json` is unchanged. Large files were checked against the SHA-256 published by the Hugging Face Hub.

| Directory | Source (pinned) | Files | SHA-256 | License |
| --- | --- | --- | --- | --- |
| `parakeet-tdt-0.6b-v3-he/` | `thewh1teagle/parakeet-tdt-0.6b-v3-he` @ `003720491ed0d2699a4c9e204b9ca19d6f1fe8a1` | `model.safetensors` (2.51 GB) and config/tokenizer files; the `.nemo` (2.51 GB) and `q8_0.gguf` (0.72 GB) variants are not downloaded | `model.safetensors` `3a5bdd304d75f6ab4b7eb71db9b66f53179112681cdddd4545d5bb55461c7e31` | CC-BY-4.0 |
| `fleurs-he_il/` | `google/fleurs` (dataset) @ `70bb2e84b976b7e960aa89f1c648e09c59f894dd` | `data/he_il/audio/test.tar.gz` (0.39 GB, not extracted), `data/he_il/test.tsv` | `test.tar.gz` `f09f2335973d7ff5469c0e88fc37b528e66ec2ff2af5346438daacb3fbd84a53` | CC-BY-4.0 |
| `flores200/`, `flores200-devtest/` | `https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz` (25.6 MB, last modified 2022-07-14); only `devtest/{heb_Hebr,eng_Latn,rus_Cyrl}.devtest` extracted, 1012 lines each | archive | archive `b8b0b76783024b85797e5cc75064eb83fc5288b41e9654dabc7be6ae944011f6` (the Hub does not host it, so there is no published hash to compare with); devtest hashes below | not checked |
| `milmmt-4b-5bit-mlx/` (deleted 2026-10-12, download again to repeat) | `translate-studio/MiLMMT-46-4B-v1.0-5bit-MLX` @ `8227b351ad0580e35ff3f92f5f8c623da1788c48` | all files (2.67 GB weights) | `model.safetensors` `099185b39e9d37fd944c8a1dc710a960943a431b88a322946da7a33f143173a5`, `tokenizer.json` `48a9afc4c8abd25310cbc644959cff42b119dc95aaf8543279952300c5938bc4` | Gemma terms |
| `ivrit-eval-d1/` (downloaded 2026-10-12) | `ivrit-ai/eval-d1` (dataset) @ `7899b0427df2e1d722c043ac41211ac7da15c737`; 17 podcast recordings, 85.5 min, hand-transcribed | `data/test-00000-of-00001.parquet` (82.2 MB) | `cbf680204924f02edb1bbdd13e4d0d1d201e033f993ae62d3b65c772a432c854` (equals the hash the Hub publishes) | ivrit.ai license, see below |
| `ivrit-eval-whatsapp/` (downloaded 2026-10-12) | `ivrit-ai/eval-whatsapp` (dataset) @ `1267f61b95b2ecda9368cd620befbdaf8ad60bd8`; 54 WhatsApp voice messages (ogg/opus), 70.7 min, expert-transcribed | `data/test-00000-of-00001.parquet` (9.8 MB), `ivritai_dataset_license.txt` (`41cbf9e7ad0e3f5c0a2012bf06472e1813654aa3996ab33838b0e4b0c3de09aa`) | `13f3923498e805fe220a12126b8530b4de4c1aa3839bf219c6af4868da721b4e` (equals the Hub hash) | ivrit.ai v2, see below |
| `milmmt-1b-8bit-mlx/` (downloaded and deleted 2026-10-12, download again to repeat) | `translate-studio/MiLMMT-46-1B-v1.0-8bit-MLX` @ `d11e0c590940f193fbd312d305951969e22c1453` | all files (1.06 GB weights) | `model.safetensors` `135a413a26f411142378cb78df25e1124a0f304a4a4237dd163df8bd072c8d46`, `tokenizer.json` `48a9afc4c8abd25310cbc644959cff42b119dc95aaf8543279952300c5938bc4` (equal to the Hub hashes) | Gemma terms |
| `venv-parquet/` | `pyarrow` 26.0.0 from PyPI in a throwaway virtual environment outside the project | | | |

**ivrit.ai license.** The dataset cards say it "enables broad research and commercial use". The licence text in `ivritai_dataset_license.txt` (v2, 2024-10-01) is narrower: CC BY 4.0, but the data "may only be used, modified and distributed for the express purpose of either (a) training AI models, or (b) academic research", and not to imitate the voice of the people in it. Evaluating a model for a product is not named in either purpose, so the audio and texts stay in the references folder, are never copied into the repository or a release, and reports carry numbers only.

Full devtest hashes: `heb_Hebr.devtest` `78e8786afa6dbd3a207bca7b8274d8efc1ed9e513a0c5dd7f471ee6119d34423`, `eng_Latn.devtest` `612e9fbe87997617c0fa8fa8929654a4f49b728d96738112c2b86ef6a1d78d88`, `rus_Cyrl.devtest` `cdc706ed862d1d35d8d67cfda0b396766646885434958b18291aa760ff1bb59e`.

The Parakeet runtime (NeMo or ONNX) is not installed; it is set up when plan items 4.2 / 3.10 start.
