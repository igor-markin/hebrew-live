"""Plan 3.1 on real speech: how much does truncating the encoder context change the transcript?

Uses the audit's measurement patch (`experiments/nn-audit-2026-10/whisper_patches.py`); the app
does not contain this code. For every accepted ASR window of a session it transcribes with the
stock 30 s context and with `n = max(FLOOR, ceil((seconds + 1.5) * 50))` positions, and reports
how often the text is identical and how far it moves (WER of floor text against stock text), by
window length. Run alone (one MLX job); prints counts only.

    .venv/bin/python experiments/corpus/asr_floor_probe.py SESSION_DIR FLOOR   # e.g. 750 1000 1250
"""
import os
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path[:0] = [str(ROOT / 'src'), str(Path(__file__).parent), str(ROOT / 'experiments' / 'nn-audit-2026-10')]
import mlx.core as mx
import mlx_whisper
from mlx_whisper.transcribe import ModelHolder

import whisper_patches as patches
from metrics import wer
from normalize import normalize
from windows import windows

session, floor = Path(sys.argv[1]), int(sys.argv[2])
path = str(ROOT / 'models' / 'asr')
ModelHolder.get_model(path, mx.float16)
patches.install_context_patch()


def transcribe(audio):
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=path, language='he', task='transcribe', temperature=0.0,
                                    word_timestamps=False, condition_on_previous_text=False, verbose=None)
    return ''.join(s.get('text', '') for s in result['segments']).strip()


rows = []
for item in windows(session):
    seconds = len(item['audio']) / 16000
    patches.context(None)
    base = transcribe(item['audio'])
    patches.context(max(floor, min(1500, int((seconds + 1.5) * 50) + 1)))
    cut = transcribe(item['audio'])
    patches.context(None)
    rows.append((seconds, wer(base, cut), len(normalize(cut).split()), len(normalize(base).split())))
errors = [r[1] for r in rows if r[1] is not None]
print(f'floor {floor}: {len(rows)} windows, identical {sum(e == 0 for e in errors)}, '
      f'decile WER vs stock {[round(q, 2) for q in st.quantiles(errors, n=10)]}')
print(f'floor text >1.5x stock words in {sum(r[2] > 1.5 * max(r[3], 1) for r in rows)} windows, '
      f'<0.5x in {sum(r[2] < 0.5 * r[3] for r in rows)}, empty in {sum(r[2] == 0 for r in rows)}')
for low, high in ((0, 2), (2, 5), (5, 10), (10, 99)):
    values = [r[1] for r in rows if low <= r[0] < high and r[1] is not None]
    if values:
        print(f'  {low}-{high} s: n={len(values)}, median WER {st.median(values):.2f}, identical {sum(v == 0 for v in values)}')
