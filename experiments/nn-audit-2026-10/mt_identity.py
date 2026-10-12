"""Identity check for plan item 1.1: `mt_generate` (generate_step) vs stock `stream_generate`.

Compares the full sequence of yielded `(text, finish_reason)` pairs for the 12 synthetic
references, concatenations of 4 and 12 of them, in he-en, he-ru and he-my (Burmese, the
case that used to hit the 256-token limit). Run alone; one MLX job at a time.

    .venv/bin/python experiments/nn-audit-2026-10/mt_identity.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
from mlx_lm import load
from mlx_lm.sample_utils import make_sampler

import corpus
from hebrew_live import mt_generate
from hebrew_live.translation import configure, prompt

model, tok = load(str(ROOT / 'models' / 'milmmt-4b-4bit'))
configure(tok, 'milmmt')
refs = corpus.references()
texts = list(refs) + [' '.join(refs[:4]), ' '.join(refs)]


def run(impl, ids, max_tokens):
    os.environ['HEBREW_LIVE_MT_GENERATE'] = impl
    return list(mt_generate.generate(model, tok, ids, max_tokens=max_tokens, sampler=make_sampler(temp=0)))


bad = 0
total = 0
for direction in ('he-en', 'he-ru', 'he-my'):
    for text in texts:
        ids = prompt(tok, 'milmmt', text, direction)
        limit = mt_generate.max_tokens_for(len(tok.encode(text, add_special_tokens=False)))
        for max_tokens in (limit, 24):  # 24 forces the finish_reason == 'length' path
            a = run('stock', ids, max_tokens)
            b = run('fast', ids, max_tokens)
            total += 1
            if a != b:
                bad += 1
                print('MISMATCH', direction, max_tokens, len(a), len(b))
print(f'{total - bad}/{total} yielded sequences identical')
sys.exit(1 if bad else 0)
