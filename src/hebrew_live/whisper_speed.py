"""Numerical speedup for the Whisper encoder (plan item 2.1), ON by default since 2026-10-12.

Encoder self-attention runs through `mx.fast.scaled_dot_product_attention` instead of the
explicit softmax. `HEBREW_LIVE_FUSED_ENCODER=0` restores the upstream implementation. It changes
the numbers slightly (FLEURS he, 792 clips: WER 19.15 -> 19.18 %, CI -0.03...+0.07 pp), so it
fails closed to the upstream implementation when the installed `mlx-whisper` is not the
qualified one (`whisper_reuse.compatible`: version and file hashes).

On 87 real speech windows it produced the byte-identical transcript 84 times (mean WER 0.55 %
against the stock transcript on the rest) and cut the call time by 16-19 % for windows up to
10 s. Truncating the encoder context (plan item 3.1) is deliberately NOT here: it changed the
transcript of 62-80 % of the same real windows even with a 25 s floor.
"""
import os
import types

from .whisper_reuse import compatible


def enabled():
    return os.environ.get('HEBREW_LIVE_FUSED_ENCODER') != '0'


def _fused_attention(self, q, k, v, mask=None):
    import mlx.core as mx
    batch, length, state = q.shape
    heads = self.n_head
    shape = lambda x: x.reshape(batch, x.shape[1], heads, -1).transpose(0, 2, 1, 3)
    out = mx.fast.scaled_dot_product_attention(shape(q), shape(k), shape(v), scale=(state // heads) ** -0.5,
                                               mask=None if mask is None else mask[:length, :length])
    return out.transpose(0, 2, 1, 3).reshape(batch, length, state), None


def prepare(model, event=None):
    """Patch the encoder blocks of a loaded model when enabled; returns what was applied."""
    applied = {'fused_encoder': False}
    if not enabled():
        return applied
    if not compatible():
        if event:
            event('whisper_speed_disabled', reason='unsupported library version or source')
        return applied
    for block in model.encoder.blocks:
        block.attn.qkv_attention = types.MethodType(_fused_attention, block.attn)
    applied['fused_encoder'] = True
    if event:
        event('whisper_speed', **applied)
    return applied
