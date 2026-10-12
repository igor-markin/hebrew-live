"""Hypotheses for FLEURS he_il (test) from one ASR variant; scoring is done by `compare.py asr`.

    # Whisper Turbo as the app runs it (project venv). `fused` turns on HEBREW_LIVE_FUSED_ENCODER.
    .venv/bin/python experiments/corpus/fleurs_asr.py whisper OUT.json [--fused] [--limit N]
    # Parakeet-he (the separate environment in ~/Library/Caches/hebrew-live-refs/venv-parakeet)
    ~/Library/Caches/hebrew-live-refs/venv-parakeet/bin/python experiments/corpus/fleurs_asr.py parakeet OUT.json

OUT.json maps the clip name to `{text, seconds}`. FLEURS is public, but keep OUT.json in the app
data root (`corpus/`), not in the repository. One model job at a time; run under `nice`.
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFS = Path.home() / 'Library' / 'Caches' / 'hebrew-live-refs'
TSV = REFS / 'fleurs-he_il' / 'data' / 'he_il' / 'test.tsv'
AUDIO = REFS / 'fleurs-he_il-test' / 'test'

parser = argparse.ArgumentParser()
parser.add_argument('engine', choices=['whisper', 'parakeet'])
parser.add_argument('out', type=Path)
parser.add_argument('--fused', action='store_true')
parser.add_argument('--limit', type=int)
args = parser.parse_args()

clips = [row[1] for row in csv.reader(TSV.open(encoding='utf-8'), delimiter='\t', quoting=csv.QUOTE_NONE)][:args.limit]
result = json.loads(args.out.read_text()) if args.out.is_file() else {}

if args.engine == 'whisper':
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    if args.fused:
        os.environ['HEBREW_LIVE_FUSED_ENCODER'] = '1'
    sys.path.insert(0, str(ROOT / 'src'))
    import numpy as np
    import soundfile as sf
    import soxr
    from hebrew_live.cli import Engine

    class Quiet:
        def event(self, *a, **k):
            pass

    engine = Engine(ROOT / 'models', Quiet(), role='asr')
    engine.direction = 'he-ru'
    engine.warmup()  # loads the model and applies the fused patch when enabled

    def load(name):
        data, rate = sf.read(AUDIO / name, dtype='float32', always_2d=False)
        if data.ndim == 2:
            data = data.mean(axis=1)
        return soxr.resample(data, rate, 16000).astype(np.float32) if rate != 16000 else data

    def transcribe(audio):
        return engine.recognize(audio, 0., preliminary=False, mode='phrases', align_words=False)
else:
    import librosa
    from transformers import AutoModelForTDT, AutoProcessor
    repo = REFS / 'parakeet-tdt-0.6b-v3-he'
    processor = AutoProcessor.from_pretrained(repo)
    model = AutoModelForTDT.from_pretrained(repo).eval()

    def load(name):
        return librosa.load(AUDIO / name, sr=16000, mono=True)[0]

    def transcribe(audio):
        inputs = processor(audio, sampling_rate=16000, return_tensors='pt')
        out = model.generate(**inputs)
        return processor.batch_decode(out.sequences, skip_special_tokens=True)[0]

first = load(clips[0])
transcribe(first)  # warm-up, not recorded
for index, name in enumerate(clips):
    if name in result:
        continue
    audio = load(name)
    began = time.perf_counter()
    text = transcribe(audio)
    result[name] = dict(text=text.strip(), seconds=time.perf_counter() - began, audio_seconds=len(audio) / 16000)
    if index % 50 == 49:
        args.out.write_text(json.dumps(result, ensure_ascii=False))
        print(f'{index + 1}/{len(clips)}', flush=True)
args.out.write_text(json.dumps(result, ensure_ascii=False))
print(f'{len(result)} clips, {sum(r["seconds"] for r in result.values()):.0f} s of inference for '
      f'{sum(r["audio_seconds"] for r in result.values()):.0f} s of audio')
