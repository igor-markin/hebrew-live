"""Replay WAV recordings through the live app with different settings and compare summary.json.

Each run is `he-ru benchmark WAV --ui browser --publication draft` at 1x with one variant's
environment, while headless Chrome keeps the live window open (window_watch.mjs), so the
numbers include what the window drew and when. Variants run in shuffled order per round,
one at a time. Output: one JSON line per run and a table of medians per variant. No speech
text is printed.

    PLAYWRIGHT_CORE=.../node_modules/playwright-core .venv/bin/python \
        experiments/corpus/replay_variants.py A.wav B.wav --variants default calm --rounds 2 --out runs.jsonl

The models folder is a folder of symlinks to the installed models with no saved settings,
and HEBREW_LIVE_HOME is a fresh folder, so saved timing and the owner's vocabulary never
mix into a variant.
"""
import argparse
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from hebrew_live.session_summary import read_events, write as write_summary  # noqa: E402

INSTALLED = Path.home() / 'Library' / 'Application Support' / 'Hebrew Live CLI' / 'models'
VARIANTS = {
    'default': {},
    # The defaults before 23.11.2026, spelled out.
    'previous': {'HEBREW_LIVE_CALM_DRAFTS': '0', 'HEBREW_LIVE_TIMING': '1,1,0,4,0.6'},
    'calm': {'HEBREW_LIVE_CALM_DRAFTS': '1'},
    'speculate': {'HEBREW_LIVE_MT_SPECULATE': '1', 'HEBREW_LIVE_MT_SPECULATE_TOLERANCE': '0.3'},
    'fast': {'HEBREW_LIVE_TIMING': '0.7,0.7,0,4,0.6'},
    'calm_speculate': {'HEBREW_LIVE_CALM_DRAFTS': '1', 'HEBREW_LIVE_MT_SPECULATE': '1',
                       'HEBREW_LIVE_MT_SPECULATE_TOLERANCE': '0.3'},
    'calm_fast': {'HEBREW_LIVE_CALM_DRAFTS': '1', 'HEBREW_LIVE_TIMING': '0.7,0.7,0,4,0.6'},
    'speculate_fast': {'HEBREW_LIVE_MT_SPECULATE': '1', 'HEBREW_LIVE_MT_SPECULATE_TOLERANCE': '0.3',
                       'HEBREW_LIVE_TIMING': '0.7,0.7,0,4,0.6'},
    'all': {'HEBREW_LIVE_CALM_DRAFTS': '1', 'HEBREW_LIVE_MT_SPECULATE': '1',
            'HEBREW_LIVE_MT_SPECULATE_TOLERANCE': '0.3', 'HEBREW_LIVE_TIMING': '0.7,0.7,0,4,0.6'},
    'frozen_view': {'HEBREW_LIVE_SENTENCE_CONTEXT': '1'},
    # Needs sherpa-onnx in the venv (uv sync --group hybrid) and HEBREW_LIVE_HYBRID_MODEL set.
    'hybrid': {'HEBREW_LIVE_HYBRID': '1'},
}
# (label, path in summary.json); lower is better for all of them.
METRICS = [
    ('he_p50', 'screen.hebrew_lag.p50'), ('he_p95', 'screen.hebrew_lag.p95'),
    ('tr_p50', 'screen.translation_lag.p50'), ('tr_p95', 'screen.translation_lag.p95'),
    ('first_tr_p50', 'screen.first_translation_lag.p50'),
    ('tr_erased', 'screen.translation_moves.erased_words'),
    ('tr_erasing_versions', 'screen.translation_moves.versions_with_erasure'),
    ('tr_finished_rewritten', 'screen.translation_moves.finished_sentences_rewritten'),
    ('he_erased', 'screen.hebrew_moves.erased_words'),
    ('closed_changes', 'screen.translation_moves.changes_after_closed'),
    ('renders', 'screen.renders'),
    ('mt_interrupted', 'translation_runs.interrupted'),
    ('mt_p50', 'backend.mt_seconds.p50'), ('asr_p50', 'backend.asr_seconds.p50'),
    ('whisper_s', 'backend.whisper_total_seconds'),
    ('he_word_p50', 'backend.hebrew_word_lag.p50'),
    ('close_erased', 'backend.closing_vs_last_draft.erased_words'),
]


