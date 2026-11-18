"""Can Whisper recognise only the tail of a growing group?

    .venv/bin/python experiments/tail-only/prefix_probe.py OUT.json [--limit 120] [--early 14] [--full 20]

The app re-decodes the whole open group every second, although its finished sentences are
already frozen on screen. Here the frozen sentences are handed to the decoder as a forced
`prefix`, so it only has to write what follows them. For each window of continuous speech
(ivrit.ai eval-d1 interviews):

    A = decode(first `early` seconds)           -> its finished sentences are the frozen part
    B = decode(first `full` seconds)            -> baseline; expected tail = tail_after(frozen, B)
    P = decode(first `full` seconds, prefix=frozen) -> the tail only

in two modes: with timestamp tokens (how the app decodes now) and without them. Reports how
often P equals the expected tail, the word distance between them and the time of B against P.
One MLX model (Whisper). OUT.json holds speech text: keep it outside the repository.
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'streaming-asr'))
import common  # noqa: E402
import numpy as np  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('out', type=Path)
parser.add_argument('--set', default='d1', choices=['d1', 'whatsapp'])
parser.add_argument('--limit', type=int, default=120)
parser.add_argument('--early', type=float, default=14.)
parser.add_argument('--full', type=float, default=20.)
parser.add_argument('--step', type=float, default=30.)
parser.add_argument('--models', type=Path, default=Path.home() / 'Library' / 'Application Support' / 'Hebrew Live CLI' / 'models')
parser.add_argument('--no-gate', action='store_true')
parser.add_argument('--score', action='store_true', help='only print the summary of an existing OUT.json')
parser.add_argument('--mixed', action='store_true', help='add to an existing OUT.json: frozen text from decodes with '
                    'timestamps, continued decode without them; and what a continued decode writes when only noise follows')
args = parser.parse_args()

sys.path.insert(0, str(ROOT / 'src'))
from hebrew_live.sentence_freeze import _norm, pair_finished, tail_after  # noqa: E402

MODES = {'timestamps': {}, 'plain': dict(without_timestamps=True)}


def words(text):
    return [word for word in map(_norm, text.split()) if word]


def distance(left, right):
    """Word edit distance."""
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        previous, row[0] = row[0], i
        for j, b in enumerate(right, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (a != b))
    return row[-1]


def summary(rows):
    for mode in (*MODES, 'mixed'):
        used = [row[mode] for row in rows if mode in row and row[mode]['frozen']]
        if not used:
            continue
        same = sum(words(item['prefixed']) == words(item['expected']) for item in used)
        edits = sum(distance(words(item['prefixed']), words(item['expected'])) for item in used)
        total = sum(len(words(item['expected'])) for item in used)
        drift = sum(words(item['baseline'])[:len(words(item['frozen']))] != words(item['frozen']) for item in used)
        empty = sum(not item['prefixed'].strip() and bool(item['expected'].strip()) for item in used)
        base = [item['baseline_seconds'] for item in used]; tail = [item['prefixed_seconds'] for item in used]
        saved = [b - p for b, p in zip(base, tail)]
        share = statistics.median(len(words(item['frozen'])) / max(1, len(words(item['baseline']))) for item in used)
        print(f'{mode}: {len(used)} of {len(rows)} windows have a frozen part (median {share:.0%} of the words)')
        print(f'  tail identical to the baseline tail: {same}/{len(used)} ({same / len(used):.0%}); '
              f'word distance {edits}/{total} ({edits / max(1, total):.1%}); empty tail {empty}')
        print(f'  baseline itself rewrote the frozen part: {drift}/{len(used)}')
        print(f'  decode time p50: whole {statistics.median(base):.3f} s, tail {statistics.median(tail):.3f} s; '
              f'paired saving p50 {statistics.median(saved):.3f} s, faster in {sum(s > 0 for s in saved)}/{len(used)}')


def accuracy(rows):
    """WER against the recording's reference, for runs with `--step` equal to `--full` (the
    windows then cover a recording end to end). `whole`: every window decoded whole. `shown`:
    what the app shows today - frozen sentences plus the rest of a whole decode. `tail`:
    frozen sentences plus the continued decode. Window edges cut words in all three alike."""
    sys.path.insert(0, str(ROOT / 'experiments' / 'corpus'))
    from normalize import normalize
    reference = common.references(args.set)
    for mode in (*MODES, 'mixed'):
        if not all(mode in row for row in rows):
            continue
        errors = dict(whole=0, shown=0, tail=0); total = 0
        for key in sorted({row['key'] for row in rows}, key=int):
            parts = dict(whole=[], shown=[], tail=[])
            for row in sorted((row for row in rows if row['key'] == key), key=lambda row: row['start']):
                item = row[mode]
                parts['whole'].append(item['baseline'])
                parts['shown'].append(item['frozen'] + ' ' + item['expected'] if item['frozen'] else item['baseline'])
                parts['tail'].append(item['frozen'] + ' ' + item['prefixed'] if item['frozen'] else item['baseline'])
            truth = normalize(reference[key]).split(); total += len(truth)
            for name, texts in parts.items():
                errors[name] += distance(truth, normalize(' '.join(texts)).split())
        print(f'{mode}: WER over {total} reference words - ' +
              ', '.join(f'{name} {count / total:.2%} ({count} errors)' for name, count in errors.items()))


if args.score:
    rows = json.loads(args.out.read_text())['rows']
    summary(rows)
    if args.step == args.full:
        accuracy(rows)
    quiet = [row['quiet'] for row in rows if row.get('quiet')]
    if quiet:
        print(f'only noise after the frozen text, {len(quiet)} windows: continued decode wrote '
              f'{sum(len(words(item["continued"])) for item in quiet)} words in {sum(bool(words(item["continued"])) for item in quiet)} windows, '
              f'a whole decode with timestamps added {sum(len(words(item["whole_tail"])) for item in quiet)} words in '
              f'{sum(bool(words(item["whole_tail"])) for item in quiet)} windows')
    pause = [row['pause'] for row in rows if row.get('pause')]
    if pause:
        changed = [item for item in pause if words(item['followed']) != words(item['without'])]
        longer = sum(max(0, len(words(item['followed'])) - len(words(item['without']))) for item in changed)
        shorter = sum(max(0, len(words(item['without'])) - len(words(item['followed']))) for item in changed)
        print(f'pause after the speech, {len(pause)} windows: the continued decode changed in {len(changed)} '
              f'({longer} words added, {shorter} lost)')
    raise SystemExit

if not args.no_gate:
    sys.path.insert(0, str(ROOT / 'experiments' / 'nn-audit-2026-10'))
    from gated import wait_until_quiet
    if not wait_until_quiet(need_idle=50, timeout=1800):
        raise SystemExit('memory pressure is not normal or the CPU is busy; not starting')

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
from hebrew_live.cli import Engine  # noqa: E402

engine = Engine(args.models, type('Quiet', (), {'event': lambda *a, **k: None})(), role='asr')
engine.direction = 'he-ru'
engine.warmup()


def decode(audio, **options):
    began = time.perf_counter()
    result = engine.asr.transcribe(audio, path_or_hf_repo=engine.asr_path, language='he', task='transcribe',
                                   temperature=0.0, word_timestamps=False, condition_on_previous_text=False,
                                   verbose=None, **options)
    return result['text'].strip(), time.perf_counter() - began


if args.mixed:
    from hebrew_live.sentence_freeze import finished, split_sentences
    saved = json.loads(args.out.read_text())
    early_samples = round(float(saved['args']['early']) * common.RATE); full_samples = round(float(saved['args']['full']) * common.RATE)
    noise = common.synthetic('pink_-50', seconds=4)[:2 * common.RATE]
    audio_of = {}
    for index, row in enumerate(saved['rows']):
        if row['key'] not in audio_of:
            audio_of = {row['key']: common.load(args.set, row['key'])}
        start = round(row['start'] * common.RATE)
        audio = audio_of[row['key']][start:start + full_samples]
        if 'mixed' not in row:      # finished steps of an earlier run are kept
            item = dict(row['timestamps'])
            if item['frozen']:
                item['prefixed'], item['prefixed_seconds'] = decode(audio, prefix=item['frozen'], without_timestamps=True)
            row['mixed'] = item
        # The speaker stopped right where the recognised text ends: every sentence of the
        # early decode is finished, and only a noise floor follows it.
        early = row['timestamps']['early']
        if 'quiet' not in row and early and all(finished(sentence) for sentence in split_sentences(early)):
            ended = np.concatenate((audio[:early_samples], noise)).astype(np.float32)
            continued, _ = decode(ended, prefix=early, without_timestamps=True)
            whole, _ = decode(ended)
            row['quiet'] = dict(continued=continued, whole_tail=tail_after(early, whole))
        # A group closes after a pause: does the continued decode add words when a noise
        # floor follows the speech? Same audio and frozen text, with and without the pause.
        count, sentences = pair_finished(early, False)
        if count and 'pause' not in row:
            frozen = ' '.join(sentences[:count])
            speech = audio[:early_samples]
            row['pause'] = dict(without=decode(speech, prefix=frozen, without_timestamps=True)[0],
                                followed=decode(np.concatenate((speech, noise)).astype(np.float32), prefix=frozen,
                                                without_timestamps=True)[0])
        if index % 20 == 19:
            common.save(args.out, saved); print(f'{index + 1}/{len(saved["rows"])}', flush=True)
    common.save(args.out, saved)
    summary(saved['rows'])
    raise SystemExit

windows = []
for key in common.keys(args.set):
    audio = common.load(args.set, key)
    for start in range(0, len(audio) - round(args.full * common.RATE), round(args.step * common.RATE)):
        windows.append((key, start / common.RATE, audio[start:start + round(args.full * common.RATE)]))
windows = windows[::max(1, len(windows) // args.limit)][:args.limit]
decode(windows[0][2])  # warm-up, not recorded
rows = []
for index, (key, start, audio) in enumerate(windows):
    row = dict(key=key, start=start)
    for mode, options in MODES.items():
        early, _ = decode(audio[:round(args.early * common.RATE)], **options)
        count, sentences = pair_finished(early, False)
        frozen = ' '.join(sentences[:count])
        baseline, baseline_seconds = decode(audio, **options)
        item = dict(early=early, frozen=frozen, baseline=baseline, baseline_seconds=baseline_seconds)
        if frozen:
            item['expected'] = tail_after(frozen, baseline)
            item['prefixed'], item['prefixed_seconds'] = decode(audio, prefix=frozen, **options)
        row[mode] = item
    rows.append(row)
    if index % 10 == 9:
        common.save(args.out, dict(args={k: str(v) for k, v in vars(args).items()}, rows=rows))
        print(f'{index + 1}/{len(windows)}', flush=True)
common.save(args.out, dict(args={k: str(v) for k, v in vars(args).items()}, rows=rows))
summary(rows)
