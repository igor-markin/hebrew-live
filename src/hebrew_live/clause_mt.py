"""Translation of a growing Hebrew sentence that only ever adds to the shown translation.

The open sentence (every Hebrew word heard so far) is given to MiLMMT with the translation
already shown as a forced prefix, and the model continues it. Generation stops before it gets
ahead of the Hebrew (AlignAtt for a decoder-only model, Fuxa & Macháček 2026 / AlignAtt4LLM):
at the first target token whose attention, in MiLMMT's translation heads, points at a Hebrew
word the call may not cover yet. The words after `upto` are seen, so a clause is translated with
what follows it in view, but not translated.

Two more stops against invented words: a sentence end («.», «?») the Hebrew has not reached
(the words before it are kept, `end_mark` says which end the model wanted), and, when
`min_prob` is set, a token the model is unsure of.

Measured design: experiments/live-append/simulate.py --mode clause.
"""
import re

import numpy as np

# Translation heads of MiLMMT-46-4B from AlignAtt4LLM (data/alignatt_heads, MIT): the heads ranked
# high for cs-en, en-de, en-it and en-zh; there is no he-ru calibration, this is their union by rank.
HEADS = [(11, 2), (11, 3), (6, 4), (4, 2)]
SENTENCE_END = re.compile(r'[.?!…]')