def value(summary, path):
    for key in path.split('.'):
        summary = summary.get(key) if isinstance(summary, dict) else None
    return summary


def models_folder(target):
    target.mkdir(parents=True)
    for item in INSTALLED.iterdir():
        if item.name.startswith('.'):
            continue
        (target / item.name).symlink_to(item)
    return target


def closed_text(session):
    """The Hebrew of every closed version, in order: the session's final transcript."""
    return ' '.join((event.get('current') or {}).get('source', '') for event in read_events(session)
                    if event.get('event') == 'live_publication'
                    and event.get('stage') in ('closed', 'technical')).strip()


def run(wav, variant, workdir, watcher, hyp_dir=None):
    logs = workdir / 'logs'
    env = dict(os.environ, **VARIANTS[variant], HEBREW_LIVE_HOME=str(workdir / 'home'))
    env.pop('HEBREW_LIVE_DESKTOP_MANAGED', None)
    command = [str(ROOT / '.venv/bin/he-ru'), '--models', str(workdir / 'models'), '--log-dir', str(logs),
               'benchmark', str(wav), '--ui', 'browser', '--publication', 'draft', '--no-open-browser',
               '--direction', 'he-ru', '--no-save-raw-audio']
    started = time.monotonic()
    engine = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    window = None
    errors = []
    for line in engine.stderr:
        match = re.search(r'(http://127\.0\.0\.1:\d+/[^/\s]+/)', line)
        if match and window is None:
            window = subprocess.Popen(['node', str(watcher), match.group(1) + 'live/'], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        elif 'Error' in line or 'Traceback' in line:
            errors.append(line.strip()[:200])
    engine.wait()
    if window is not None:
        try:
            window.wait(30)
        except subprocess.TimeoutExpired:
            window.kill()
    session = max(logs.glob('*/'), key=lambda path: path.stat().st_mtime)
    summary = write_summary(session)
    if hyp_dir is not None:
        (hyp_dir / f'{Path(wav).stem}.{variant}.{workdir.name}.txt').write_text(closed_text(session) + '\n')
    return dict(wav=Path(wav).name, variant=variant, seconds=round(time.monotonic() - started, 1),
                exit=engine.returncode, window=window is not None, errors=errors[:3],
                **{label: value(summary, path) for label, path in METRICS})


def table(rows, variants):
    print('\nmedian over runs (all recordings):')
    widths = [max(len(label) + 2, 9) for label, _ in METRICS]
    print('variant'.ljust(16) + ''.join(label.rjust(width) for (label, _), width in zip(METRICS, widths)))
    for variant in variants:
        mine = [row for row in rows if row['variant'] == variant]
        cells = []
        for (label, _), width in zip(METRICS, widths):
            values = [row[label] for row in mine if isinstance(row[label], (int, float))]
            cells.append(f'{statistics.median(values):{width}.3g}' if values else '-'.rjust(width))
        print(variant.ljust(16) + ''.join(cells))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('wavs', nargs='+', type=Path)
    parser.add_argument('--variants', nargs='+', default=['default', 'calm'], choices=sorted(VARIANTS))
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261123)
    parser.add_argument('--hyp-dir', type=Path, help='write each run\'s closed Hebrew here (speech text: keep it '
                        'outside the repository) for WER against a reference')
    args = parser.parse_args()
    watcher = Path(__file__).with_name('window_watch.mjs')
    random.seed(args.seed)
    rows = []
    with tempfile.TemporaryDirectory(prefix='hebrew-live-replay-') as folder:
        base = Path(folder)
        models = models_folder(base / 'models')
        for round_number in range(args.rounds):
            plan = [(wav, variant) for wav in args.wavs for variant in args.variants]
            random.shuffle(plan)
            for wav, variant in plan:
                workdir = base / f'run-{len(rows)}'
                workdir.mkdir()
                (workdir / 'models').symlink_to(models)
                row = dict(run(wav, variant, workdir, watcher, args.hyp_dir), round=round_number)
                rows.append(row)
                with args.out.open('a') as file:
                    file.write(json.dumps(row, ensure_ascii=False) + '\n')
                print(json.dumps(row, ensure_ascii=False), flush=True)
                shutil.rmtree(workdir, ignore_errors=True)
    table(rows, args.variants)


if __name__ == '__main__':
    main()
