"""Count visible rewrites of finished sentences in a recorded session.

Usage: python3 rewrites.py SESSION_DIR [--until SECONDS]
Reads <part>.diagnostics.jsonl and replays the `live_publication` events: a finished
sentence is any sentence of a shown translation that is followed by another one.
It counts how often such a sentence is no longer an exact prefix of the next version.
"""
import argparse, json, re
from pathlib import Path

SENTENCE = re.compile(r'[^.!?…]+(?:[.!?…]+["»”)]*\s*|$)')

def sentences(text):
    return [s.strip() for s in SENTENCE.findall(text.strip()) if s.strip()]

def main():
    p = argparse.ArgumentParser(); p.add_argument('session'); p.add_argument('--until', type=float, default=1440.)
    a = p.parse_args()
    path = next(Path(a.session).glob('*.diagnostics.jsonl'))
    last = {}; versions = rewritten = finished_seen = 0; rewritten_chars = 0; groups = set()
    for line in path.open():
        d = json.loads(line)
        if d['event'] != 'live_publication' or d['start'] > a.until: continue
        text = d['current']['translation']; sid = d['segment']; versions += 1
        old = last.get(sid)
        if old:
            done = sentences(old)[:-1]
            prefix = ''
            for s in done:
                finished_seen += 1
                prefix = (prefix + ' ' + s).strip()
                if not re.sub(r'\s+', ' ', text).startswith(prefix):
                    rewritten += 1; rewritten_chars += len(s); groups.add(sid)
        if text: last[sid] = text
    print(json.dumps(dict(versions=versions, finished_sentence_checks=finished_seen,
                          rewritten=rewritten, rewritten_chars=rewritten_chars,
                          groups_with_rewrites=len(groups), groups=len(last)), ensure_ascii=False))

if __name__ == '__main__': main()
