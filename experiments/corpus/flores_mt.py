"""Translations of FLORES-200 devtest sentences by one MiLMMT build, with the app's prompt and loop.

    .venv/bin/python experiments/corpus/flores_mt.py 4bit OUT.json [--pairs he-en he-ru] [--n 300] [--seed 20261011]
    .venv/bin/python experiments/corpus/flores_mt.py 5bit OUT.json
    # own reference translations (corpus/ref-translations-*.json) instead of FLORES
    .venv/bin/python experiments/corpus/flores_mt.py 4bit OUT.json --units REF.json

`4bit` is the shipped model in `models/`, `5bit` the build in `~/Library/Caches/hebrew-live-refs`
(deleted 2026-10-12, the owner rejected it; to repeat the run download it again, revision and hashes are in README.md),
`1b8bit` the 1B build in the same folder (smaller-model candidate, measured and deleted 2026-10-12; revision and hashes are in README.md).
The same sentences (fixed seed) go through `Engine.translate`, so a later `compare.py mt` run
scores both builds on identical input. OUT.json holds translated text and per-sentence timings;
keep it in the app data root (`corpus/`). One MT model at a time; run under `nice`.
"""
import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFS = Path.home() / 'Library' / 'Caches' / 'hebrew-live-refs'
DEVTEST = REFS / 'flores200-devtest' / 'flores200_dataset' / 'devtest'
BUILDS = {'4bit': None, '5bit': REFS / 'milmmt-4b-5bit-mlx', '1b8bit': REFS / 'milmmt-1b-8bit-mlx'}
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))

parser = argparse.ArgumentParser()
parser.add_argument('build', choices=list(BUILDS))
parser.add_argument('out', type=Path)
parser.add_argument('--pairs', nargs='+', default=['he-en', 'he-ru'])
parser.add_argument('--n', type=int, default=300)
parser.add_argument('--seed', type=int, default=20261011)
parser.add_argument('--units', type=Path, help='JSON with {units: [{he, en, ru}]}: translate these instead of FLORES')
args = parser.parse_args()

CODES = {'he': 'heb_Hebr', 'en': 'eng_Latn', 'ru': 'rus_Cyrl'}
if args.units:
    units = json.loads(args.units.read_text(encoding='utf-8'))['units']
    lines = {CODES[lang]: [unit[lang] for unit in units] for lang in CODES}
    indexes = list(range(len(units)))
else:
    lines = {code: (DEVTEST / f'{code}.devtest').read_text(encoding='utf-8').splitlines() for code in CODES.values()}
    indexes = sorted(random.Random(args.seed).sample(range(len(lines['heb_Hebr'])), args.n))

from hebrew_live.cli import Engine


class Log:
    def __init__(self):
        self.tokens = None

    def event(self, name, **values):
        if name == 'mt_generation':
            self.tokens = values.get('tokens')


log = Log()
engine = Engine(ROOT / 'models', log, role='mt', translation_path=BUILDS[args.build])
result = json.loads(args.out.read_text()) if args.out.is_file() else {}


def translate(text):
    began = time.perf_counter()
    first = None
    pieces = []
    reason = None
    for piece, reason in engine.translate(text):
        if piece and first is None:
            first = time.perf_counter() - began
        pieces.append(piece)
    return dict(text=''.join(pieces).strip(), first=first, total=time.perf_counter() - began, tokens=log.tokens, reason=reason)


engine.direction = args.pairs[0]
translate(lines['heb_Hebr'][indexes[0]])  # warm-up
for pair in args.pairs:
    engine.direction = pair
    target = CODES[pair.split('-')[1]]
    rows = result.setdefault(pair, {})
    for done, index in enumerate(indexes):
        if str(index) in rows:
            continue
        row = translate(lines['heb_Hebr'][index])
        row['reference'] = lines[target][index]
        rows[str(index)] = row
        if done % 50 == 49:
            args.out.write_text(json.dumps(result, ensure_ascii=False))
            print(pair, f'{done + 1}/{len(indexes)}', flush=True)
args.out.write_text(json.dumps(result, ensure_ascii=False))
for pair, rows in result.items():
    print(pair, len(rows), 'sentences,', f'{sum(r["total"] for r in rows.values()):.0f} s')
print(f'peak MLX memory {engine.mx.get_peak_memory() / 1e9:.2f} GB (this process only)')
