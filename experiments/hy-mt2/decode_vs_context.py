"""Decode cost per token against request length, one model per process.

    .venv/bin/python experiments/hy-mt2/decode_vs_context.py hy4 [--repeats 3]

The same Hebrew sentence is translated with 0, 1, 2, 4 and 8 preceding FLORES sentences of the
same article put into the request (app style: both sides open with them, see common.Translator.ids).
Prints prompt tokens, first-token time and decode ms/token (median over repeats). If a model's decode
cost grows with the request while the other's does not, the app's context pairs cost it more.
Timings are indicative on a shared Mac.
"""
import argparse
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import Translator, flores, require_memory

parser = argparse.ArgumentParser()
parser.add_argument('model', choices=['milmmt', 'hy4', 'hy8', 'hybf16'])
parser.add_argument('--repeats', type=int, default=3)
parser.add_argument('--pair', default='he-ru')
args = parser.parse_args()
require_memory()
lines, urls, _ = flores()
# an article with at least 9 sentences
start = next(i for i in range(len(urls) - 9) if len(set(urls[i:i + 9])) == 1)
target = lines['he'][start + 8]
tr = Translator(args.model)
tr.translate(target, args.pair)
own = {}
for n in (0, 1, 2, 4, 8):
    pairs = []
    for i in range(start + 8 - n, start + 8):
        own.setdefault(i, tr.translate(lines['he'][i], args.pair)['text'])
        pairs.append((lines['he'][i], own[i]))
    runs = [tr.translate(target, args.pair, pairs=pairs) for _ in range(args.repeats)]
    dec = [1000 * (r['total'] - r['first_token']) / (r['tokens'] - 1) for r in runs]
    print(f'{args.model} context {n}: prompt {runs[0]["prompt_tokens"]} tokens, out {runs[0]["tokens"]}, '
          f'first token {st.median(r["first_token"] for r in runs):.3f} s, decode {st.median(dec):.1f} ms/token, '
          f'call {st.median(r["total"] for r in runs):.3f} s', flush=True)
