"""Cost of one ASR snapshot vs window length through the app's own Engine.recognize path."""
import os
import statistics as st
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                  HEBREW_LIVE_HOME=tempfile.mkdtemp(prefix='hl-audit-'))
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
import mlx.core as mx

import corpus
from hebrew_live.cli import Engine


class Log:
    def __init__(self):
        self.ev = []

    def event(self, n, **k):
        self.ev.append((n, k))

    def error(self, e):
        pass


log = Log()
e = Engine(ROOT / 'models', log, language='he', role='asr')
e.direction = 'he-en'
t = time.monotonic()
e.warmup()
print('warmup', round(time.monotonic() - t, 2), 's')
audio = corpus.concat(corpus.load(), 0.3)
lens = [1.5, 2.5, 3.5, 5, 7.5, 10, 15, 20, 30]
res = {L: [] for L in lens}
for rnd in range(5):
    for L in lens:
        a = audio[:int(L * 16000)]
        t = time.monotonic()
        e.recognize(a, 0., preliminary=True, mode='phrases', align_words=True)
        mx.synchronize()
        res[L].append(time.monotonic() - t)
print('len_s  median_s  min_s  max_s   (app path: word_timestamps=True, encoder reuse on)')
for L in lens:
    r = res[L]
    print(f'{L:5}  {st.median(r):7.3f}  {min(r):6.3f}  {max(r):6.3f}   rounds={[round(x, 2) for x in r]}')
reuse = [k for n, k in log.ev if n == 'whisper_encoder_reuse']
print('encoder_reuse events:', reuse[:2], '... total', len(reuse))
print('peak MLX mem GB', round(mx.get_peak_memory() / 1e9, 2))
