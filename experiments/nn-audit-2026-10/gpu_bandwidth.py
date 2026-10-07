"""Measured GPU read bandwidth -> decode ceiling for a 4-bit / 5-bit 4B model (decode reads all weights per token)."""
import statistics as st
import time

import mlx.core as mx

n = 512 * 1024 * 1024 // 2   # 512 Mi fp16 elements = 1 GiB
a = mx.random.normal((n,)).astype(mx.float16)
mx.eval(a)


def f():
    mx.eval(mx.sum(a.astype(mx.float32)))


def g():
    mx.eval(mx.max(a))


best = 0.
for name, fn in (('sum', f), ('max', g)):
    for _ in range(5):
        fn()
    ts = []
    for _ in range(25):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    gbs = a.nbytes / min(ts) / 1e9
    gm = a.nbytes / st.median(ts) / 1e9
    print(f'{name}: best {gbs:6.1f} GB/s  median {gm:6.1f} GB/s')
    best = max(best, gbs)
for label, gb in (('4-bit (2.22 GB)', 2.22), ('5-bit (2.70 GB)', 2.70)):
    print(f'  decode ceiling {label}: {best / gb:5.1f} tok/s at best-case bandwidth')
