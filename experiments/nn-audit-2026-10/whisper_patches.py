"""Experimental Whisper encoder patches shared by the ASR benchmarks.

``set_fused`` swaps the encoder self-attention for ``mx.fast.scaled_dot_product_attention``.
``context`` truncates the encoder input/positional embedding to ``n`` audio-context
positions (``n=1500`` is the stock 30-second window; ``None`` restores upstream).
Both are measurement aids, not production code.
"""
import types

import mlx.core as mx
import mlx.nn as nn
from mlx_whisper import whisper as W

_ORIGINAL_ATTN = {}
_ORIGINAL_CALL = W.AudioEncoder.__call__
CTX = {'n': None}


def _fused(self, q, k, v, mask=None):
    b, n, s = q.shape
    h = self.n_head
    qh = q.reshape(b, n, h, -1).transpose(0, 2, 1, 3)
    kh = k.reshape(b, k.shape[1], h, -1).transpose(0, 2, 1, 3)
    vh = v.reshape(b, v.shape[1], h, -1).transpose(0, 2, 1, 3)
    o = mx.fast.scaled_dot_product_attention(qh, kh, vh, scale=(s // h) ** -0.5,
                                             mask=None if mask is None else mask[:n, :n])
    return o.transpose(0, 2, 1, 3).reshape(b, n, s), None


def set_fused(model, on):
    for blk in model.encoder.blocks:
        key = id(blk.attn)
        if key not in _ORIGINAL_ATTN:
            _ORIGINAL_ATTN[key] = blk.attn.qkv_attention
        blk.attn.qkv_attention = types.MethodType(_fused, blk.attn) if on else _ORIGINAL_ATTN[key]


def _call(self, x):
    n = CTX['n']
    if n is None:
        return _ORIGINAL_CALL(self, x)
    x = x[:, :2 * n, :]
    x = nn.gelu(self.conv1(x))
    x = nn.gelu(self.conv2(x))
    x = x + self._positional_embedding[:n]
    for b in self.blocks:
        x, _, _ = b(x)
    return self.ln_post(x)


def install_context_patch():
    W.AudioEncoder.__call__ = _call


def context(n):
    CTX['n'] = n
