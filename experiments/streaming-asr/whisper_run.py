"""Whisper Turbo as Hebrew Live runs it, on the same inputs as zipformer_run.py (paired comparison).

    .venv/bin/python experiments/streaming-asr/whisper_run.py {d1,whatsapp,fleurs,synthetic} OUT.json [--level -40] [--limit N]

Read-only use of the app: imports src/hebrew_live (Engine) and the installed Whisper model from
~/Library/Application Support/Hebrew Live CLI/models (override with --models). Same decoding as
experiments/corpus: ivrit.ai sets as whole recordings in app mode (greedy, no conditioning, 30 s windows cut by
mlx-whisper); FLEURS clips through Engine.recognize like fleurs_asr.py; synthetic signals in 20 s pieces (the
app's longest phrase) through Engine.recognize. Note: in the app, Silero VAD decides what reaches Whisper, so the
synthetic run shows what Whisper says IF noise passes the VAD, not what the app shows.
Waits for normal memory pressure and an idle CPU first (experiments/nn-audit-2026-10/gated.py). One MLX model only.
"""
import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import common  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('set', choices=['d1', 'whatsapp', 'fleurs', 'synthetic'])
parser.add_argument('out', type=Path)
parser.add_argument('--level', type=float)
parser.add_argument('--floor', type=float, help='add a pink-noise floor at this RMS dBFS after levelling')
parser.add_argument('--limit', type=int)
parser.add_argument('--models', type=Path, default=Path.home() / 'Library' / 'Application Support' / 'Hebrew Live CLI' / 'models')
parser.add_argument('--no-gate', action='store_true')
args = parser.parse_args()

if not args.no_gate:
    sys.path.insert(0, str(ROOT / 'experiments' / 'nn-audit-2026-10'))
    from gated import wait_until_quiet
    if not wait_until_quiet(need_idle=50, timeout=1800):
        raise SystemExit('memory pressure is not normal or the CPU is busy; not starting')

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))
from hebrew_live.cli import Engine  # noqa: E402


class Quiet:
    def event(self, *a, **k):
        pass


engine = Engine(args.models, Quiet(), role='asr')
engine.direction = 'he-ru'
engine.warmup()
APP = dict(temperature=0.0, condition_on_previous_text=False)


def whole(audio):
    return engine.asr.transcribe(audio, path_or_hf_repo=engine.asr_path, language='he', task='transcribe',
                                 word_timestamps=False, verbose=None, **APP)['text']


def phrase(audio):
    return engine.recognize(audio, 0., preliminary=False, mode='phrases', align_words=False)


if args.set == 'synthetic':
    items = common.SYNTHETIC[:args.limit]

    def transcribe(audio):
        return ' | '.join(phrase(audio[i:i + 20 * common.RATE]).strip() for i in range(0, len(audio), 20 * common.RATE))
    load = common.synthetic
else:
    items = common.keys(args.set, args.limit)
    transcribe = phrase if args.set == 'fleurs' else whole

    def load(key):
        return common.load(args.set, key)

result = json.loads(args.out.read_text()) if args.out.is_file() else {}
transcribe(load(items[0])[:common.RATE * 10])  # warm-up, not recorded
for done, key in enumerate(items):
    if key in result:
        continue
    audio = load(key)
    gain = 0.
    if args.level is not None:
        audio, gain = common.set_level(audio, args.level)
    if args.floor is not None:
        audio = common.add_floor(audio, args.floor, seed=done)
    began = time.perf_counter()
    text = transcribe(audio)
    result[key] = dict(text=text.strip(), seconds=time.perf_counter() - began, audio_seconds=len(audio) / common.RATE, gain_db=gain)
    if done % 25 == 24 or args.set != 'fleurs':
        common.save(args.out, result)
        print(f'{done + 1}/{len(items)}', flush=True)
result['_meta'] = dict(vars(args), out=str(args.out), models=str(args.models),
                       peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20)
result['_meta'] = {k: str(v) if isinstance(v, Path) else v for k, v in result['_meta'].items()}
common.save(args.out, result)
rows = [r for k, r in result.items() if k != '_meta']
print(f'{len(rows)} items, {sum(r["audio_seconds"] for r in rows):.0f} s audio, inference {sum(r["seconds"] for r in rows):.0f} s')
