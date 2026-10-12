"""Paired comparison of two runs with a bootstrap confidence interval. Prints numbers only.

    .venv/bin/python experiments/corpus/compare.py asr A.json B.json [--names a b]   # fleurs_asr.py outputs
    .venv/bin/python experiments/corpus/compare.py asr A.json B.json --set ivrit-d1  # ivrit_eval_asr.py outputs (or ivrit-whatsapp)
    .venv/bin/python experiments/corpus/compare.py mt  A.json B.json [--names a b]   # flores_mt.py outputs

ASR: micro WER of each run against the FLEURS reference (leaderboard normalisation), the
difference B - A with a 95 % interval over clips (negative = B better), and the time per clip.
MT: mean sentence chrF++ against the FLORES reference per direction, difference B - A with a
95 % interval over sentences (positive = B better), and timing. The local chrF++ is meant for
comparing runs with each other (see metrics.py).
"""
import argparse
import csv
import json
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from metrics import chrf, edit_counts
from normalize import normalize

TSV = Path.home() / 'Library' / 'Caches' / 'hebrew-live-refs' / 'fleurs-he_il' / 'data' / 'he_il' / 'test.tsv'
parser = argparse.ArgumentParser()
parser.add_argument('kind', choices=['asr', 'mt'])
parser.add_argument('a', type=Path)
parser.add_argument('b', type=Path)
parser.add_argument('--names', nargs=2, default=['a', 'b'])
parser.add_argument('--set', choices=['fleurs', 'ivrit-d1', 'ivrit-whatsapp'], default='fleurs', help='which reference the asr texts are scored against')
parser.add_argument('--resamples', type=int, default=2000)
args = parser.parse_args()
rng = random.Random(1)
A, B = (json.loads(path.read_text()) for path in (args.a, args.b))
na, nb = args.names


def interval(values, weights=None):
    """95 % bootstrap interval of the mean (or of the weighted ratio when weights are given)."""
    n = len(values)
    stats = []
    for _ in range(args.resamples):
        pick = [rng.randrange(n) for _ in range(n)]
        stats.append(sum(values[i] for i in pick) / (sum(weights[i] for i in pick) if weights else n))
    stats.sort()
    return stats[int(.025 * args.resamples)], stats[int(.975 * args.resamples)]


def timing(label, rows):
    seconds = [r['seconds'] if 'seconds' in r else r['total'] for r in rows]
    print(f'  {label}: p50 {st.median(seconds):.3f} s, mean {st.mean(seconds):.3f} s per item, n={len(seconds)}')


if args.kind == 'asr':
    if args.set == 'fleurs':
        reference = {row[1]: row[2] for row in csv.reader(TSV.open(encoding='utf-8'), delimiter='\t', quoting=csv.QUOTE_NONE)}
    else:
        reference = json.loads((TSV.parents[3] / f'ivrit-eval-{args.set[6:]}' / 'extracted' / 'texts.json').read_text(encoding='utf-8'))
    names = [n for n in A if n in B and n in reference]
    counts = {}
    for label, run in ((na, A), (nb, B)):
        errors, words = [], []
        for n in names:
            ref = normalize(reference[n]).split()
            s, d, i = edit_counts(ref, normalize(run[n]['text']).split())
            errors.append(s + d + i)
            words.append(len(ref))
        counts[label] = (errors, words)
        print(f'{label}: WER {sum(errors) / sum(words):.4f} over {sum(words)} words in {len(names)} clips; '
              f'empty outputs {sum(1 for n in names if not run[n]["text"].strip())}')
        timing(label, [run[n] for n in names])
    (ea, w), (eb, _) = counts[na], counts[nb]
    diff = [y - x for x, y in zip(ea, eb)]
    low, high = interval(diff, w)
    print(f'WER {nb} - {na}: {sum(diff) / sum(w):+.4f} (95 % interval {low:+.4f} .. {high:+.4f}); '
          f'identical text on {sum(1 for n in names if normalize(A[n]["text"]) == normalize(B[n]["text"]))}/{len(names)} clips')
else:
    for pair in A:
        if pair not in B:
            continue
        ids = [i for i in A[pair] if i in B[pair]]
        scores = {}
        for label, run in ((na, A), (nb, B)):
            scores[label] = [chrf(run[pair][i]['text'], run[pair][i]['reference']) for i in ids]
            print(f'{pair} {label}: chrF++ {st.mean(scores[label]):.2f} over {len(ids)} sentences; '
                  f'length-truncated {sum(1 for i in ids if run[pair][i]["reason"] == "length")}')
            timing(label, [run[pair][i] for i in ids])
            firsts = [run[pair][i]['first'] for i in ids if run[pair][i]['first'] is not None]
            tokens = [run[pair][i]['tokens'] / run[pair][i]['total'] for i in ids if run[pair][i]['tokens']]
            print(f'  first piece p50 {st.median(firsts):.3f} s' + (f'; tokens/s p50 {st.median(tokens):.1f}' if tokens else ''))
        diff = [y - x for x, y in zip(scores[na], scores[nb])]
        low, high = interval(diff)
        print(f'{pair} chrF++ {nb} - {na}: {st.mean(diff):+.2f} (95 % interval {low:+.2f} .. {high:+.2f}); '
              f'identical text on {sum(1 for i in ids if A[pair][i]["text"] == B[pair][i]["text"])}/{len(ids)}')
