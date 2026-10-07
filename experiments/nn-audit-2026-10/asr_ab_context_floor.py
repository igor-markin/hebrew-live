"""Speed of a truncated encoder (context floor 15 s / 20 s) vs the shipped path; idle-gated, randomised arms.

A shipped (1500 ctx, word timestamps, reuse)  B fused attention  C floor 750 (no word-ts)
D floor 750 + fused (no word-ts)  E floor 1000 + fused (no word-ts).  Audio windows are <= 10 s,
so a fixed floor never cuts speech here; the production rule must be
n = clamp(ceil((len_s + 1.5) * 50), 750, 1500).
"""
import os
import random
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
from whisper_patches import CTX, context, install_context_patch, set_fused

P = str(ROOT / 'models' / 'asr')
model = ModelHolder.get_model(P, mx.float16)
install_context_patch()
audio = corpus.concat(corpus.load(), 0.3)
LENS = (1.5, 5, 10)


def asr(L, wts):
    a = audio[:int(L * 16000)]
    t = time.perf_counter()
    with reuse_alignment(wts and CTX['n'] is None):
        mlx_whisper.transcribe(a, path_or_hf_repo=P, language='he', task='transcribe', temperature=0.0,
                               word_timestamps=wts, condition_on_previous_text=False, verbose=None)
    mx.synchronize()
    return time.perf_counter() - t


mel = log_mel_spectrogram(audio[:5 * 16000], n_mels=128, padding=N_SAMPLES)
seg = pad_or_trim(mel[:N_FRAMES], N_FRAMES, axis=-2).astype(mx.float16)[None]


def enc(n):
    context(n)
    t = time.perf_counter()
    f = model.encoder(seg)
    mx.eval(f)
    d = time.perf_counter() - t
    context(None)
    return d


ARMS = {'A shipped': (0, None, True), 'B fused': (1, None, True), 'C floor750': (0, 750, False),
        'D floor750+fused': (1, 750, False), 'E floor1000+fused': (1, 1000, False)}
for k, (f, n, w) in ARMS.items():
    set_fused(model, bool(f))
    context(n)
    [asr(5, w) for _ in range(2)]
    context(None)


def one_round():
    r = {}
    names = list(ARMS)
    random.shuffle(names)
    for nm in names:
        f, n, w = ARMS[nm]
        set_fused(model, bool(f))
        context(n)
        for L in LENS:
            r[(nm, L)] = asr(L, w)
        context(None)
    for f in (0, 1):
        set_fused(model, bool(f))
        for n in (None, 1000, 750):
            r[('enc', f, n)] = enc(n)
    set_fused(model, False)
    return r


acc, tried = run_gated(one_round, want=8, budget=400)
print(f'accepted rounds {len(acc)}/{tried}')
g = lambda k: [a[k] for a in acc]
if acc:
    print('encoder only, seconds  min/median')
    for f in (0, 1):
        for n in (None, 1000, 750):
            print(f'  fused={f} ctx={n or 1500}: {min(g(("enc", f, n))):.3f} / {st.median(g(("enc", f, n))):.3f}')
    print('whole ASR call, seconds  min/median')
    for L in LENS:
        print(f'  audio {L} s: ' + ' | '.join(f'{nm}: {min(g((nm, L))):.3f}/{st.median(g((nm, L))):.3f}' for nm in ARMS))
