"""Do the current ASR defaults reproduce what the shipped build recorded on the same audio?

Replays every accepted `live_asr` window of a session through `Engine.recognize` with the
draft-path settings (no word timestamps) and compares with the recorded text. Reports counts
and timing only. Run alone (one MLX job).

    .venv/bin/python experiments/corpus/asr_window_identity.py SESSION_DIR [--limit N]
"""
import argparse
import os
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

from metrics import wer
from windows import windows


class Quiet:
    def event(self, *args, **kwargs):
        pass


parser = argparse.ArgumentParser()
parser.add_argument('session', type=Path)
parser.add_argument('--limit', type=int)
parser.add_argument('--align-words', action='store_true', help='stock path: word timestamps on')
args = parser.parse_args()

from hebrew_live.cli import Engine

engine = Engine(ROOT / 'models', Quiet(), role='asr')
engine.direction = 'he-ru'
items = windows(args.session)[:args.limit]
engine.recognize(items[0]['audio'], 0., preliminary=True, mode='phrases', align_words=args.align_words)
same = normalized = 0
errors = []
seconds = []
for item in items:
    began = time.perf_counter()
    text = engine.recognize(item['audio'], 0., preliminary=not item['final'], mode='phrases',
                            align_words=args.align_words)
    seconds.append(time.perf_counter() - began)
    same += text.strip() == item['text'].strip()
    error = wer(item['text'], text)
    normalized += error == 0
    if error is not None:
        errors.append(error)
n = len(items)
print(f'{n} windows: byte-identical {same}, identical after normalisation {normalized}, '
      f'mean WER vs recorded {sum(errors) / max(len(errors), 1):.4f}')
print(f'call time median {st.median(seconds):.3f}s min {min(seconds):.3f}s (recorded median '
      f'{st.median(i["seconds"] for i in items):.3f}s under the original load)')
