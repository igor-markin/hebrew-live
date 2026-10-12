"""Plan 1.6 cost model: time of one forward pass over M tokens with a warm ~80-token cache.

If verifying M drafted tokens costs far more than one decode step, drafting cannot pay off.
    .venv/bin/python experiments/nn-audit-2026-10/mt_batch_cost.py
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
from mlx_lm import load
from mlx_lm.models import cache as kv

import corpus
from hebrew_live.mt_speculate import _greedy
from hebrew_live.translation import configure, prompt

model, tok = load(str(ROOT / 'models' / 'milmmt-4b-4bit'))
configure(tok, 'milmmt')
ids = prompt(tok, 'milmmt', ' '.join(corpus.references()[:3]), 'he-en')
print('prompt tokens', len(ids))


def forward_time(m, with_head=True, reps=12):
    out = []
    for _ in range(reps):
        cache = kv.make_prompt_cache(model)
        mx.eval(model(mx.array(ids)[None], cache=cache))
        mx.eval([c.state for c in cache])
        tokens = mx.array([1000 + i for i in range(m)])
        t0 = time.perf_counter()
        logits = model(tokens[None], cache=cache)
        choice = _greedy(logits[0] if with_head else logits[0][:, :8])
        mx.eval(choice)
        choice.tolist()
        out.append(time.perf_counter() - t0)
    return st.median(out), min(out)


for m in (1, 2, 4, 8, 12, 16, 24, 32):
    med, low = forward_time(m)
    print(f'M={m:2d}: median {med*1000:6.1f} ms  min {low*1000:6.1f} ms   per-token {med*1000/m:5.1f} ms')
