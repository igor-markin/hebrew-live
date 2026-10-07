"""Plan 1.6 / 3.7: how a tolerance for drafted tokens trades identity, speed and stability.

Per reference the source grows by two words per step. The plain chain translates every
prefix from scratch. For each tolerance (nats) a second chain translates every prefix with
the previous step's own output as the draft. Reported per tolerance: share of steps whose
text equals plain greedy, deleted-word ratio between consecutive versions (normalised
erasure) for plain vs drafted, paired time ratio, accepted share of proposed tokens.

    JOIN=3 MARGINS="0 0.3 0.7 1.5" .venv/bin/python experiments/nn-audit-2026-10/mt_speculate_tolerance.py he-ru
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
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent))
import mlx.core as mx
from mlx_lm import load
from mlx_lm.sample_utils import make_sampler

import corpus
from diagnose_latency import erasure
from hebrew_live import mt_generate, mt_speculate
from hebrew_live.translation import configure, prompt

direction = sys.argv[1] if len(sys.argv) > 1 else 'he-ru'
margins = [float(x) for x in os.environ.get('MARGINS', '0 0.3 0.7 1.5').split()]
join = int(os.environ.get('JOIN', 3))
model, tok = load(str(ROOT / 'models' / 'milmmt-4b-4bit'))
configure(tok, 'milmmt')
base = [r for r in corpus.references() if len(r.split()) >= 6]
refs = [' '.join(base[i:i + join]) for i in range(0, len(base) - join + 1, join)]


def run(text, hint=None, margin=0.):
    ids = prompt(tok, 'milmmt', text, direction)
    limit = mt_generate.max_tokens_for(len(tok.encode(text, add_special_tokens=False)))
    stats = {}
    step = mt_speculate.step_for(tok.encode(hint, add_special_tokens=False), stats, margin) if hint else None
    began = time.perf_counter()
    pieces = list(mt_generate.generate(model, tok, ids, max_tokens=limit, sampler=make_sampler(temp=0), step=step))
    mx.synchronize()
    return ''.join(p for p, _ in pieces).strip(), time.perf_counter() - began, stats


def chain_erasure(versions):
    deleted = sum(erasure(a.split(), b.split()) for a, b in zip(versions, versions[1:]))
    return deleted, len(versions[-1].split())


prefixes = []
for ref in refs:
    words = ref.split()
    prefixes.append([' '.join(words[:min(n, len(words))]) for n in range(4, len(words) + 2, 2)])
run(prefixes[0][0])
plain = [[run(text)[0] for text in steps] for steps in prefixes]
plain_deleted = sum(chain_erasure(v)[0] for v in plain)
plain_words = sum(chain_erasure(v)[1] for v in plain)
print(f'{direction}: {sum(len(s) for s in prefixes)} steps over {len(refs)} phrases; '
      f'plain erasure {plain_deleted}/{plain_words} = {plain_deleted / plain_words:.2f} deleted words per final word')
for margin in margins:
    same = total = proposed = accepted = 0
    ratios = []
    chains = []
    for steps, reference in zip(prefixes, plain):
        chain = [reference[0]]
        for j in range(1, len(steps)):
            order = ['A', 'B']
            random.shuffle(order)
            timing = {}
            for who in order:
                if who == 'A':
                    timing['A'] = run(steps[j])[1]
                else:
                    text, timing['B'], stats = run(steps[j], chain[-1], margin)
            chain.append(text)
            ratios.append(timing['B'] / timing['A'])
            same += text == reference[j]
            total += 1
            proposed += stats.get('proposed', 0)
            accepted += stats.get('accepted_drafts', 0)
        chains.append(chain)
    deleted = sum(chain_erasure(v)[0] for v in chains)
    print(f'tolerance {margin:4.1f}: identical to plain {same}/{total} ({same / total:.0%}); '
          f'erasure {deleted}/{plain_words} = {deleted / plain_words:.2f}; time ratio median {st.median(ratios):.2f} '
          f'(p10 {sorted(ratios)[len(ratios) // 10]:.2f}, p90 {sorted(ratios)[-len(ratios) // 10 - 1]:.2f}); '
          f'accepted {accepted}/{proposed}')