class AttentionCapture:
    """Records, for every forward pass, the attention of the last query over all keys in the chosen
    (layer, head)s of the Gemma3 translator: mlx_lm 0.31's Gemma3 attention plus the record. While
    `active` is False the layers compute exactly what mlx_lm does."""

    def __init__(self, model, heads=HEADS):
        import mlx.core as mx
        from mlx_lm.models.base import scaled_dot_product_attention
        language = getattr(model, 'language_model', model)
        layers = language.model.layers
        self.model = model
        self.rows = []
        self.active = False
        by_layer = {}
        for layer, head in heads:
            by_layer.setdefault(layer, []).append(head)
        capture = self

        def patched(cls, layer, chosen):
            index = mx.array(chosen)

            def call(self, x, mask=None, cache=None):
                B, L, _ = x.shape
                queries, keys, values = self.q_proj(x), self.k_proj(x), self.v_proj(x)
                queries = queries.reshape(B, L, self.n_heads, -1).transpose(0, 2, 1, 3)
                keys = keys.reshape(B, L, self.n_kv_heads, -1).transpose(0, 2, 1, 3)
                values = values.reshape(B, L, self.n_kv_heads, -1).transpose(0, 2, 1, 3)
                queries = self.q_norm(queries)
                keys = self.k_norm(keys)
                if cache is not None:
                    queries = self.rope(queries, offset=cache.offset)
                    keys = self.rope(keys, offset=cache.offset)
                    keys, values = cache.update_and_fetch(keys, values)
                else:
                    queries = self.rope(queries)
                    keys = self.rope(keys)
                if capture.active:
                    q = queries[0, index, -1, :].astype(mx.float32)
                    k = keys[0, mx.array([h // self.repeats for h in chosen])].astype(mx.float32)
                    scores = (k @ q[:, :, None])[..., 0] * self.scale
                    capture.rows[-1][layer] = mx.softmax(scores, axis=-1)
                output = scaled_dot_product_attention(queries, keys, values, cache=cache, scale=self.scale, mask=mask)
                output = output.transpose(0, 2, 1, 3).reshape(B, L, -1)
                return self.o_proj(output)
            return type(cls.__name__ + 'Capture', (cls,), {'__call__': call})

        for layer, chosen in by_layer.items():
            attention = layers[layer].self_attn
            if not type(attention).__name__.endswith('Capture'):
                attention.__class__ = patched(type(attention), layer, chosen)

    def forward(self):
        self.rows.append({})

    def last(self):
        import mlx.core as mx
        rows = self.rows[-1]
        return mx.concatenate([rows[layer] for layer in sorted(rows)], axis=0)


def median_filter(rows, width):
    if width <= 1 or rows.shape[-1] < 2:
        return rows
    pad = width // 2
    padded = np.pad(rows, ((0, 0), (pad, pad)), mode='edge')
    windows = np.lib.stride_tricks.sliding_window_view(padded, width, axis=-1)
    return np.median(windows, axis=-1)


def runaway(forced, new, source):
    """How many of the `new` words to keep when the translation (`forced` + `new`) has run into
    a loop: three or more copies in a row of a phrase of 3-15 words, more copies than the Hebrew
    has of any phrase (a speaker who says a thing three times gets it three times). The new words
    are kept up to the end of the first copy; None when there is no loop. Hebrew the recognizer
    garbled (speech in another language) made the model repeat «без лишних слов» eleven times
    in one card until the length cap stopped it (Maccabi Dent call, 26.11)."""
    words = [re.sub(r'\W', '', word.lower()) for word in [*forced, *new]]
    first = None
    for size in range(3, min(15, len(words) // 3) + 1):
        for start in range(len(words) - 3 * size + 1):
            phrase = words[start:start + size]
            if any(phrase) and phrase == words[start + size:start + 2 * size] == words[start + 2 * size:start + 3 * size]:
                if first is None or start + size < first[0] + first[1]:
                    first = (start, size)
                break
    if first is None:
        return None
    start, size = first
    copies = 1
    while words[start + size * copies:start + size * (copies + 1)] == words[start:start + size]:
        copies += 1
    from .cli import repeat_run
    if copies <= repeat_run(source):
        return None
    return max(0, start + size - len(forced))


class Result:
    def __init__(self, words, stop, end_mark=None, tokens=0):
        self.words, self.stop, self.end_mark, self.tokens = words, stop, end_mark, tokens


class ClauseGenerator:
    """generate(text, forced, pairs, direction, upto=None, close=False) -> Result.

    `text`: the open sentence's Hebrew; `forced`: its translation shown so far; `pairs`: earlier
    (Hebrew, translation) sentences as context; `upto`: how many Hebrew words this call may cover
    (default: all but the last); `close`: the sentence is over, translate to the end, no stops;
    `max_new`: at most this many new words; `terms`: (Hebrew, translation) of the owner's words that
    occur in `text`, given as a list above the task.
    `Result.stop`: 'end' (the model finished), 'frontier' (attention reached a word it may not
    cover), 'sentence' (it wanted a sentence end the Hebrew has not reached), 'unsure', 'cap',
    'repetition' (the translation ran into a loop, see `runaway`: the words up to its first copy),
    'cancel'."""

    def __init__(self, engine, margin=1, width=7, min_mass=.03, min_prob=0., cancel=None):
        self.engine, self.margin, self.width, self.min_mass = engine, margin, width, min_mass
        self.min_prob, self.cancel = min_prob, cancel
        self.capture = None

    def _capture(self):
        model = self.engine.model
        if self.capture is None or self.capture.model is not model:
            self.capture = AttentionCapture(model)
        return self.capture

    def prompt(self, text, forced, pairs, direction, terms=()):
        from .languages import prompt_names
        source, target = prompt_names(direction)
        before = ' '.join(p[0] for p in pairs)
        done = ' '.join(p[1] for p in pairs if p[1])
        # The owner's words as a list above the task, not as sentences translated before this one:
        # given as «קופת חולים. → больничная касса.» before «עובדת בקופת חולים בבית הכרם» the
        # model took that Hebrew for done and dropped it (Maccabi call replay, 26.11).
        glossary = ('Use these translations of names and terms:\n' +
                    ''.join(f'{he} = {translation}\n' for he, translation in terms)) if terms else ''
        head = glossary + f'Translate this from {source} to {target}:\n{source}: ' + (before + ' ' if before else '')
        content = head + text + f'\n{target}:' + (' ' + done if done else '') + (' ' + forced if forced else '')
        encoded = self.engine.tokenizer._tokenizer(content, add_special_tokens=False, return_offsets_mapping=True)
        ids, offsets = encoded['input_ids'], encoded['offset_mapping']
        bounds, at = [], len(head)
        for word in text.split(' '):
            bounds.append((at, at + len(word)))
            at += len(word) + 1
        span = []   # (prompt position, Hebrew word index) of every token inside `text`
        for position, (start, end) in enumerate(offsets):
            middle = max(start, end - 1)
            if len(head) <= middle < len(head) + len(text):
                index = next((i for i, (a, b) in enumerate(bounds) if a <= middle < b + 1), len(bounds) - 1)
                span.append((position, index))
        return ids, span, len(bounds)

    def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None, terms=()):
        import mlx.core as mx
        from mlx_lm.models.cache import make_prompt_cache
        model, tokenizer = self.engine.model, self.engine.tokenizer
        capture = self._capture()
        ids, span, count = self.prompt(text, forced, pairs, direction, terms)
        positions = np.array([p for p, _ in span])
        upto = count - 1 if upto is None else upto
        accessible = sum(1 for _, i in span if i < upto)
        frontier = accessible + self.margin
        eos = set(tokenizer.eos_token_ids)
        limit = 3 * len(text.split()) + 3 - len(forced.split())
        if max_new is not None:
            limit = min(limit, max_new)
        token_limit = 6 * max(1, limit) + 24   # a «word» without spaces never reaches the word limit
        cache = make_prompt_cache(model)
        tokens, history, stop, end_mark, ended_once = [], [], None, None, False
        shown, checked = forced.split(), 0
        capture.active = not close and accessible < len(positions)
        capture.rows = []
        try:
            capture.forward()
            logits = model(mx.array(ids)[None], cache=cache)
            while True:
                if self.cancel is not None and self.cancel.is_set():
                    stop = 'cancel'
                    break
                token = int(mx.argmax(logits[0, -1]).item())
                if token in eos:
                    stop = 'end'
                    break
                if not close:
                    piece = tokenizer.decode([token])
                    if SENTENCE_END.search(piece) and not SENTENCE_END.search(text.strip()[-1:]):
                        if not tokens and not ended_once:
                            # Ended right after the shown words: let it, once, and go on.
                            ended_once = True
                        else:
                            return Result(tokenizer.decode(tokens).split(), 'sentence',
                                          SENTENCE_END.search(piece).group(), len(tokens))
                    elif self.min_prob > 0:
                        probability = float(mx.softmax(logits[0, -1].astype(mx.float32))[token].item())
                        if probability < self.min_prob:
                            return Result(self._whole_words(tokens, token), 'unsure', None, len(tokens))
                if capture.active and len(positions):
                    rows = np.array(capture.last())[:, positions]
                    history.append(rows)
                    per_head = median_filter(rows, self.width).argmax(-1)
                    aligned = int(np.sort(per_head)[(len(per_head) - 1) // 2])
                    mass = float(np.array(capture.last())[:, positions[accessible:]].sum(-1).mean())
                    if aligned >= frontier and mass >= self.min_mass:
                        return Result(self._whole_words(tokens, token), 'frontier', None, len(tokens))
                tokens.append(token)
                new = tokenizer.decode(tokens).split()
                if len(tokens) >= token_limit or len(new) > limit + 1:
                    stop = 'cap'
                    break
                if len(new) - 1 > checked:   # a word was finished: the last one may still grow
                    checked = len(new) - 1
                    keep = runaway(shown, new[:-1], text)
                    if keep is not None:
                        return Result(new[:keep], 'repetition', None, len(tokens))
                capture.forward()
                logits = model(mx.array([[token]]), cache=cache)
        finally:
            capture.active = False
            capture.rows = []
        words = tokenizer.decode(tokens).split()
        # Cut short (cap, cancel) the last word may be unfinished, also in the last call of a card.
        return Result(words if stop == 'end' else words[:-1], stop, None, len(tokens))

    def _whole_words(self, tokens, stop):
        """The words before the token generation stopped at; the last one only if `stop` starts a new word."""
        tokenizer = self.engine.tokenizer
        text_out = tokenizer.decode(tokens)
        words = text_out.split()
        if words and not tokenizer.decode(tokens + [stop]).startswith(text_out + ' ') and not text_out.endswith(' '):
            words = words[:-1]
        return words
