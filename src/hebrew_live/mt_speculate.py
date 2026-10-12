"""Greedy decoding drafted from the previous translation of the same growing phrase.

A refresh translates the same speech again with a few more words, so most of the new
translation equals the previous one. The previous translation's tokens are proposed as a
draft, the model scores `[last token, *draft]` in one forward pass, the longest prefix that
agrees with the model's own greedy choice is kept, and the KV cache is trimmed back over the
rejected tail. Every emitted token is the model's argmax, so the result equals plain greedy
decoding except where fp16/bf16 batch kernels flip a near-tie (measured, see the plan).

Measured on the reference Mac: 0.81x time on live-sized he-ru phrases, but only 32 of 43
translations were text-identical to plain greedy (bf16 batch kernels flip near-ties, mostly a
trailing full stop or a synonym), so it is OFF by default and not an "identical output"
change: enable it with `HEBREW_LIVE_MT_SPECULATE=1`. `HEBREW_LIVE_MT_SPECULATE_TOLERANCE=<nats>`
additionally accepts a drafted token whose log-probability is within that margin of the best
one (prefix-stable translations, more accepted tokens). Drop-in `step` for `mt_generate.generate`.
"""
import os

MAX_DRAFT = 24
MIN_DRAFT = 4
RESYNC_NGRAM = 2
PREFILL_STEP = 2048


def enabled():
    return os.environ.get('HEBREW_LIVE_MT_SPECULATE', '0') == '1'


def tolerance():
    try:
        return max(0., float(os.environ.get('HEBREW_LIVE_MT_SPECULATE_TOLERANCE', '0')))
    except ValueError:
        return 0.


class Drafter:
    """Tracks where the generated text is inside the previous translation's tokens."""

    def __init__(self, draft):
        self.draft = list(draft)
        self.generated = []
        self.pos = 0 if self.draft else None

    def emit(self, token):
        self.generated.append(token)
        if self.pos is not None and self.pos < len(self.draft) and self.draft[self.pos] == token:
            self.pos += 1
            return
        self.pos = self._resync()

    def _resync(self):
        size = RESYNC_NGRAM
        if len(self.generated) < size:
            return None
        tail = self.generated[-size:]
        for start in range(len(self.draft) - size + 1):
            if self.draft[start:start + size] == tail:
                return start + size
        return None

    def propose(self, limit):
        if self.pos is None:
            return []
        return self.draft[self.pos:self.pos + limit]


def _greedy(logits):
    """Same argmax-of-logprobs the stock `make_sampler(temp=0)` path computes."""
    import mlx.core as mx
    return mx.argmax(logits - mx.logsumexp(logits, axis=-1, keepdims=True), axis=-1)


def _accepted(logits, tentative, margin):
    """(number of drafted tokens accepted, the model's own token after them)."""
    import mlx.core as mx
    logprobs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
    best = mx.argmax(logprobs, axis=-1)
    if margin <= 0 or not tentative:
        mx.eval(best)
        choices = best.tolist()
        agree = 0
        while agree < len(tentative) and choices[agree] == tentative[agree]:
            agree += 1
        return agree, choices[agree]
    rows = mx.arange(len(tentative))
    drafted = logprobs[rows, mx.array(tentative)]
    close = drafted >= mx.max(logprobs[:len(tentative)], axis=-1) - margin
    mx.eval(best, close)
    flags, choices = close.tolist(), best.tolist()
    agree = 0
    while agree < len(tentative) and flags[agree]:
        agree += 1
    return agree, choices[agree]


def _room(cache):
    """Tokens that can still be appended before a sliding-window layer would drop old keys.

    A rotating cache that discards its oldest entries cannot be rolled back by `trim`, so a
    verification pass must fit inside the window."""
    sizes = [c.max_size for c in cache if getattr(c, 'max_size', None)]
    return min(sizes) - max(c.offset for c in cache) if sizes else PREFILL_STEP


def _run(prompt, model, draft, max_tokens, stats, margin=0.):
    import mlx.core as mx
    from mlx_lm.generate import generation_stream
    from mlx_lm.models import cache as kv
    cache = kv.make_prompt_cache(model)
    drafter = Drafter(draft)
    rounds = accepted_drafts = proposed = 0

    def forward(tokens):
        with mx.stream(generation_stream):
            return model(tokens[None], cache=cache)

    remaining = len(prompt) - 1
    while remaining > 0:
        count = min(PREFILL_STEP, remaining)
        with mx.stream(generation_stream):
            model(prompt[:count][None], cache=cache)
            mx.eval([c.state for c in cache])
        prompt = prompt[count:]
        remaining -= count
        mx.clear_cache()
    first = _greedy(forward(prompt)[:, -1, :])
    mx.eval(first)
    token = int(first.item())
    emitted = 1
    drafter.emit(token)
    last = token
    k = MAX_DRAFT // 2
    try:
        yield token, None
        while emitted < max_tokens:
            limit = min(k, _room(cache) - 1) if kv.can_trim_prompt_cache(cache) else 0
            tentative = drafter.propose(limit) if limit > 0 else []
            agree, bonus = _accepted(forward(mx.array([last] + tentative))[0], tentative, margin)
            accepted = tentative[:agree] + [bonus]
            if tentative:
                rounds += 1
                proposed += len(tentative)
                accepted_drafts += agree
                if agree < len(tentative):
                    kv.trim_prompt_cache(cache, len(tentative) - agree)
                k = min(MAX_DRAFT, k * 2) if agree == len(tentative) else max(MIN_DRAFT, agree + 2)
            for token in accepted:
                if emitted >= max_tokens:
                    return
                emitted += 1
                drafter.emit(token)
                last = token
                yield token, None
    finally:
        if stats is not None:
            stats.update(speculative_rounds=rounds, proposed=proposed, accepted_drafts=accepted_drafts)


def step_for(draft_ids, stats=None, margin=None):
    """A `generate_step` replacement bound to one previous translation."""
    margin = tolerance() if margin is None else margin
    def step(prompt, model, *, max_tokens, sampler=None, **ignored):
        return _run(prompt, model, draft_ids, max_tokens, stats, margin)
    return step
