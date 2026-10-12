"""Apple Translation (on device) over the same sentences as flores_mt.py, written in its OUT.json schema.

    .venv/bin/python experiments/corpus/apple_mt.py OUT.json [--pairs he-en he-ru] [--n 300] [--seed 20261011]
    .venv/bin/python experiments/corpus/apple_mt.py OUT.json --units REF.json     # own reference units
    .venv/bin/python experiments/corpus/apple_mt.py OUT.json --loop 600           # background load for 600 s, no OUT rows
    .venv/bin/python experiments/corpus/compare.py mt <corpus>/runs/flores-4bit.json OUT.json --names milmmt apple

Apple does not stream, so `first` equals `total`; `tokens` is None. The Swift helper is built once into
`~/Library/Caches/hebrew-live-refs/apple_mt` (outside the repository). `--watch-memory` samples `ps` once a second
and prints the processes whose resident memory grew while the pairs ran.
"""
import argparse
import json
import random
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFS = Path.home() / 'Library' / 'Caches' / 'hebrew-live-refs'
DEVTEST = REFS / 'flores200-devtest' / 'flores200_dataset' / 'devtest'
SOURCE = Path(__file__).with_name('apple_mt.swift')
BINARY = REFS / 'apple_mt'
CODES = {'he': 'heb_Hebr', 'en': 'eng_Latn', 'ru': 'rus_Cyrl'}

parser = argparse.ArgumentParser()
parser.add_argument('out', type=Path)
parser.add_argument('--pairs', nargs='+', default=['he-en', 'he-ru'])
parser.add_argument('--n', type=int, default=300)
parser.add_argument('--seed', type=int, default=20261011)
parser.add_argument('--units', type=Path, help='JSON with {units: [{he, en, ru}]}: translate these instead of FLORES')
parser.add_argument('--loop', type=float, metavar='SECONDS', help='translate the first pair in a loop for this long; nothing is saved')
parser.add_argument('--watch-memory', action='store_true')
parser.add_argument('--no-gate', action='store_true', help='do not wait for an idle CPU and normal memory pressure')
args = parser.parse_args()

if not args.no_gate:
    import sys
    sys.path.insert(0, str(ROOT / 'experiments' / 'nn-audit-2026-10'))
    from gated import wait_until_quiet
    if not wait_until_quiet(timeout=900):
        raise SystemExit('the Mac is not quiet (CPU idle < 60 % or memory pressure); not starting')

if not BINARY.is_file() or BINARY.stat().st_mtime < SOURCE.stat().st_mtime:
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', '-O', '-o', str(BINARY), str(SOURCE)], check=True)

if args.units:
    units = json.loads(args.units.read_text(encoding='utf-8'))['units']
    lines = {code: [unit[lang] for unit in units] for lang, code in CODES.items()}
    indexes = list(range(len(units)))
else:
    lines = {code: (DEVTEST / f'{code}.devtest').read_text(encoding='utf-8').splitlines() for code in CODES.values()}
    indexes = sorted(random.Random(args.seed).sample(range(len(lines['heb_Hebr'])), args.n))
sentences = [lines['heb_Hebr'][index].replace('\n', ' ') for index in indexes]


def processes():
    out = subprocess.run(['ps', '-axo', 'pid=,rss=,comm='], capture_output=True, text=True).stdout
    found = {}
    for row in out.splitlines():
        pid, rss, command = row.split(None, 2)
        found[int(pid)] = (int(rss) / 1024, Path(command).name)
    return found


class Watch:
    """Peak resident MB per process seen during the run, against the first sample."""

    def __init__(self):
        self.base = processes()
        self.peak = {}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            for pid, (mb, name) in processes().items():
                if mb > self.peak.get(pid, (0, name))[0]:
                    self.peak[pid] = (mb, name)
            self.stop.wait(1.0)

    def report(self):
        self.stop.set()
        self.thread.join()
        rows = sorted(((mb - self.base.get(pid, (0, ''))[0], mb, name, pid) for pid, (mb, name) in self.peak.items()), reverse=True)
        print('resident memory growth during the run (MB: growth / peak); other apps on the Mac are in this list too:')
        related = [row for row in rows if any(word in row[2] for word in ('translationd', 'TGOnDevice', 'modelmanagerd'))]
        for growth, mb, name, pid in rows[:5] + [row for row in related if row not in rows[:5]]:
            print(f'  {name} (pid {pid}): {growth:+.0f} / {mb:.0f}')


def run(target, handle, seconds=None):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'sentences.txt'
        path.write_text('\n'.join(sentences), encoding='utf-8')
        command = [str(BINARY), target, str(path)] + (['loop'] if seconds else [])
        process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
        deadline = time.monotonic() + seconds if seconds else None
        for line in process.stdout:
            handle(json.loads(line))
            if deadline and time.monotonic() > deadline:
                break
        if deadline:
            process.kill()
        process.wait()
        if not deadline and process.returncode:
            raise SystemExit(f'apple_mt {target} exited with {process.returncode}')


watch = Watch() if args.watch_memory else None
if watch:
    watch.thread.start()
if args.loop:
    times = []
    run(args.pairs[0].split('-')[1], lambda row: times.append(row['ms']) if 'ms' in row else None, args.loop)
    print(f'{len(times)} background translations in {args.loop:.0f} s, call time p50 {sorted(times)[len(times) // 2]:.0f} ms')
else:
    result = json.loads(args.out.read_text()) if args.out.is_file() else {}
    for pair in args.pairs:
        target = pair.split('-')[1]
        rows = result.setdefault(pair, {})

        def collect(item):
            index = indexes[item['i']]
            reference = lines[CODES[target]][index]
            if 'error' in item:
                rows[str(index)] = dict(text='', first=None, total=0., tokens=None, reason='error', reference=reference, error=item['error'])
            else:
                rows[str(index)] = dict(text=item['text'].strip(), first=item['ms'] / 1000, total=item['ms'] / 1000,
                                        tokens=None, reason='stop', reference=reference)

        run(target, collect)
        args.out.write_text(json.dumps(result, ensure_ascii=False))
    for pair, rows in result.items():
        errors = sum(1 for r in rows.values() if r['reason'] == 'error')
        print(pair, len(rows), 'sentences,', f'{sum(r["total"] for r in rows.values()):.0f} s,', errors, 'errors')
if watch:
    watch.report()
