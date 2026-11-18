"""Does the owner's vocabulary prompt hurt speech that does not contain its words?

    .venv/bin/python experiments/tail-only/vocabulary_check.py OUT.json [--set d1]

OUT.json is a finished `prefix_probe.py --step 20 --mixed` run. Every window is decoded again
through Engine.recognize with a prompt of 29 clinic terms that the recordings do not use: whole,
and continued from the frozen sentences. Prints WER against the reference next to the same
windows without the prompt. One MLX model; reads the vocabulary from a temporary folder.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for part in ('experiments/streaming-asr', 'experiments/nn-audit-2026-10', 'experiments/corpus', 'src'):
    sys.path.insert(0, str(ROOT / part))
import common  # noqa: E402
from gated import wait_until_quiet  # noqa: E402
from normalize import normalize  # noqa: E402

TERMS = ['הפניה', 'הרדמה', 'סדציה', 'קופת חולים', 'מכבי', 'כללית', 'מאוחדת', 'לאומית', 'התחייבות', 'טופס 17',
         'מרפאה', 'אורתופד', 'קרדיולוג', 'גסטרו', 'קולונוסקופיה', 'אולטרסאונד', 'בדיקת דם', 'מרשם',
         'אנטיביוטיקה', 'פיזיותרפיה', 'ביטוח משלים', 'תור', 'זימון תורים', 'מיון', 'אשפוז', 'ניתוח',
         'צילום רנטגן', 'חיסון', 'רופא משפחה']

parser = argparse.ArgumentParser()
parser.add_argument('out', type=Path)
parser.add_argument('--set', default='d1', choices=['d1', 'whatsapp'])
parser.add_argument('--terms', type=int, default=len(TERMS), help='use only the first N terms')
args = parser.parse_args()
if not wait_until_quiet(need_idle=30, timeout=1800):
    raise SystemExit('memory pressure is not normal or the CPU is busy; not starting')

home = tempfile.mkdtemp(prefix='hebrew-live-vocabulary-')
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HEBREW_LIVE_HOME=home, HEBREW_LIVE_VOCABULARY_ASR='1')
from hebrew_live import vocabulary  # noqa: E402
from hebrew_live.cli import Engine  # noqa: E402

TERMS = TERMS[:args.terms]
vocabulary.save([vocabulary.Entry(term) for term in TERMS], vocabulary.path())
models = Path.home() / 'Library' / 'Application Support' / 'Hebrew Live CLI' / 'models'
engine = Engine(models, type('Quiet', (), {'event': lambda *a, **k: None})(), role='asr')
engine.direction = 'he-ru'
engine.warmup()
print(f'prompt: {len(engine.asr_prompt.split(", "))} terms, {engine.asr_tokens(engine.asr_prompt)} tokens', flush=True)


def distance(left, right):
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        previous, row[0] = row[0], i
        for j, b in enumerate(right, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (a != b))
    return row[-1]


def recognize(audio, **options):
    return engine.recognize(audio, 0., preliminary=True, mode='phrases', align_words=False, **options)


saved = json.loads(args.out.read_text())
size = round(float(saved['args']['full']) * common.RATE)
reference = common.references(args.set)
errors = dict(whole=0, whole_prompt=0, tail=0, tail_prompt=0); total = inserted = 0
terms = {word for term in TERMS for word in normalize(term).split()}
for key in sorted({row['key'] for row in saved['rows']}, key=int):
    audio = common.load(args.set, key)
    texts = dict(whole=[], whole_prompt=[], tail=[], tail_prompt=[])
    for row in sorted((row for row in saved['rows'] if row['key'] == key), key=lambda row: row['start']):
        window = audio[round(row['start'] * common.RATE):][:size]
        item = row['mixed']
        whole = recognize(window)
        texts['whole'].append(item['baseline']); texts['whole_prompt'].append(whole)
        texts['tail'].append(item['frozen'] + ' ' + item['prefixed'] if item['frozen'] else item['baseline'])
        texts['tail_prompt'].append(item['frozen'] + ' ' + recognize(window, continues=item['frozen']) if item['frozen'] else whole)
    truth = normalize(reference[key]).split(); total += len(truth)
    for name, parts in texts.items():
        errors[name] += distance(truth, normalize(' '.join(parts)).split())
    # vocabulary words that the prompt put into the text although the reference has none
    inserted += sum(word in terms and word not in truth for word in normalize(' '.join(texts['whole_prompt'])).split())
    print(key, flush=True)
print(f'{args.set}: {total} reference words; errors ' + ', '.join(f'{name} {count}' for name, count in errors.items()) +
      f'; vocabulary words written although not said: {inserted}')
