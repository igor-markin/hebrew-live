"""Where one ASR snapshot spends its time (5 s of audio) plus a fused-attention encoder probe."""
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
from hebrew_live.whisper_reuse import reuse_alignment
from whisper_patches import set_fused

P = str(ROOT / 'models' / 'asr')
model = ModelHolder.get_model(P, mx.float16)
audio = corpus.concat(corpus.load(), 0.3)[:5 * 16000]


def T(fn, n=7, warm=2):
    for _ in range(warm):
        fn()
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        mx.synchronize()
        xs.append(time.perf_counter() - t)
    return st.median(xs), min(xs)


def mel_fn():
    m = log_mel_spectrogram(audio, n_mels=128, padding=N_SAMPLES)
    mx.eval(m)
    return m


m = mel_fn()
seg = pad_or_trim(m[:N_FRAMES], N_FRAMES, axis=-2).astype(mx.float16)[None]


def enc_fn():
    f = model.encoder(seg)
    mx.eval(f)
    return f


def tr(wt, reuse):
    def fn():
        with reuse_alignment(reuse):
            mlx_whisper.transcribe(audio, path_or_hf_repo=P, language='he', task='transcribe', temperature=0.0,
                                   word_timestamps=wt, condition_on_previous_text=False, verbose=None)
    return fn


print('--- baseline (5.0 s of audio) median/min seconds')
print('log-mel (30s-padded)      ', T(mel_fn))
print('encoder (32 layers, 1500) ', T(enc_fn))
print('transcribe no word-ts     ', T(tr(False, False)))
print('transcribe word-ts (no reuse)', T(tr(True, False)))
print('transcribe word-ts + reuse (app)', T(tr(True, True)))
f0 = enc_fn()
set_fused(model, True)
print('--- encoder with mx.fast.scaled_dot_product_attention')
print('encoder fused             ', T(enc_fn))
f1 = enc_fn()
d = mx.abs(f1.astype(mx.float32) - f0.astype(mx.float32))
print('max|diff| %.4f  mean|diff| %.5f  mean|f0| %.4f' % (
    mx.max(d).item(), mx.mean(d).item(), mx.mean(mx.abs(f0.astype(mx.float32))).item()))
print('transcribe word-ts + reuse + fused', T(tr(True, True)))
set_fused(model, False)
