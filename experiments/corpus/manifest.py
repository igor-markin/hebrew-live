"""Build the corpus manifest from session archives (audio stays where the app keeps it).

    .venv/bin/python experiments/corpus/manifest.py [--data-root DIR] [--scenario NAME]

Entries carry the audio path relative to the data root, sha256, duration, date, direction and a
scenario label. Labels already set in an existing manifest are kept (matched by sha256), so
re-running after new sessions only adds rows. No speech text and no absolute paths are written.
"""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

DEFAULT_ROOT = Path.home() / 'Library' / 'Application Support' / 'Hebrew Live CLI'
OUT = Path(__file__).with_name('manifest.json')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def entries(root, default_scenario):
    for summary_path in sorted((root / 'logs').glob('*/session.json')):
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        stamp = datetime.strptime(summary_path.parent.name[:15], '%Y%m%d-%H%M%S')
        for part, info in summary.get('parts', {}).items():
            audio = next(summary_path.parent.glob(f'{int(part):03d}-*.audio.wav'), None)
            if audio is None:
                continue
            accepted = summary.get('accepted', {}).get(part, {})
            yield dict(
                id=f'{summary_path.parent.name}/{part}',
                audio=str(audio.relative_to(root)),
                sha256=digest(audio),
                duration_seconds=round(accepted.get('duration', 0.), 1),
                sample_rate=info.get('rate'),
                date=stamp.date().isoformat(),
                direction=info.get('direction'),
                scenario=default_scenario,
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--scenario', default='unlabeled')
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    known = {}
    if args.out.is_file():
        known = {item['sha256']: item for item in json.loads(args.out.read_text())['recordings']}
    rows = []
    for row in entries(args.data_root.expanduser(), args.scenario):
        row['scenario'] = known.get(row['sha256'], {}).get('scenario', row['scenario'])
        rows.append(row)
    total = sum(row['duration_seconds'] for row in rows)
    args.out.write_text(json.dumps(dict(schema_version=1, total_minutes=round(total / 60, 1), recordings=rows),
                                   ensure_ascii=False, indent=2) + '\n')
    print(f'{len(rows)} recordings, {total / 60:.1f} min -> {args.out.name}')


if __name__ == '__main__':
    main()
