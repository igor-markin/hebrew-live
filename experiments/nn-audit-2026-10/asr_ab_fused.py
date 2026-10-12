"""Gated interleaved A/B: stock encoder attention vs fused SDPA, app ASR path (word timestamps + reuse)."""
import os
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
import mlx.core as mx
import mlx_whisper
from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
from mlx_whisper.transcribe import ModelHolder

import corpus
from gated import run_gated
from hebrew_live.whisper_reuse import reuse_alignment
from whisper_patches import set_fused

P = str(ROOT / 'models' / 'asr')
model = ModelHolder.get_model(P, mx.float16)
audio = corpus.concat(corpus.load(), 0.3)
LENS = (1.5, 5, 10)


def call(L):
    a = audio[:int(L * 16000)]
    t = time.perf_counter()
    with reuse_alignment(True):
        mlx_whisper.transcribe(a, path_or_hf_repo=P, language='he', task='transcribe', temperature=0.0,
                               word_timestamps=True, condition_on_previous_text=False, verbose=None)
    mx.synchronize()
    return time.perf_counter() - t


mel = log_mel_spectrogram(audio[:5 * 16000], n_mels=128, padding=N_SAMPLES)
seg = pad_or_trim(mel[:N_FRAMES], N_FRAMES, axis=-2).astype(mx.float16)[None]


def enc():
    t = time.perf_counter()
    f = model.encoder(seg)
    mx.eval(f)
    return time.perf_counter() - t


for on in (False, True):
    set_fused(model, on)
    [enc() for _ in range(3)]
    [call(5) for _ in range(2)]


def one_round():
    r = {}
    for on in (0, 1):
        set_fused(model, bool(on))
        r[('enc', on)] = enc()
        for L in LENS:
            r[(L, on)] = call(L)
    set_fused(model, False)
    return r


acc, tried = run_gated(one_round, want=10, budget=540)
print(f'accepted clean rounds: {len(acc)} of {tried} tried (idle>=62% before/after)')
if acc:
    g = lambda k: [a[k] for a in acc]
    f = lambda k: f'min {min(g(k)):.3f} / med {st.median(g(k)):.3f}'
    print('encoder baseline :', f(('enc', 0)))
    print('encoder fused    :', f(('enc', 1)))
    for L in LENS:
        print(f'ASR call {L:4} s  baseline: {f((L, 0))}   fused: {f((L, 1))}')
