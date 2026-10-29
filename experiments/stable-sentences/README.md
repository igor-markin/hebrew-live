# Stable finished sentences

Replays a recorded session's ASR texts through the draft pipeline with the real
MiLMMT translator and counts how much the screen moves. ASR is not re-run, so both
variants see identical recognitions. Output goes to `out/` (ignored: it holds the
private call text).

```sh
PYTHONPATH=src .venv/bin/python experiments/stable-sentences/replay.py SESSION_DIR out/freeze.jsonl --until 1440
HEBREW_LIVE_FREEZE_SENTENCES=0 PYTHONPATH=src .venv/bin/python experiments/stable-sentences/replay.py SESSION_DIR out/baseline.jsonl --until 1440
cd experiments/stable-sentences && python3 compare.py out/baseline.jsonl out/freeze.jsonl
```

Result on the 2026-10-29 he-ru session, first 24 minutes (a phone call: IVR menu,
Hebrew, English and the speaker's own Hebrew), 847 recognitions, M5, serial pipeline:

| | whole group (before) | frozen sentences |
| --- | --- | --- |
| screen updates | 3822 | 1536 |
| finished sentence rewritten on screen | 296 | 66 |
| bubble shrank by more than 20 characters | 424 | 12 |
| MT calls / p50 / p95 | 701 / 0.55 s / 1.69 s | 689 / 0.54 s / 1.20 s |

The remaining rewrites are finished sentences that are not frozen yet: a sentence is
frozen only after two recognitions in a row agree on it, which kept the IVR menu digits
that a single early recognition dropped. A frozen sentence keeps its first translation;
the old pipeline's final re-translation of the whole group no longer replaces it.

The same replay on `stable-release` (alpha.4 code, both runs with the preview rule, so
only freezing differs): finished sentences rewritten 196 -> 66, bubble collapses 12 -> 13,
MT p50 0.49 -> 0.45 s, p95 1.47 -> 1.03 s.
