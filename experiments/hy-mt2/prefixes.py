"""Growing-tail behaviour: translate every word prefix of a sentence, as the app re-translates a growing phrase.

    .venv/bin/python experiments/hy-mt2/prefixes.py run hy4 OUT.json [--n 40]
    .venv/bin/python experiments/hy-mt2/prefixes.py score A.json B.json ...

Sentences: the first `--n` of the 300 seeded FLORES sentences that have 8-20 words, plus the
fact checklist (`facts.py`) sentences with 5+ words. Every prefix from 2 words to the whole sentence
is translated separately, without context (the app passes the previous translation only as a
speculation hint, which is off by default).

Scores per prefix step k -> k+1 (words of the shown translation, punctuation stripped):
- rewrite: share of the previous translation's words that are not kept as the start of the next
  one (0 = the new translation only appends, 1 = everything shown is replaced);
- for 2-6-word fragments: length ratio output words / source words, share of outputs over 3x the
  source (made-up continuation or explanation), outputs with Hebrew letters left, empty outputs;
- closed: share of unfinished prefixes (not the whole sentence) whose translation ends with a full
  stop or a closing quote, i.e. the model presents a fragment as a finished sentence.
"""
import argparse
import json
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def words(text):
    return [w for w in re.sub(r'[^\w\s\'-]', ' ', text.lower()).split() if w]


def sentences(n):
    from common import flores
    from facts import ITEMS
    lines, _, indexes = flores()
    picked = [(f'flores-{i}', lines['he'][i]) for i in indexes if 8 <= len(lines['he'][i].split()) <= 20][:n]
    return picked + [(key, he) for key, _, he, _ in ITEMS if len(he.split()) >= 5]


def run(args):
    from common import Translator, require_memory
    require_memory()
    tr = Translator(args.model, args.mode)
    out = json.loads(args.out.read_text()) if args.out.is_file() else {}
    tr.translate('שלום לכולם.', 'he-en')
    for pair in args.pairs:
        rows = out.setdefault(pair, {})
        for key, he in sentences(args.n):
            if key in rows:
                continue
            tokens = he.split()
            rows[key] = [dict(k=k, source=' '.join(tokens[:k]), **tr.translate(' '.join(tokens[:k]), pair))
                         for k in range(2, len(tokens) + 1)]
        args.out.write_text(json.dumps(out, ensure_ascii=False))
        print(pair, 'done', flush=True)
    print(f'peak MLX {tr.peak_gb():.2f} GB')


def rewrite(prev, new):
    a, b = words(prev), words(new)
    if not a:
        return None
    kept = 0
    for x, y in zip(a, b):
        if x != y:
            break
        kept += 1
    return 1 - kept / len(a)


def score(args):
    for pair in ('he-en', 'he-ru'):
        print(f'\n{pair}')
        print('run'.ljust(26) + 'rewrite mean  steps>0  steps>=50%  | 2-6 words: len ratio  >3x  hebrew  empty  | closed | p50 s')
        for path in args.runs:
            run = json.loads(path.read_text()).get(pair)
            if not run:
                continue
            rw, short, times, closed = [], [], [], []
            for rows in run.values():
                closed += [bool(re.search(r'[.!?»"”]\s*$', r['text'])) for r in rows[:-1]]
                for prev, new in zip(rows, rows[1:]):
                    r = rewrite(prev['text'], new['text'])
                    if r is not None:
                        rw.append(r)
                for row in rows:
                    times.append(row['total'])
                    if row['k'] <= 6:
                        short.append(row)
            ratio = [len(words(r['text'])) / r['k'] for r in short]
            print(path.stem[:25].ljust(26) +
                  f'{st.mean(rw):.3f}'.ljust(14) + f'{sum(x > 0 for x in rw) / len(rw):.0%}'.ljust(9) +
                  f'{sum(x >= .5 for x in rw) / len(rw):.0%}'.ljust(12) + '| ' +
                  f'{st.median(ratio):.2f}'.ljust(21) + f'{sum(x > 3 for x in ratio) / len(ratio):.0%}'.ljust(5) +
                  f'{sum(bool(re.search("[א-ת]", r["text"])) for r in short)}'.ljust(8) +
                  f'{sum(not r["text"] for r in short)}'.ljust(7) + f'| {sum(closed) / len(closed):.0%}'.ljust(9) + f'| {st.median(times):.3f}  (n steps {len(rw)}, fragments {len(short)})')
        if args.examples:
            for path in args.runs:
                run = json.loads(path.read_text()).get(pair, {})
                for key in list(run)[:args.examples]:
                    print(f'  {path.stem} {key}:')
                    for row in run[key][:6]:
                        print(f'    {row["k"]}: {row["text"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('model', choices=['milmmt', 'hy4', 'hy8', 'hybf16'])
    r.add_argument('out', type=Path)
    r.add_argument('--mode', choices=['greedy', 'rp', 'rec'], default='greedy')
    r.add_argument('--n', type=int, default=40)
    r.add_argument('--pairs', nargs='+', default=['he-ru', 'he-en'])
    s = sub.add_parser('score')
    s.add_argument('runs', nargs='+', type=Path)
    s.add_argument('--examples', type=int, default=0)
    args = parser.parse_args()
    run(args) if args.cmd == 'run' else score(args)
