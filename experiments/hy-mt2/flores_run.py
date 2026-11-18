"""FLORES-200 devtest (the same 300 seeded sentences as `experiments/corpus/flores_mt.py`) through one model.

    .venv/bin/python experiments/hy-mt2/flores_run.py hy4 OUT.json [--mode greedy|rp|rec] [--seed 1]
    .venv/bin/python experiments/hy-mt2/flores_run.py milmmt OUT.json
    # with the two preceding sentences of the same article (own translations, as the app passes them)
    .venv/bin/python experiments/hy-mt2/flores_run.py hy4 OUT.json --context prefix|turns|background

OUT.json has the `flores_mt.py` schema, so `experiments/corpus/compare.py mt A.json B.json` scores it.
Keep OUT.json outside the repository (it holds FLORES text only, but the folder convention is the same).
With `--context`, rows also get `context` (how many preceding sentences went into the request).
"""
import argparse
import json
from pathlib import Path

from common import Translator, flores, require_memory

parser = argparse.ArgumentParser()
parser.add_argument('model', choices=['milmmt', 'hy4', 'hy8', 'hybf16'])
parser.add_argument('out', type=Path)
parser.add_argument('--mode', choices=['greedy', 'rp', 'rec'], default='greedy')
parser.add_argument('--seed', type=int, default=1, help='sampling seed for --mode rec')
parser.add_argument('--pairs', nargs='+', default=['he-en', 'he-ru'])
parser.add_argument('--context', choices=['none', 'prefix', 'turns', 'background'], default='none')
parser.add_argument('--window', type=int, default=2, help='preceding sentences of the same article')
args = parser.parse_args()

require_memory()
lines, urls, indexes = flores()
tr = Translator(args.model, args.mode, args.seed)
result = json.loads(args.out.read_text()) if args.out.is_file() else {}
tr.translate(lines['he'][indexes[0]], args.pairs[0])  # warm-up
cache = {}


def plain(index, pair):
    """The model's own context-free translation of a preceding sentence, as the app would show it."""
    if (index, pair) not in cache:
        cache[index, pair] = tr.translate(lines['he'][index], pair, key=index)['text']
    return cache[index, pair]


for pair in args.pairs:
    rows = result.setdefault(pair, {})
    for done, index in enumerate(indexes):
        if str(index) in rows:
            continue
        extra = {}
        before = [i for i in range(index - args.window, index) if i >= 0 and urls[i] == urls[index]]
        if args.context != 'none' and before:
            extra = dict(pairs=[(lines['he'][i], plain(i, pair)) for i in before], style=args.context)
        row = tr.translate(lines['he'][index], pair, key=index, **extra)
        row['reference'] = lines[pair.split('-')[1]][index]
        row['context'] = len(extra.get('pairs', ()))
        rows[str(index)] = row
        if done % 50 == 49:
            args.out.write_text(json.dumps(result, ensure_ascii=False))
            print(pair, f'{done + 1}/{len(indexes)}', flush=True)
args.out.write_text(json.dumps(result, ensure_ascii=False))
for pair, rows in result.items():
    print(pair, len(rows), 'sentences,', f'{sum(r["total"] for r in rows.values()):.0f} s')
print(f'peak MLX memory {tr.peak_gb():.2f} GB; load {tr.load_seconds:.1f} s')
