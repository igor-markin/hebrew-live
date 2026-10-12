"""Is the transcript identical with word timestamps off vs on (the app's two text branches)?"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
import mlx_whisper

import corpus
from hebrew_live.whisper_reuse import reuse_alignment

P = str(ROOT / 'models' / 'asr')


def tr(a, wt):
    with reuse_alignment(wt):
        r = mlx_whisper.transcribe(a, path_or_hf_repo=P, language='he', task='transcribe', temperature=0.0,
                                   word_timestamps=wt, condition_on_previous_text=False, verbose=None)
    if wt:   # the app's reconstruction from words
        return ''.join(w['word'] for s in r['segments'] for w in s.get('words', [])).strip()
    return ''.join(s.get('text', '') for s in r['segments']).strip()   # the app's text-only branch


def n(t):
    return re.sub(r'\s+', ' ', t).strip()


clips = corpus.load()
same_exact = same_ws = tot = 0
diffs = []
for cid, a, ref in clips:
    for L in (1.5, 2.5, 3.5, None):
        w = a if L is None else (a[:int(L * 16000)] if len(a) / 16000 > L + .2 else None)
        if w is None:
            continue
        x, y = tr(w, True), tr(w, False)
        tot += 1
        same_exact += (x == y)
        same_ws += (n(x) == n(y))
        if n(x) != n(y):
            diffs.append((cid, L, x, y))
print(f'windows compared: {tot}; byte-identical: {same_exact}; identical after whitespace normalisation: {same_ws}')
for d in diffs[:6]:
    print('DIFF', d[0], d[1], '|', d[2], '|', d[3])
