"""Paired speed of the translators on the same requests, one model in memory at a time.

    .venv/bin/python experiments/hy-mt2/speed.py drive OUT.jsonl [--rounds 4] [--models milmmt hy4 hy8]
    .venv/bin/python experiments/hy-mt2/speed.py score OUT.jsonl

`drive` runs blocks: each block is a fresh process that loads one model, warms it up and translates
the same request list (he-ru: 30 FLORES sentences whole and their first 6 words, i.e. a long and a
short growing tail). The model order rotates each round, so drift on a shared Mac hits every
model alike. A block starts only when memory pressure is normal and >= 40 % is free.
Per call: whole call, first token (prefill + first step), tokens, prompt tokens. Decode cost per
token = (whole - first token) / (tokens - 1). `score` compares per request (median over rounds)
and gives the paired ratio to MiLMMT. Timings on a shared Mac are indicative.
"""
import argparse
import json
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def requests():
    from common import flores
    lines, _, indexes = flores()
    picked = indexes[::10][:30]
    out = []
    for i in picked:
        he = lines['he'][i]
        out += [(f'{i}-full', he), (f'{i}-6w', ' '.join(he.split()[:6]))]
    return out


def idle():
    sys.path.insert(0, str(HERE.parents[0] / 'nn-audit-2026-10'))
    from gated import idle as cpu_idle
    return cpu_idle()


def worker(args):
    from common import Translator, memory_state
    tr = Translator(args.model)
    reqs = requests()
    for _, he in reqs[:2]:
        tr.translate(he, 'he-ru')
    before = idle()
    rows = []
    for key, he in reqs:
        r = tr.translate(he, 'he-ru')
        rows.append(dict(model=args.model, round=args.round, key=key, total=r['total'], first=r['first'],
                         first_token=r['first_token'], tokens=r['tokens'], prompt_tokens=r['prompt_tokens'], text=r['text']))
    after = idle()
    level, free = memory_state()
    with args.out.open('a') as f:
        for row in rows:
            row.update(idle_before=before, idle_after=after, pressure=level, free=free, peak_gb=tr.peak_gb(), load_s=tr.load_seconds)
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'{args.model} round {args.round}: p50 {st.median(r["total"] for r in rows):.3f} s, idle {before:.0f}->{after:.0f} %, '
          f'pressure {level}, free {free} %, peak {tr.peak_gb():.2f} GB', flush=True)


def drive(args):
    from common import memory_state
    for r in range(args.rounds):
        order = args.models[r % len(args.models):] + args.models[:r % len(args.models)]
        if r % 2:
            order = order[::-1]
        for model in order:
            for _ in range(60):
                level, free = memory_state()
                other = subprocess.run(['pgrep', '-f', r'experiments/streaming-asr/.*\.py|whisper_run|fleurs_asr|ivrit_eval_asr'],
                                       capture_output=True).returncode == 0
                if level == 1 and free is not None and free >= 40 and not other:
                    break
                print(f'waiting: pressure {level}, free {free} %, other model job {other}', flush=True)
                time.sleep(30)
            else:
                sys.exit('memory never got quiet; stopped')
            subprocess.run([sys.executable, __file__, 'worker', model, str(args.out), '--round', str(r)], check=True)


def score(args):
    rows = [json.loads(line) for line in args.out.read_text().splitlines()]
    models = list(dict.fromkeys(r['model'] for r in rows))
    by = {}
    for r in rows:
        by.setdefault((r['model'], r['key']), []).append(r)
    keys = sorted({r['key'] for r in rows})
    med = lambda m, k, f: st.median(x[f] for x in by[m, k])
    print('model    rounds  call p50  call p95  first-token p50  decode ms/tok p50  out tok p50  prompt tok p50  peak GB  idle p50')
    for m in models:
        mr = [r for r in rows if r['model'] == m]
        calls = sorted(med(m, k, 'total') for k in keys if (m, k) in by)
        dec = [1000 * (r['total'] - r['first_token']) / (r['tokens'] - 1) for r in mr if r['tokens'] and r['tokens'] > 3]
        print(f'{m:8} {len({r["round"] for r in mr}):6}  {st.median(calls):8.3f}  {calls[int(.95 * (len(calls) - 1))]:8.3f}  '
              f'{st.median(r["first_token"] for r in mr):15.3f}  {st.median(dec):17.1f}  {st.median(r["tokens"] for r in mr):11.0f}  '
              f'{st.median(r["prompt_tokens"] for r in mr):14.0f}  {max(r["peak_gb"] for r in mr):7.2f}  {st.median(r["idle_before"] for r in mr):8.0f}')
    base = 'milmmt'
    for m in models:
        if m == base:
            continue
        for kind in ('full', '6w', ''):
            ks = [k for k in keys if k.endswith(kind) and (m, k) in by and (base, k) in by]
            ratios = sorted(med(m, k, 'total') / med(base, k, 'total') for k in ks)
            label = kind or 'all'
            print(f'{m}/{base} whole call, per request ({label}, n={len(ks)}): median ratio {st.median(ratios):.2f} '
                  f'(25-75 % {ratios[len(ratios) // 4]:.2f}..{ratios[3 * len(ratios) // 4]:.2f})')
        # per round: same requests, paired by round order
        per_round = []
        for rnd in sorted({r['round'] for r in rows}):
            a = [r['total'] for r in rows if r['model'] == m and r['round'] == rnd]
            b = [r['total'] for r in rows if r['model'] == base and r['round'] == rnd]
            if a and b:
                per_round.append(sum(a) / sum(b))
        print(f'{m}/{base} total time of a block, per round: ' + ', '.join(f'{x:.2f}' for x in per_round))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    w = sub.add_parser('worker')
    w.add_argument('model')
    w.add_argument('out', type=Path)
    w.add_argument('--round', type=int, default=0)
    d = sub.add_parser('drive')
    d.add_argument('out', type=Path)
    d.add_argument('--rounds', type=int, default=4)
    d.add_argument('--models', nargs='+', default=['milmmt', 'hy4', 'hy8'])
    s = sub.add_parser('score')
    s.add_argument('out', type=Path)
    args = parser.parse_args()
    {'worker': worker, 'drive': drive, 'score': score}[args.cmd](args)
