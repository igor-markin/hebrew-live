"""Plan 2.1 on real speech: fused encoder attention against the stock encoder.

Replays the accepted ASR windows of a session through `Engine.recognize` (draft path, no word
timestamps) with and without `HEBREW_LIVE_FUSED_ENCODER`, in random order inside every repeat.
Reports how many transcripts equal the stock transcript (byte-identical, mean WER) and the paired
time ratio by window length. Run alone (one MLX job); prints counts and timings only.

    .venv/bin/python experiments/corpus/asr_speed_ab.py SESSION_DIR [--repeats 2] [--reference REF.json]

With `--reference` (from `make_asr_reference.py`) it also scores stock, fused and the transcript
recorded by the shipped build against the reference words inside each window (micro WER).
"""
import argparse
import importlib
import json
import os
import random
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HEBREW_LIVE_FUSED_ENCODER='1')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

from metrics import wer
from windows import windows


class Quiet:
    def event(self, *args, **kwargs):
        pass


parser = argparse.ArgumentParser()
parser.add_argument('session', type=Path)
parser.add_argument('--repeats', type=int, default=2)
parser.add_argument('--reference', type=Path)
args = parser.parse_args()

from hebrew_live.cli import Engine

engine = Engine(ROOT / 'models', Quiet(), role='asr')
engine.direction = 'he-ru'
engine.warmup()                                   # loads the model and applies the fused patch
model = importlib.import_module('mlx_whisper.transcribe').ModelHolder.model
blocks = [block.attn for block in model.encoder.blocks]
if not all('qkv_attention' in vars(attn) for attn in blocks):
    sys.exit('the fused patch was not applied (library not qualified?)')
fused = {id(attn): attn.qkv_attention for attn in blocks}


def configure(variant):
    for attn in blocks:
        if variant == 'fused':
            attn.qkv_attention = fused[id(attn)]
        elif 'qkv_attention' in vars(attn):
            del attn.qkv_attention                # back to the class method


items = windows(args.session)
texts = {v: [None] * len(items) for v in ('base', 'fused')}
times = {v: [[] for _ in items] for v in texts}
for _ in range(args.repeats):
    for index, item in enumerate(items):
        order = ['base', 'fused']
        random.shuffle(order)
        for variant in order:
            configure(variant)
            began = time.perf_counter()
            texts[variant][index] = engine.recognize(item['audio'], 0., preliminary=not item['final'],
                                                     mode='phrases', align_words=False)
            times[variant][index].append(time.perf_counter() - began)
configure('base')
same = sum(texts['fused'][i].strip() == texts['base'][i].strip() for i in range(len(items)))
errors = [e for e in (wer(texts['base'][i], texts['fused'][i]) for i in range(len(items))) if e is not None]
print(f'{len(items)} real windows, {args.repeats} repeats: fused byte-identical to stock {same}/{len(items)}, '
      f'mean WER vs stock {sum(errors) / len(errors):.4f}')
row = []
for low, high in ((0, 2), (2, 5), (5, 10), (10, 99)):
    ratios = [min(times['fused'][i]) / min(times['base'][i]) for i, item in enumerate(items)
              if low <= len(item['audio']) / 16000 < high]
    if ratios:
        row.append(f'{low}-{high}s: x{st.median(ratios):.2f} (n={len(ratios)})')
print('time vs stock (min of repeats, median over windows): ' + '; '.join(row))

if args.reference:
    from metrics import corpus_wer
    reference = json.loads(args.reference.read_text(encoding='utf-8'))
    words = [w for segment in reference['segments'] for w in segment['words']]

    def reference_text(item):
        return ' '.join(w['word'].strip() for w in words if item['start'] <= (w['start'] + w['end']) / 2 < item['end'])

    def score(selected, hypotheses):
        pairs = [(reference_text(items[i]), hypotheses[i]) for i in selected]
        pairs = [(r, h) for r, h in pairs if r.strip()]
        value, count = corpus_wer(pairs)
        return f'{value:.3f} over {count} reference words in {len(pairs)} windows'

    recorded = [item['text'] for item in items]
    for label, selected in (('final windows', [i for i, it in enumerate(items) if it['final']]),
                            ('partial windows', [i for i, it in enumerate(items) if not it['final']])):
        print(f'WER vs reference, {label}: stock {score(selected, texts["base"])}; fused {score(selected, texts["fused"])}; '
              f'recorded by the shipped build {score(selected, recorded)}')
