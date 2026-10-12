"""Plan 1.6: previous-translation drafting vs plain greedy, on growing source prefixes.

For every synthetic reference, sources grow by 2 words per step (like successive ASR
refreshes); each step is translated plainly and with the previous step's translation as the
draft. Reports token identity, paired time ratio (A/B interleaved in random order) and the
draft acceptance rate. Run alone; gate on an idle CPU.

    .venv/bin/python experiments/nn-audit-2026-10/mt_speculate_ab.py [he-en|he-ru]
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
from mlx_lm import load
from mlx_lm.sample_utils import make_sampler

import corpus
import gated
from hebrew_live import mt_generate, mt_speculate
from hebrew_live.translation import configure, prompt

direction = sys.argv[1] if len(sys.argv) > 1 else 'he-en'
model, tok = load(str(ROOT / 'models' / 'milmmt-4b-4bit'))
configure(tok, 'milmmt')
JOIN = int(os.environ.get('JOIN', 1))  # concatenate N consecutive references: longer, live-sized phrases
_refs = [r for r in corpus.references() if len(r.split()) >= 6]
refs = [' '.join(_refs[i:i + JOIN]) for i in range(0, len(_refs) - JOIN + 1, JOIN)] if JOIN > 1 else _refs
STEP = 2


def run(text, hint_ids=None, stats=None):
    ids = prompt(tok, 'milmmt', text, direction)
    limit = mt_generate.max_tokens_for(len(tok.encode(text, add_special_tokens=False)))
    step = mt_speculate.step_for(hint_ids, stats) if hint_ids else None
    tokens = []
    sampler = make_sampler(temp=0)
    began = time.perf_counter()
    first = None
    for piece, reason in mt_generate.generate(model, tok, ids, max_tokens=limit, sampler=sampler, step=step):
        if first is None:
            first = time.perf_counter() - began
        tokens.append((piece, reason))
    mx.synchronize()
    return tokens, first, time.perf_counter() - began


def encode(pieces):
    return tok.encode(''.join(p for p, _ in pieces).strip(), add_special_tokens=False)


# Plain translation of each prefix (also the draft source for the next step).
cases = []
for ref in refs:
    words = ref.split()
    previous = None
    for n in range(STEP * 2, len(words) + STEP, STEP):
        text = ' '.join(words[:min(n, len(words))])
        plain, _, _ = run(text)
        if previous is not None:
            cases.append((text, previous, plain))
        previous = encode(plain)
print(f'{direction}: {len(cases)} (previous -> next) pairs from {len(refs)} references')

identical = 0
mismatch = []
stats_all = []


def one_round():
    out = {}
    for text, hint, plain in cases:
        order = ['A', 'B']
        random.shuffle(order)
        for o in order:
            stats = {}
            tokens, first, total = run(text, hint if o == 'B' else None, stats if o == 'B' else None)
            out.setdefault(o, []).append((first, total))
            if o == 'B':
                out.setdefault('stats', []).append(stats)
                out.setdefault('tokens', []).append(tokens)
    return out


for text, hint, plain in cases:
    stats = {}
    tokens, _, _ = run(text, hint, stats)
    same = ''.join(p for p, _ in tokens) == ''.join(p for p, _ in plain) and tokens[-1][1] == plain[-1][1]
    identical += same
    if not same:
        mismatch.append(text)
    stats_all.append(stats)
print(f'text identical with drafting: {identical}/{len(cases)}')
prop = sum(s.get('proposed', 0) for s in stats_all)
acc = sum(s.get('accepted_drafts', 0) for s in stats_all)
print(f'draft tokens proposed {prop}, accepted {acc} ({acc / max(prop, 1):.0%}); rounds {sum(s.get("speculative_rounds", 0) for s in stats_all)}')

rounds, tried = gated.run_gated(one_round, want=int(os.environ.get('ROUNDS', 4)), budget=1500)
print(f'accepted rounds {len(rounds)}/{tried} (idle gate)')
ratios = []
firsts = []
totals_a = []
totals_b = []
for r in rounds:
    for (fa, ta), (fb, tb) in zip(r['A'], r['B']):
        ratios.append(tb / ta)
        firsts.append(fb / fa)
        totals_a.append(ta)
        totals_b.append(tb)
if ratios:
    print(f'paired total-time ratio B/A: median {st.median(ratios):.2f}, p10 {sorted(ratios)[len(ratios)//10]:.2f}, '
          f'p90 {sorted(ratios)[-len(ratios)//10 - 1]:.2f}; first-token ratio median {st.median(firsts):.2f}')
    print(f'sum time A {sum(totals_a):.1f}s B {sum(totals_b):.1f}s -> {sum(totals_b) / sum(totals_a):.2f}x')
for t, hint, plain in [c for c in cases if c[0] in mismatch][:3]:
    spec, _, _ = run(t, hint)
    a, b = ''.join(p for p, _ in plain), ''.join(p for p, _ in spec)
    k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    print(f'MISMATCH ({len(t.split())} words) first differing char {k}: plain ...{a[max(0, k-25):k+25]!r} | spec ...{b[max(0, k-25):k+25]!r}')
