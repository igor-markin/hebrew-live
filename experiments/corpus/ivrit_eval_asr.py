"""Hypotheses for the ivrit.ai eval sets from Whisper Turbo as the app loads it; scoring is `compare.py asr --set ...`.

    .venv/bin/python experiments/corpus/ivrit_eval_asr.py {d1,whatsapp} OUT.json [--fused] [--mode {leaderboard,app}] [--limit N]

Prepare the audio first with `ivrit_extract.py` (needs the separate `venv-parquet`). Whole recordings go through
`mlx_whisper.transcribe`, with the app's model and, with `--fused`, the app's fused-encoder patch:
  leaderboard  mlx-whisper defaults (temperature fallback, conditioning on the previous text), Hebrew forced:
               the closest to how the ivrit.ai leaderboard runs long audio;
  app          the app's decoder settings (greedy, no conditioning) on the 30 s windows mlx-whisper cuts itself.
OUT.json maps the recording key to `{text, seconds, audio_seconds}`; keep it in the app data root (`corpus/`), not in
the repository. One model job at a time; run under `nice`. Waits for an idle CPU and normal memory pressure first
(`--no-gate` skips that).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFS = Path.home() / 'Library' / 'Caches' / 'hebrew-live-refs'
SETS = {'d1': REFS / 'ivrit-eval-d1' / 'extracted', 'whatsapp': REFS / 'ivrit-eval-whatsapp' / 'extracted'}

parser = argparse.ArgumentParser()
parser.add_argument('set', choices=list(SETS))
parser.add_argument('out', type=Path)
parser.add_argument('--fused', action='store_true')
parser.add_argument('--mode', choices=['leaderboard', 'app'], default='leaderboard')
parser.add_argument('--limit', type=int)
parser.add_argument('--no-gate', action='store_true')
args = parser.parse_args()

folder = SETS[args.set]
keys = sorted(json.loads((folder / 'texts.json').read_text(encoding='utf-8')), key=lambda key: int(key))[:args.limit]
result = json.loads(args.out.read_text()) if args.out.is_file() else {}

if not args.no_gate:
    sys.path.insert(0, str(ROOT / 'experiments' / 'nn-audit-2026-10'))
    from gated import wait_until_quiet
    if not wait_until_quiet(timeout=900):
        raise SystemExit('the Mac is not quiet (CPU idle < 60 % or memory pressure); not starting')

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HEBREW_LIVE_FUSED_ENCODER='1' if args.fused else '0')
sys.path.insert(0, str(ROOT / 'src'))
import soundfile as sf
from hebrew_live.cli import Engine


class Quiet:
    def event(self, *a, **k):
        pass


engine = Engine(ROOT / 'models', Quiet(), role='asr')
engine.direction = 'he-ru'
engine.warmup()  # loads the model and applies the fused patch when enabled
APP = dict(temperature=0.0, condition_on_previous_text=False)


def transcribe(audio):
    extra = APP if args.mode == 'app' else {}
    return engine.asr.transcribe(audio, path_or_hf_repo=engine.asr_path, language='he', task='transcribe',
                                 word_timestamps=False, verbose=None, **extra)['text']


def load(key):
    audio, rate = sf.read(folder / f'{key}.wav', dtype='float32')
    assert rate == 16000 and audio.ndim == 1
    return audio


transcribe(load(keys[0])[:16000 * 20])  # warm-up, not recorded
for done, key in enumerate(keys):
    if key in result:
        continue
    audio = load(key)
    began = time.perf_counter()
    text = transcribe(audio)
    result[key] = dict(text=text.strip(), seconds=time.perf_counter() - began, audio_seconds=len(audio) / 16000)
    args.out.write_text(json.dumps(result, ensure_ascii=False))
    print(f'{done + 1}/{len(keys)}', flush=True)
print(f'{len(result)} recordings, {sum(r["seconds"] for r in result.values()):.0f} s of inference for '
      f'{sum(r["audio_seconds"] for r in result.values()):.0f} s of audio')
