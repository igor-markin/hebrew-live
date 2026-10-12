"""Synthetic Hebrew TTS corpus (12 clean clips) resampled to 16 kHz plus reference texts.

The clips and ``corpus.json`` live in the local ``logs/asr-comparison-20260908``
folder, which is not part of the public export.
"""
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'logs' / 'asr-comparison-20260908'


def load():
    meta = json.load(open(BASE / 'corpus.json', encoding='utf-8'))
    clips = []
    for c in meta['cases']:
        if c['language'] != 'he' or c['group'] != 'clean':
            continue
        a, sr = sf.read(BASE / (c['id'] + '.aiff'), dtype='float32', always_2d=False)
        if a.ndim == 2:
            a = a.mean(1)
        a = soxr.resample(a, sr, 16000).astype('float32')
        clips.append((c['id'], a, c['reference']))
    return clips


def references():
    return [ref for _, _, ref in load()]


def concat(clips, gap=0.3, n=None):
    g = np.zeros(int(gap * 16000), dtype='float32')
    parts = []
    for _, a, _ in (clips if n is None else clips[:n]):
        parts += [a, g]
    return np.concatenate(parts)


if __name__ == '__main__':
    cl = load()
    print(len(cl), [round(len(a) / 16000, 2) for _, a, _ in cl])
    print('concat gap .3 :', round(len(concat(cl, .3)) / 16000, 1), 's')
