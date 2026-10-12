"""Nightly local regression run (plan 4.4): tests, identity checks, replay A/B, one report.

    .venv/bin/python experiments/corpus/nightly.py SESSION_DIR [--minutes 7] [--rounds 2] [--out docs/NIGHTLY.md]

Runs, in order and one MLX job at a time: the unit suite, MT identity (stock vs fast generate),
ASR window identity on the real recording, and the end-to-end replay A/B (stock switches vs
current defaults). The report lists the input hashes (git commit, library versions, corpus
manifest, recording sha256) and each step's printed summary. The scripts print counts and
timings only, never speech, so the report is safe to keep next to the code.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / '.venv' / 'bin' / 'python')


def run(title, command, pythonpath=None):
    began = time.time()
    env = dict(os.environ, PYTHONPATH=pythonpath) if pythonpath else None
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=env)
    output = (result.stdout + result.stderr).strip().splitlines()
    tail = [line for line in output if line.strip()][-14:]
    return dict(title=title, ok=result.returncode == 0, seconds=round(time.time() - began), tail=tail)


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def inputs(session):
    manifest = ROOT / 'experiments' / 'corpus' / 'manifest.json'
    versions = {name: importlib.metadata.version(name) for name in ('mlx', 'mlx-lm', 'mlx-whisper')}
    return dict(
        commit=git('rev-parse', '--short', 'HEAD'),
        uncommitted_files=len(git('status', '--porcelain').splitlines()),
        source_sha256=hashlib.sha256(b''.join(
            p.read_bytes() for p in sorted((ROOT / 'src' / 'hebrew_live').glob('*.py')))).hexdigest()[:16],
        versions=versions,
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest()[:16] if manifest.is_file() else None,
        session=session.name,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--minutes', default='7')
    parser.add_argument('--rounds', default='2')
    parser.add_argument('--out', type=Path, default=ROOT / 'docs' / 'NIGHTLY.md')
    parser.add_argument('--skip-replay', action='store_true')
    args = parser.parse_args()
    steps = [
        run('unit tests', [PYTHON, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q'], str(ROOT / 'src')),
        run('metrics tests', [PYTHON, '-m', 'unittest', 'discover', '-s', 'experiments/corpus', '-q']),
        run('MT identity (generate_step vs stream_generate)',
            [PYTHON, 'experiments/nn-audit-2026-10/mt_identity.py']),
        run('ASR window identity (real recording)',
            [PYTHON, 'experiments/corpus/asr_window_identity.py', str(args.session)]),
    ]
    if not args.skip_replay:
        steps.append(run('replay A/B (stock vs defaults)', [PYTHON, 'experiments/corpus/e2e_ab.py', str(args.session),
                                                           '--minutes', args.minutes, '--rounds', args.rounds]))
    lines = [f'# Nightly regression, {datetime.now():%Y-%m-%d %H:%M}', '', '```json',
             json.dumps(inputs(args.session), indent=2), '```', '']
    for step in steps:
        lines += [f'## {"PASS" if step["ok"] else "FAIL"}: {step["title"]} ({step["seconds"]} s)', '', '```']
        lines += step['tail'] + ['```', '']
    args.out.write_text('\n'.join(lines))
    print(f'wrote {args.out}: ' + ', '.join(f'{s["title"]}={"ok" if s["ok"] else "FAIL"}' for s in steps))
    return 0 if all(s['ok'] for s in steps) else 1


if __name__ == '__main__':
    sys.exit(main())
