"""Paired A/B: shipped mlx_lm.stream_generate vs mlx_lm.generate.generate_step (same tokens?).

Each round runs A and B in random order for three source sizes; the report is the paired
ratio per round, which is robust to background load drift.
"""
import os
import random
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
import mlx.core as mx
from mlx_lm import load, stream_generate
from mlx_lm.generate import generate_step
from mlx_lm.sample_utils import make_sampler

import corpus
from hebrew_live.translation import configure, prompt

model, tok = load(str(ROOT / 'models' / 'milmmt-4b-4bit'))
configure(tok, 'milmmt')
EOS = set(tok.eos_token_ids)
refs = corpus.references()


def A(ids):
    t0 = time.perf_counter()
    first = None
    out = []
    for r in stream_generate(model, tok, prompt=ids, max_tokens=256, sampler=make_sampler(temp=0)):
        if r.finish_reason is None:
            if first is None:
                first = time.perf_counter() - t0
            out.append(int(r.token))
    mx.synchronize()
    return out, first, time.perf_counter() - t0


def B(ids):
    arr = mx.array(ids)
    t0 = time.perf_counter()
    first = None
    out = []
    for tkn, lp in generate_step(arr, model, max_tokens=256, sampler=make_sampler(temp=0)):
        t = int(tkn)
        if first is None:
            first = time.perf_counter() - t0
        if t in EOS:
            break
        out.append(t)
    mx.synchronize()
    return out, first, time.perf_counter() - t0


SIZES = (1, 4, 8)
P = {k: prompt(tok, 'milmmt', ' '.join(refs[:k]), 'he-en') for k in SIZES}
for k in SIZES:
    A(P[k])
    B(P[k])
rounds = []
allsame = True
for rep in range(10):
    r = {}
    for k in SIZES:
        order = ['A', 'B']
        random.shuffle(order)
        for o in order:
            out, f, t = (A if o == 'A' else B)(P[k])
            r[(o, k)] = (f, t)
            r[('out', o, k)] = out
        allsame &= r[('out', 'A', k)] == r[('out', 'B', k)]
    rounds.append(r)
print('token-identical A vs B in all rounds/sizes:', allsame)
for k in SIZES:
    ntok = len(rounds[0][('out', 'A', k)])
    rt = [r[('B', k)][1] / r[('A', k)][1] for r in rounds]
    rf = [r[('B', k)][0] / r[('A', k)][0] for r in rounds]
    ta = [r[('A', k)][1] for r in rounds]
    tb = [r[('B', k)][1] for r in rounds]
    print(f'  {sum(len(x.split()) for x in refs[:k]):3d} words {ntok:3d} tok | paired total-time ratio B/A: '
          f'median {st.median(rt):.2f} (B faster in {sum(x < 1 for x in rt)}/10) | first-token ratio median '
          f'{st.median(rf):.2f} | abs total A med {st.median(ta):.2f}s min {min(ta):.2f}s | B med '
          f'{st.median(tb):.2f}s min {min(tb):.2f}s')
