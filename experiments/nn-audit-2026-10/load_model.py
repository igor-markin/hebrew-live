"""GPU-load model of the default live schedule (first snapshot 1.5 s, then every 1.0 s) for continuous speech.

Worst case: every snapshot is re-decoded and re-translated.  Costs come from
``asr_cost_vs_length.py`` (quiet windows) and ``mt_cost_vs_length.py`` (he->en fit a + b*words).
A load factor above 1 means the serial GPU worker falls behind; in the app the queue then
collapses to the newest snapshot and visible latency grows instead.
"""
import numpy as np

L = np.array([1.5, 2.5, 3.5, 5, 7.5, 10, 15, 20])
A = np.array([.466, .477, .513, .534, .616, .694, .788, .937])
asr = lambda l: float(np.interp(l, L, A))
A0, B0 = 0.23, 0.056   # he-en MT total seconds = A0 + B0 * words (measured, shipped path)


def sim(D, wps=2.5, interval=1.0, asr_scale=1.0, mt_minus=0.0, cap=20.0, mt_scale=1.0, first=1.5):
    t = first
    a = m = 0.
    n = 0
    while t <= D + 1e-9:
        l = min(t, cap)
        a += asr(l) * asr_scale
        m += max(A0 + B0 * wps * l - mt_minus, 0.05) * mt_scale
        n += 1
        t += interval
    return n, a, m


def row(name, D=12, **k):
    n, a, m = sim(D, **k)
    print(f'  {name:62s} snaps {n:2d}  ASR {a:4.1f}s MT {m:4.1f}s  load {(a + m) / D:4.2f}')


print('12 s continuous speech, 2.5 words/s, he->en; offered GPU load (>1 = cannot keep up)')
row('as shipped')
row('MT: bypass stream_generate wrapper (-0.35 s/call, identical tokens)', mt_minus=0.35)
row('ASR: 15 s encoder-context floor + fused attn + no word-ts (x0.5)', asr_scale=0.5)
row('both of the above', mt_minus=0.35, asr_scale=0.5)
row('both + snapshot interval 1.5 s (instead of 1.0 s)', mt_minus=0.35, asr_scale=0.5, interval=1.5)
row('MT 5-bit (decode ~+18% time) on top of "both"', mt_minus=0.35, asr_scale=0.5, mt_scale=1.18)
row('MT 1.5x faster (self-speculative draft, paper) on top of "both"', mt_minus=0.35, asr_scale=0.5, mt_scale=1 / 1.5)
print('\n20 s continuous speech:')
row('as shipped', D=20)
row('both (wrapper bypass + encoder floor/fused/no-wts)', D=20, mt_minus=0.35, asr_scale=0.55)
