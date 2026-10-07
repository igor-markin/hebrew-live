"""MiLMMT 4-bit through the app's Engine.translate: timing for growing phrases plus a max_tokens=256 probe.

Run with ``probe`` as the only argument to skip the timing part.
"""
import os
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
import mlx.core as mx

import corpus
from hebrew_live.cli import Engine


class Log:
    def event(self, n, **k):
        pass

    def error(self, e):
        pass


e = Engine(ROOT / 'models', Log(), language='he', role='mt')
e.warmup()
refs = corpus.references()


def run(text, direction):
    e.direction = direction
    e.topic = 'none'
    e.translation_context = []
    t0 = time.perf_counter()
    first = None
    out = ''
    last = '?'
    for piece, reason in e.translate(text):
        if piece and first is None:
            first = time.perf_counter() - t0
        out += piece
        last = reason
    mx.synchronize()
    tot = time.perf_counter() - t0
    return first or tot, tot, len(e.tokenizer.encode(out, add_special_tokens=False)), len(text.split()), last


if sys.argv[1:] != ['probe']:
    for direction in ('he-en', 'he-ru'):
        print('==', direction, ' (median of 3 after 1 warm run)')
        for k in (1, 2, 4, 8, 12):
            text = ' '.join(refs[:k])
            rs = [run(text, direction) for _ in range(4)][1:]
            f = st.median(r[0] for r in rs)
            t = st.median(r[1] for r in rs)
            nt = rs[-1][2]
            nw = rs[-1][3]
            print(f'  {nw:3d} src words -> {nt:3d} out tok | first token {f:.3f}s | total {t:.3f}s '
                  f'| decode {(nt - 1) / max(t - f, 1e-6):5.1f} tok/s | finish={rs[-1][4]}')
print('== max_tokens=256 truncation probe (no timing): source = 8 and 12 TTS sentences')
for d in ('he-en', 'he-ru', 'he-ar', 'he-ja', 'he-ko', 'he-hi', 'he-ta', 'he-th', 'he-my', 'he-km', 'he-lo'):
    row = []
    for k in (8, 12):
        r = run(' '.join(refs[:k]), d)
        row.append(f'{r[3]}w->{r[2]}tok finish={r[4]}')
    print(f'  {d:6s}', ' | '.join(row))
print('peak MLX GB', round(mx.get_peak_memory() / 1e9, 2))
