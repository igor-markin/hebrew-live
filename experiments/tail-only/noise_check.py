"""Does decoding without timestamp tokens invent more text on silence and noise?

    .venv/bin/python experiments/tail-only/noise_check.py

The 11 synthetic signals of experiments/streaming-asr (60 s each, in 20 s pieces - the app's
longest phrase) through Engine.recognize, as the app decodes now and with `plain=True`.
Prints words per signal. Whisper sees the noise directly here; in the app Silero VAD decides
what reaches it. One MLX model.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments' / 'streaming-asr'))
sys.path.insert(0, str(ROOT / 'experiments' / 'nn-audit-2026-10'))
sys.path.insert(0, str(ROOT / 'src'))
import common  # noqa: E402
from gated import wait_until_quiet  # noqa: E402

if not wait_until_quiet(need_idle=50, timeout=1800):
    raise SystemExit('memory pressure is not normal or the CPU is busy; not starting')
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
from hebrew_live.cli import Engine  # noqa: E402

models = Path.home() / 'Library' / 'Application Support' / 'Hebrew Live CLI' / 'models'
engine = Engine(models, type('Quiet', (), {'event': lambda *a, **k: None})(), role='asr')
engine.direction = 'he-ru'
engine.warmup()
total = dict(timestamps=0, plain=0)
for kind in common.SYNTHETIC:
    audio = common.synthetic(kind)
    counts = {}
    for name, options in (('timestamps', {}), ('plain', dict(plain=True))):
        counts[name] = sum(len(engine.recognize(audio[start:start + 20 * common.RATE], 0., preliminary=False,
                                                mode='phrases', align_words=False, **options).split())
                           for start in range(0, len(audio), 20 * common.RATE))
        total[name] += counts[name]
    print(f'{kind}: timestamps {counts["timestamps"]} words, plain {counts["plain"]} words', flush=True)
print(f'total: timestamps {total["timestamps"]}, plain {total["plain"]}')
