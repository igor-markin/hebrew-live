"""Translate the 12 synthetic reference sentences with the app's MiLMMT path (side by side with apple_translate.swift)."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
import mlx.core as mx

import corpus
from hebrew_live.cli import Engine


class Log:
    def event(self, n, **k):
        pass

    def error(self, e):
        pass


e = Engine(ROOT / 'models', Log(), language='he', role='mt')
e.warmup()
lines = corpus.references()
for tgt in ('en', 'ru'):
    e.direction = 'he-' + tgt
    e.topic = 'none'
    for i, line in enumerate(lines + [' '.join(lines)]):
        e.translation_context = []
        t0 = time.perf_counter()
        out = ''
        for piece, reason in e.translate(line):
            out += piece
        mx.synchronize()
        ms = (time.perf_counter() - t0) * 1000
        print(f"{tgt}\t{'ALL12' if i == len(lines) else i + 1}\t{ms:.0f} ms\t{out.strip()}")
