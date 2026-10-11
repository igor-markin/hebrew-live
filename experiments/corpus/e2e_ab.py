"""End-to-end A/B of the live pipeline on a real recording, replayed at 1x.

Variants are environment dictionaries (rollback switches of the Phase 1 items); each round
runs every variant once in shuffled order through `he-ru benchmark`, then prints the live
metrics of `scripts/diagnose_latency.py` per variant. Runs one MLX job at a time and waits for
an idle CPU before starting. Speech never reaches the output.

    .venv/bin/python experiments/corpus/e2e_ab.py SESSION_DIR --minutes 7 --rounds 2 \
        [--start SECONDS]   # default: the densest stretch of speech
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'experiments' / 'nn-audit-2026-10'))
from diagnose_latency import summarize
from gated import wait_until_quiet

STOCK = {'HEBREW_LIVE_MT_GENERATE': 'stock', 'HEBREW_LIVE_MT_INTERRUPT': '0', 'HEBREW_LIVE_TEXT_ONLY_DRAFT': '0',
         'HEBREW_LIVE_MT_MAX_TOKENS': '256', 'HEBREW_LIVE_MT_SPECULATE': '0',
         'HEBREW_LIVE_LOOP_STOP': '0'}
CATALOG = {
    'stock': STOCK,
    'phase1': {},
    'phase1_no_interrupt': {'HEBREW_LIVE_MT_INTERRUPT': '0'},
    # one Phase 1 change on top of the rollback baseline, to find which one moves a metric
    'stock_textonly': {**STOCK, 'HEBREW_LIVE_TEXT_ONLY_DRAFT': '1'},
    'stock_fastgen': {**STOCK, 'HEBREW_LIVE_MT_GENERATE': 'fast'},
    'hold_last_word': {'HEBREW_LIVE_HOLD_LAST_WORD': '1'},
    'first_1.0': {'HEBREW_LIVE_TIMING': '1.0,1.0,0,4,0.6'},
    'interval_0.5': {'HEBREW_LIVE_TIMING': '1.5,0.5,0,4,0.6'},
    'fused_encoder': {'HEBREW_LIVE_FUSED_ENCODER': '1'},
    'mt_draft': {'HEBREW_LIVE_MT_SPECULATE': '1'},
    'mt_draft_stable': {'HEBREW_LIVE_MT_SPECULATE': '1', 'HEBREW_LIVE_MT_SPECULATE_TOLERANCE': '0.3'},
    'fast_draft': {'HEBREW_LIVE_FUSED_ENCODER': '1', 'HEBREW_LIVE_TIMING': '1.0,1.0,0,4,0.6'},
}
# E2E_VARIANTS="stock phase1 hold_last_word" picks what to run (default: stock phase1)
VARIANTS = {name: CATALOG[name] for name in os.environ.get('E2E_VARIANTS', 'stock phase1').split()}


def densest_start(session, minutes):
    """Start second of the window with the most distinct audio sent to ASR."""
    diag = next(session.glob('001-*.diagnostics.jsonl'))
    spans = []
    for line in diag.open(encoding='utf-8'):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('event') == 'live_asr':
            spans.append((event['start'], event['end']))
    width = minutes * 60
    best, best_start = -1, 0.
    for start in np.arange(0, max(end for _, end in spans) - width, 15.):
        covered = sum(max(0., min(e, start + width) - max(s, start)) for s, e in spans)
        if covered > best:
            best, best_start = covered, float(start)
    return best_start


def cut(session, start, minutes, out):
    source = next(session.glob('001-*.audio.wav'))
    with sf.SoundFile(source) as audio:
        audio.seek(int(start * audio.samplerate))
        data = audio.read(int(minutes * 60 * audio.samplerate), dtype='float32')
        sf.write(out, data, audio.samplerate, subtype='FLOAT')


def run(variant, wav, logs, direction):
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), **VARIANTS[variant])
    command = [sys.executable, '-m', 'hebrew_live.cli', '--models', str(ROOT / 'models'), '--log-dir', str(logs),
               'benchmark', str(wav), '--ui', 'plain', '--no-open-browser', '--no-save-raw-audio',
               '--direction', direction]
    result = subprocess.run(command, env=env, capture_output=True, text=True, cwd=ROOT)
    match = re.search(r'Session / diagnostics: (\S+)', result.stderr)
    if not match:
        raise SystemExit('benchmark did not report a session folder')
    return next(Path(match.group(1)).glob('*.diagnostics.jsonl'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--minutes', type=float, default=7)
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--start', type=float)
    parser.add_argument('--direction', default='he-ru')
    parser.add_argument('--wait-minutes', type=float, default=60, help='how long to wait for a quiet Mac before each run')
    parser.add_argument('--out', type=Path, help='write the summaries as JSON')
    args = parser.parse_args()
    start = args.start if args.start is not None else densest_start(args.session, args.minutes)
    results = {name: [] for name in VARIANTS}
    with tempfile.TemporaryDirectory() as work:
        wav = Path(work) / 'cut.wav'
        cut(args.session, start, args.minutes, wav)
        print(f'window: {args.minutes} min from {start:.0f}s', flush=True)
        for index in range(args.rounds):
            names = list(VARIANTS)
            random.shuffle(names)
            for name in names:
                # Both models are resident (about 4.4 GB MLX): never start under memory pressure.
                if not wait_until_quiet(timeout=args.wait_minutes * 60):
                    raise SystemExit('the Mac stayed busy or short of memory; no run was started')
                log = run(name, wav, Path(work) / 'logs', args.direction)
                results[name].append(summarize(log))
                print(f'round {index + 1} {name}: done', flush=True)
    keys = ('time_to_first_visible_draft_seconds', 'closed_translation_audio_lag_seconds',
            'first_completed_translation_audio_lag_seconds', 'asr_queue_wait_seconds', 'asr_duration_seconds',
            'mt_duration_seconds', 'normalized_erasure', 'stable_word_seconds')
    for name, runs in results.items():
        print(f'== {name}')
        for key in keys:
            print(f'  {key}: ' + ' | '.join(f'p50 {r[key]["p50"]} p95 {r[key]["p95"]} n={r[key]["count"]}' for r in runs))
    if args.out:
        args.out.write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
