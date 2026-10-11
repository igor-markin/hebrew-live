"""MT token loop that matches `mlx_lm.stream_generate` output without its per-call cost.

`stream_generate` wraps every call in `wired_limit` (set limit, synchronize, restore), which
costs 0.33-0.46 s per translation on the reference Mac, and it builds a fresh streaming
detokenizer (about 0.1 s) every time. This loop drives `generate_step` directly, keeps one
detokenizer per tokenizer and reproduces the stock text segmentation and finish reasons exactly.
`HEBREW_LIVE_MT_GENERATE=stock` restores the library path;
`HEBREW_LIVE_MT_MAX_TOKENS=<n>` restores a fixed token limit.
"""
import os
import time

MIN_TOKENS = 96
MAX_TOKENS = 512
TOKENS_PER_SOURCE_TOKEN = 4
TOKEN_MARGIN = 32


def max_tokens_for(source_tokens):
    """Token budget that grows with the source; 256 truncated long Burmese/Khmer/Lao output."""
    override = os.environ.get('HEBREW_LIVE_MT_MAX_TOKENS', '')
    if override.isdigit() and int(override) > 0:
        return int(override)
    return min(MAX_TOKENS, max(MIN_TOKENS, TOKENS_PER_SOURCE_TOKEN * source_tokens + TOKEN_MARGIN))


def mode():
    return 'stock' if os.environ.get('HEBREW_LIVE_MT_GENERATE', 'fast') == 'stock' else 'fast'


def _stock(model, tokenizer, ids, max_tokens, sampler, stats):
    from mlx_lm import stream_generate
    began = time.perf_counter()
    for result in stream_generate(model, tokenizer, prompt=ids, max_tokens=max_tokens, sampler=sampler):
        if stats is not None:
            stats['tokens'] = result.generation_tokens
            stats.setdefault('first_token_seconds', time.perf_counter() - began)
        yield result.text, result.finish_reason


def _has(tokenizer, name):
    """Attribute check that does not evaluate it: the real `detokenizer` property builds an object."""
    return hasattr(type(tokenizer), name) or name in vars(tokenizer)


def _borrow_detokenizer(tokenizer):
    """A streaming detokenizer owned by one generation, reused between generations.

    Building the library's detokenizer walks the whole vocabulary (about 0.1 s for Gemma);
    `reset()` is free. A generation that starts while another is still open builds its own.
    """
    pool = vars(tokenizer).setdefault('_hebrew_live_detokenizers', [])
    detokenizer = pool.pop() if pool else tokenizer.detokenizer
    detokenizer.reset()
    return detokenizer, pool


def _fast(model, tokenizer, ids, max_tokens, sampler, step, stats):
    import mlx.core as mx
    from mlx_lm.generate import generate_step
    if not (_has(tokenizer, 'detokenizer') and _has(tokenizer, 'eos_token_ids')):
        from mlx_lm.tokenizer_utils import TokenizerWrapper
        tokenizer = TokenizerWrapper(tokenizer)
    detokenizer, pool = _borrow_detokenizer(tokenizer)
    eos = tokenizer.eos_token_ids
    token = None
    began = time.perf_counter()
    try:
        for n, (token, _) in enumerate((step or generate_step)(mx.array(ids), model, max_tokens=max_tokens, sampler=sampler)):
            if stats is not None:
                stats['tokens'] = n + 1
                stats.setdefault('first_token_seconds', time.perf_counter() - began)
            if token in eos:
                break
            detokenizer.add_token(token)
            if n + 1 == max_tokens:
                break
            yield detokenizer.last_segment, None
        detokenizer.finalize()
        yield detokenizer.last_segment, 'stop' if token in eos else 'length'
    finally:
        if not pool:
            pool.append(detokenizer)


def generate(model, tokenizer, ids, *, max_tokens, sampler, step=None, stats=None):
    """Yield `(text_segment, finish_reason)` exactly like `stream_generate`.

    `stats`, when given, receives `tokens` (generated so far, including the final stop
    token) and `first_token_seconds` (prefill plus the first decode step).
    """
    if mode() == 'stock':
        return _stock(model, tokenizer, ids, max_tokens, sampler, stats)
    return _fast(model, tokenizer, ids, max_tokens, sampler, step, stats)
