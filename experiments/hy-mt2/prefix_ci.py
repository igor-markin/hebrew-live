"""Paired 95 % bootstrap interval of the mean rewrite share (prefixes.py) between two runs, over sentences.

    .venv/bin/python experiments/hy-mt2/prefix_ci.py A.json B.json
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from prefixes import rewrite

a, b = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
rng = random.Random(1)
for pair in ('he-en', 'he-ru'):
    keys = [k for k in a[pair] if k in b.get(pair, {})]

    def per_sentence(run):
        out = []
        for k in keys:
            vals = [rewrite(p['text'], n['text']) for p, n in zip(run[pair][k], run[pair][k][1:])]
            vals = [v for v in vals if v is not None]
            out.append(sum(vals) / len(vals))
        return out
    x, y = per_sentence(a), per_sentence(b)
    d = [j - i for i, j in zip(x, y)]
    boot = sorted(sum(d[rng.randrange(len(d))] for _ in d) / len(d) for _ in range(2000))
    print(f'{pair}: rewrite B - A {sum(d) / len(d):+.3f} (95 % interval {boot[50]:+.3f} .. {boot[1949]:+.3f}), {len(d)} sentences')
