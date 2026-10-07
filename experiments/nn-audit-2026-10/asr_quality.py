"""WER / identity probe on the 12 synthetic clips for encoder variants.

Variants: stock; fused attention; naive truncation (len + 1.5 s, no floor); context floors
1000 (20 s), 750 (15 s), 500 (10 s).  Part 1: full clips vs reference (WER).  Part 2: partial
windows 1.5/2.5/3.5 s (what live drafts look like) vs the stock transcript of the same window.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(Path(__file__).parent))
import mlx.core as mx
import mlx_whisper
from mlx_whisper.transcribe import ModelHolder

import corpus
from whisper_patches import context, install_context_patch, set_fused

P = str(ROOT / 'models' / 'asr')
model = ModelHolder.get_model(P, mx.float16)
install_context_patch()


def norm(t):
    t = re.sub(r'[֑-ׇ]', '', t)
    t = re.sub(r'[^\w\s]', ' ', t.casefold())
    return t.split()


def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)], len(r)


VARIANTS = {'stock': ('stock', None), 'fused': ('fused', None), 'naive len+1.5s': ('naive', None),
            'floor 1000 (20s)': ('ctx', 1000), 'floor 750 (15s)': ('ctx', 750), 'floor 500 (10s)': ('ctx', 500)}


def run(audio, variant):
    kind, n = VARIANTS[variant]
    set_fused(model, kind == 'fused')
    if kind == 'naive':
        n = min(1500, int(len(audio) / 16000 * 50) + 75)
    context(n)
    r = mlx_whisper.transcribe(audio, path_or_hf_repo=P, language='he', task='transcribe', temperature=0.0,
                               word_timestamps=False, condition_on_previous_text=False, verbose=None)
    context(None)
    set_fused(model, False)
    return r['text'].strip()


clips = corpus.load()
print('=== full clips (n=12) WER vs reference; transcripts identical to stock')
outs = {v: [run(a, v) for _, a, _ in clips] for v in VARIANTS}
for v in VARIANTS:
    e = sum(wer(ref, o)[0] for (_, _, ref), o in zip(clips, outs[v]))
    t = sum(wer(ref, o)[1] for (_, _, ref), o in zip(clips, outs[v]))
    same = sum(norm(o) == norm(b) for o, b in zip(outs[v], outs['stock']))
    print(f'  {v:18s} WER {e}/{t} = {100 * e / t:5.2f}%   identical-to-stock {same}/12')
print('=== partial windows 1.5/2.5/3.5 s (live drafts): word diff vs stock transcript of the same window')
for v in VARIANTS:
    if v == 'stock':
        continue
    d = t = w = nw = 0
    for _, a, _ in clips:
        for L in (1.5, 2.5, 3.5):
            if len(a) / 16000 < L + .2:
                continue
            x = a[:int(L * 16000)]
            b = run(x, 'stock')
            y = run(x, v)
            e_, n_ = wer(b, y) if norm(b) else (len(norm(y)), 1)
            d += e_
            t += max(n_, 1)
            nw += 1
            w += e_ > 0
    print(f'  {v:18s} word-diff {d}/{t} = {100 * d / t:5.2f}%   windows with any diff {w}/{nw}')
