"""Screen stability of replay outputs (see replay.py).

    python3 compare.py out/baseline.jsonl out/freeze.jsonl

For every group it walks the sequence of what the bubble showed (a stream preview
replaces the bubble until the next publication) and counts:
- rewritten: a finished sentence (one followed by another) no longer starts the next view;
- shrinks: the bubble lost more than 20 characters at once (it collapses and regrows);
- MT seconds and prompt tokens per call.
"""
import json, re, statistics, sys
from rewrites import sentences


def stats(path):
    shown = {}; rewritten = checks = shrinks = updates = 0; mt = []; tokens = []; final = {}
    for line in open(path):
        d = json.loads(line)
        if d['kind'] == 'mt_generation':
            mt.append(d['seconds']); tokens.append(d['prompt_tokens']); continue
        text = re.sub(r'\s+', ' ', d['translation'] if d['kind'] == 'live_stream' else d['current']['translation']).strip()
        if not text: continue
        sid = d['segment']; old = shown.get(sid); updates += 1
        if old and text != old:
            prefix = ''
            for s in sentences(old)[:-1]:
                checks += 1; prefix = (prefix + ' ' + s).strip()
                if not text.startswith(prefix): rewritten += 1
            if len(text) < len(old) - 20: shrinks += 1
        shown[sid] = text
        if d['kind'] == 'live_publication': final[sid] = text
    return dict(updates=updates, finished_checks=checks, rewritten=rewritten, shrinks=shrinks,
                mt_calls=len(mt), mt_p50=round(statistics.median(mt), 3), mt_p95=round(sorted(mt)[int(.95 * len(mt))], 3),
                mt_total=round(sum(mt), 1), prompt_tokens_p50=statistics.median(tokens)), final


if __name__ == '__main__':
    results = [stats(path) for path in sys.argv[1:]]
    for path, (summary, _) in zip(sys.argv[1:], results):
        print(path, json.dumps(summary, ensure_ascii=False))
