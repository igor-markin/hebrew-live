"""Unpack an ivrit.ai eval parquet into 16 kHz mono WAV files plus `texts.json` (row key -> reference text).

    ~/Library/Caches/hebrew-live-refs/venv-parquet/bin/python -I -B experiments/corpus/ivrit_extract.py \
        ~/Library/Caches/hebrew-live-refs/ivrit-eval-whatsapp

Reads `<dir>/data/test-*.parquet`, writes `<dir>/extracted/<key>.wav` and `<dir>/extracted/texts.json`, where
the key is the original file stem (`1` for `1.ogg`). `pyarrow` is not a dependency of the project: the separate
`venv-parquet` environment holds it. The reference texts are public ivrit.ai data (license in the dataset
folder), but they stay outside the repository like the audio.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pyarrow.parquet as pq

root = Path(sys.argv[1])
out = root / 'extracted'
out.mkdir(exist_ok=True)
texts = {}
for part in sorted((root / 'data').glob('test-*.parquet')):
    for row in pq.read_table(part).to_pylist():
        audio = row['audio']
        key = Path(audio['path']).stem
        suffix = Path(audio['path']).suffix or '.bin'
        with tempfile.NamedTemporaryFile(suffix=suffix) as source:
            source.write(audio['bytes'])
            source.flush()
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', source.name, '-ac', '1', '-ar', '16000', str(out / f'{key}.wav')], check=True)
        texts[key] = row['text']
(out / 'texts.json').write_text(json.dumps(texts, ensure_ascii=False), encoding='utf-8')
print(len(texts), 'recordings written to', out)
