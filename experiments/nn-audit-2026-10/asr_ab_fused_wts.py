"""2x2 factorial, randomised arm order, idle-gated: {stock, fused attention} x {word timestamps on (app), off}."""
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
import mlx_whisper
from mlx_whisper.transcribe import ModelHolder

import corpus
from gated import run_gated
from hebrew_live.whisper_reuse import reuse_alignment
from whisper_patches import set_fused

P = str(ROOT / 'models' / 'asr')
model = ModelHolder.get_model(P, mx.float16)
audio = corpus.concat(corpus.load(), 0.3)
LENS = (1.5, 5, 10)


def call(L, wts):
    a = audio[:int(L * 16000)]
    t = time.perf_counter()
    with reuse_alignment(wts):
        mlx_whisper.transcribe(a, path_or_hf_repo=P, language='he', task='transcribe', temperature=0.0,
                               word_timestamps=wts, condition_on_previous_text=False, verbose=None)
    mx.synchronize()
    return time.perf_counter() - t


ARMS = [(0, 1), (1, 1), (0, 0), (1, 0)]   # (fused, word_timestamps)
for f, w in ARMS:
    set_fused(model, bool(f))
    [call(5, bool(w)) for _ in range(2)]


def one_round():
    r = {}
    order = ARMS[:]
    random.shuffle(order)
    for f, w in order:
        set_fused(model, bool(f))
        for L in LENS:
            r[(f, w, L)] = call(L, bool(w))
    set_fused(model, False)
    return r


acc, tried = run_gated(one_round, want=10, budget=420)
print(f'accepted rounds: {len(acc)} of {tried}  (idle>=62% before/after, randomised arm order)')
g = lambda k: [a[k] for a in acc]
print('ASR call seconds  min / median     [fused? , word-timestamps?]')
for L in LENS:
    for f, w in ARMS:
        if acc:
            print(f'  {L:4} s  fused={f} wts={w}: {min(g((f, w, L))):.3f} / {st.median(g((f, w, L))):.3f}')
