"""Where do the ~0.45 s before the first MT token go? prefill vs cache creation vs the stream_generate wrapper."""
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
from mlx_lm import load, stream_generate
from mlx_lm.models.cache import make_prompt_cache
from mlx_lm.sample_utils import make_sampler

import corpus
from hebrew_live.translation import configure, prompt

model, tok = load(str(ROOT / 'models' / 'milmmt-4b-4bit'))
configure(tok, 'milmmt')
refs = corpus.references()


def T(fn, n=9, warm=3):
    for _ in range(warm):
        fn()
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        mx.synchronize()
        xs.append(time.perf_counter() - t)
    return f'min {min(xs):.3f}  med {st.median(xs):.3f}'


for k in (1, 4, 8):
    text = ' '.join(refs[:k])
    ids = prompt(tok, 'milmmt', text, 'he-en')
    ids_mx = mx.array(ids)[None]
    print(f'--- {k} sentences: {len(text.split())} words, {len(ids)} prompt tokens')
    print('  tokenizer.encode            ', T(lambda: prompt(tok, 'milmmt', text, 'he-en')))
    print('  make_prompt_cache           ', T(lambda: make_prompt_cache(model)))

    def prefill():
        c = make_prompt_cache(model)
        o = model(ids_mx, cache=c)
        mx.eval(o)

    print('  prefill forward (+cache)    ', T(prefill))
    c = make_prompt_cache(model)
    o = model(ids_mx, cache=c)
    mx.eval(o)
    nxt = mx.argmax(o[:, -1], axis=-1)
    box = {'o': o}

    def step():
        box['o'] = model(nxt[:, None], cache=c)
        mx.eval(box['o'])

    print('  one decode step (warm cache)', T(step, 15))

    def sg(max_tokens):
        def fn():
            for _ in stream_generate(model, tok, prompt=ids, max_tokens=max_tokens, sampler=make_sampler(temp=0)):
                pass
        return fn

    print('  stream_generate max_tokens=1 ', T(sg(1)))
    print('  stream_generate max_tokens=17', T(sg(17)))
