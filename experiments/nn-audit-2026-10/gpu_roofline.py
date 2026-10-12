"""Peak fp16 matmul TFLOPS on this GPU vs Whisper encoder FLOPs, and manual vs fused attention per layer."""
import statistics as st
import time

import mlx.core as mx


def tf(m, k, n, iters=30):
    a = mx.random.normal((m, k)).astype(mx.float16)
    b = mx.random.normal((k, n)).astype(mx.float16)
    mx.eval(a, b)
    for _ in range(5):
        mx.eval(a @ b)
    ts = []
    for _ in range(iters):
        t = time.perf_counter()
        mx.eval(a @ b)
        ts.append(time.perf_counter() - t)
    return 2 * m * k * n / min(ts) / 1e12, 2 * m * k * n / st.median(ts) / 1e12


print('fp16 matmul TFLOPS (best / median)')
for shp in [(4096, 4096, 4096), (8192, 8192, 8192), (1500, 1280, 5120), (1500, 5120, 1280), (1500, 1280, 1280)]:
    b, m = tf(*shp)
    print(f'  {shp}: {b:6.2f} / {m:6.2f}')
q = mx.random.normal((1, 20, 1500, 64)).astype(mx.float16)
k = mx.random.normal((1, 20, 1500, 64)).astype(mx.float16)
v = mx.random.normal((1, 20, 1500, 64)).astype(mx.float16)
mx.eval(q, k, v)


def manual():
    s = (q * 0.35) @ (k * 0.35).transpose(0, 1, 3, 2)
    w = mx.softmax(s, axis=-1, precise=True)
    return w @ v


def fused():
    return mx.fast.scaled_dot_product_attention(q, k, v, scale=0.125)


for name, fn in (('manual softmax attention', manual), ('fused SDPA', fused)):
    for _ in range(5):
        mx.eval(fn())
    ts = []
    for _ in range(20):
        t = time.perf_counter()
        mx.eval(fn())
        ts.append(time.perf_counter() - t)
    print(f'attention 1500x20x64, {name}: best {min(ts) * 1e3:.2f} ms  median {st.median(ts) * 1e3:.2f} ms'
          f'   (x32 layers = {32 * min(ts):.3f} s best)')
macs_layer = 4 * 1500 * 1280 ** 2 + 2 * 1500 * 1500 * 1280 + 2 * 1500 * 1280 * 5120
macs = 32 * macs_layer + 3000 * 128 * 1280 * 3 + 1500 * 1280 * 1280 * 3
print(f'encoder: {macs / 1e9:.0f} GMAC = {2 * macs / 1e12:.2f} TFLOP per 30 s window; '
      f'at X TFLOPS the floor is {2 * macs / 1e12:.2f}/X s')
