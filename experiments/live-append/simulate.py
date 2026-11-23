"""Append-only live screen, simulated on a recording: Hebrew and translation are only ever added to.

Two ways to get Hebrew words that never change once shown:
  hybrid  the streaming zipformer (sherpa-onnx, CPU) writes words; it never rewrites them.
  agree   Whisper runs every --step seconds on the not yet committed audio; a word is shown when
          two passes in a row agree on it (LocalAgreement-2).
On zipformer words, two simultaneous translators that redo the open sentence after each burst and
only ever add to the shown translation (forced prefix):
  mt-agree  LocalAgreement on the translation: words the last --k continuations agree on.
  alignatt  AlignAtt for a decoder-only LLM: stop at the first token whose attention points at the
            last heard Hebrew word (MiLMMT translation heads from AlignAtt4LLM).
--translator DIR (hybrid) uses another MLX chat model (Gemma-4 E4B) as the chunk translator.
Shown words are translated in chunks that are only appended: each chunk is translated as the
continuation of the chunks before it (translation.prompt `pairs`), so a shown translation is
never redone. A chunk is sent when its first word was spoken --span seconds ago or a word ends
with punctuation (span 0: every time new words are shown).

Timing is a discrete-event simulation on the audio clock: model calls really run, one at a time,
and their measured time is placed on one GPU timeline (Whisper and the translator share it; the
zipformer runs on the CPU in parallel). Latency of a word = when it (or its translation) is shown
minus when it was spoken (end of the word in the audio: zipformer token time or Whisper word end).

    .venv/bin/python experiments/live-append/simulate.py A.wav --mode hybrid --span 0 \
        --zipformer DIR [--reference A.txt] [--text-dir OUT]

Prints one JSON line of numbers per recording; speech text goes only to --text-dir.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments' / 'corpus'))
from metrics import chrf, corpus_wer  # noqa: E402

RATE = 16000
MODELS = Path.home() / 'Library' / 'Application Support' / 'Hebrew Live CLI' / 'models'
END = re.compile(r'[.?!…]$')
PUNCT = re.compile(r'[.,?!…:;]$')
DIRECTION = 'he-ru'   # --direction
def new_words_cap(hebrew_words):
    """New translation words allowed when nothing heard follows (a pause, a quiet): a little more
    than the Hebrew needs, too few to finish the speaker's sentence for them."""
    return int(1.25 * hebrew_words) + 1


QUIET = 1.   # seconds without a newer word after which the last word may be translated
PAUSE_GATES = __import__('os').environ.get('SIM_PAUSE_GATES', '1') == '1'
DEBUG = bool(__import__('os').environ.get('SIM_DEBUG'))
NOISE = 0.            # --pause-noise: level of the 'silence' fed at a pause


class Log:
    def __init__(self):
        self.events = []

    def event(self, name, **data):
        self.events.append((name, data))

    def bind(self, *_):
        pass


def stats(values):
    values = sorted(values)
    if not values:
        return {}
    pick = lambda q: values[min(len(values) - 1, int(q * len(values)))]
    return dict(p50=round(pick(.5), 3), p95=round(pick(.95), 3), max=round(values[-1], 3),
                **{f'within_{k}s': round(sum(v <= k for v in values) / len(values), 3) for k in (2, 3, 4, 5)})


class Gpu:
    """One model call at a time, on the audio clock."""

    def __init__(self):
        self.free = 0.
        self.busy = 0.

    def run(self, ready, call):
        start = max(ready, self.free)
        began = time.perf_counter()
        result = call()
        seconds = time.perf_counter() - began
        self.free = start + seconds
        self.busy += seconds
        return result, self.free


class Translator:
    """--deadline D: a chunk waits for a clause end (or a pause) as long as its first word can still
    be translated and shown within D seconds of being spoken; then it is sent as it is. The time a
    call takes is estimated from the calls so far (a + b * words, b from the slowest recent calls)."""
    SAFETY = .3

    def __init__(self, engine, gpu, span, context, deadline=None):
        self.engine, self.gpu, self.span, self.context = engine, gpu, span, context
        self.deadline = deadline
        self.timings = []   # (words, seconds)
        self.pending, self.pairs, self.words = [], [], []
        self.chunks = self.capped = 0
        self.poisoned = False
        self.shown = []

    def offer(self, words, now, final=False):
        """Words newly shown at `now`; send a chunk when the rule says so."""
        self.pending.extend(words)
        while self.pending:
            first = self.pending[0]
            cut = next((i + 1 for i, w in enumerate(self.pending) if PUNCT.search(w['text'])), None)
            if cut is None:
                if not (final or self.due(first, now)):
                    return
                cut = len(self.pending)
            chunk, self.pending = self.pending[:cut], self.pending[cut:]
            self.send(chunk, now)

    def estimate(self, words):
        recent = self.timings[-20:]
        per_word = max([.12] + [(seconds - .25) / n for n, seconds in recent])
        return .25 + per_word * words

    def due(self, first, now):
        if self.deadline is None:
            return now - first['spoken'] >= self.span
        start = max(now, self.gpu.free)
        return start + self.estimate(len(self.pending)) + self.SAFETY >= first['spoken'] + self.deadline

    def send(self, chunk, ready):
        text = ' '.join(w['text'] for w in chunk)
        pairs = tuple(self.pairs[-self.context:]) if self.context else ()
        began = time.perf_counter()
        translation, shown = self.gpu.run(ready, lambda: self.generate(text, pairs))
        self.timings.append((len(chunk), time.perf_counter() - began))
        self.chunks += 1
        self.shown.append((text, translation))
        # A cut-off runaway stays on screen but is not given to the next chunks as their context.
        if not self.poisoned:
            self.pairs.append((text, translation))
        self.poisoned = False
        for w in chunk:
            w['translated'] = shown
        self.words.extend(chunk)

    def generate(self, text, pairs):
        """The chunk's continuation, stopped once it is three times longer than the chunk: past that
        the model is retelling the context, not translating the chunk."""
        out, words, chars = '', 3 * len(text.split()) + 3, 3 * len(text) + 20
        for piece, _ in self.engine.translate(text, context=pairs):
            out += piece
            if len(out.split()) > words or len(out) > chars:
                self.capped += 1
                self.poisoned = True
                break
        return out.strip()

    def text(self):
        return ' '.join(t for _, t in self.shown)


class ChatEngine:
    """Another instruction-tuned MLX model (Gemma-4 E4B) as the chunk translator, in place of MiLMMT:
    previous chunks are earlier turns of the chat, the chunk is the last user turn."""
    ASK = ('Translate the following Hebrew into Russian. The Hebrew is a piece of live speech that may stop '
           'mid-sentence: translate only what is there, add nothing. Reply with the Russian only.\n\n{text}')

    def __init__(self, path):
        from mlx_lm import load
        self.model, self.tokenizer = load(str(path))
        self.calls = []   # (wall clock, tokens, seconds)

    def warmup(self):
        # Whisper stays loaded as in the app (it writes the closing Hebrew), so memory is measured with it.
        import mlx_whisper
        mlx_whisper.transcribe(np.zeros(RATE, np.float32), path_or_hf_repo=str(MODELS / 'asr'), language='he',
                               temperature=0., verbose=None)
        list(self.translate('שלום'))
        self.calls = []

    def translate(self, text, context=()):
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler
        messages = []
        for source, target in context:
            messages += [dict(role='user', content=self.ASK.format(text=source)), dict(role='assistant', content=target)]
        messages.append(dict(role='user', content=self.ASK.format(text=text)))
        ids = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, enable_thinking=False)
        began, tokens = time.perf_counter(), 0
        for result in stream_generate(self.model, self.tokenizer, ids, max_tokens=4 * len(text.split()) + 32,
                                      sampler=make_sampler(temp=0)):
            tokens = result.generation_tokens
            yield result.text, result.finish_reason
        self.calls.append((round(time.time(), 1), tokens, round(time.perf_counter() - began, 3)))


INSTRUCTION = ('Translate only what is said. If the Hebrew breaks off in the middle of a sentence, stop '
               'the translation at the same point; do not complete or guess the rest.\n')


class AgreementTranslator:
    """LocalAgreement on the translation: the growing Hebrew of the open sentence is translated again
    after each new burst of words, always starting with the translation already shown (forced
    prefix), and only the words the last k continuations agree on are added. The sentence's last
    translation (at its end or a pause) adds the rest. Shown words are never changed.

    Latency of a Hebrew word: the time the translation reached the proportional position of that
    word in its sentence (target word ceil(T*(i+1)/S) of the final T words); a crude alignment."""

    def __init__(self, engine, gpu, k, instruct, context=2, ahead=6):
        self.engine, self.gpu, self.k, self.instruct, self.context = engine, gpu, k, instruct, context
        self.ahead = ahead
        self.sentence, self.history, self.shown = [], [], []   # shown: [(word, time)]
        self.pairs, self.words, self.done_text = [], [], []
        self.chunks = self.capped = self.skipped = 0

    def ids(self, text, forced):
        from hebrew_live.languages import prompt_names
        source, target = prompt_names(DIRECTION)
        pairs = self.pairs[-self.context:]
        before = ' '.join(p[0] for p in pairs)
        done = ' '.join(p[1] for p in pairs)
        content = f'Translate this from {source} to {target}:\n{source}: {(before + " " + text).strip()}\n{target}:'
        if done:
            content += ' ' + done
        if self.instruct:
            content = INSTRUCTION + content
        if forced:
            content += ' ' + forced
        return self.engine.tokenizer.encode(content, add_special_tokens=False)

    def generate(self, text, forced, new_words=None):
        """Words after the forced prefix; a growing sentence only needs the next `new_words` (one
        more is generated so the last one is complete)."""
        from mlx_lm.sample_utils import make_sampler
        from hebrew_live import mt_generate
        ids = self.ids(text, forced)
        out, limit = '', 3 * len(text.split()) + 3
        for piece, _ in mt_generate.generate(self.engine.model, self.engine.tokenizer, ids, max_tokens=160,
                                             sampler=make_sampler(temp=0)):
            out += piece
            if new_words is not None and len(out.split()) > new_words:
                return out.split()[:new_words]
            if len((forced + ' ' + out).split()) > limit:
                self.capped += 1
                break
        return out.split()

    def offer(self, words, now, final=False):
        for word in words:
            self.sentence.append(word)
            if END.search(word['text']):
                self.step(now, close=True)
        if words and self.sentence:
            self.step(now)
        if final and self.sentence:
            self.step(now, close=True)

    def step(self, now, close=False):
        if not close and self.gpu.free > now:
            self.skipped += 1   # still busy: the next burst translates the newer Hebrew
            return
        text = ' '.join(w['text'] for w in self.sentence)
        forced = ' '.join(w for w, _ in self.shown)
        continuation, end = self.gpu.run(now, lambda: self.generate(text, forced, None if close else self.ahead))
        self.chunks += 1
        if close:
            agreed = continuation
        else:
            self.history.append(continuation)
            if len(self.history) < self.k:
                return
            recent = self.history[-self.k:]
            agreed = []
            for i, word in enumerate(recent[-1]):
                if all(len(h) > i and h[i] == word for h in recent):
                    agreed.append(word)
                else:
                    break
            # the history now continues after the agreed words
            # an entry that was used up carries no vote for the next words
            self.history = [h[len(agreed):] for h in self.history[-self.k:]
                            if h[:len(agreed)] == agreed and len(h) > len(agreed)]
        self.shown.extend((w, end) for w in agreed)
        if close:
            total = max(1, len(self.shown))
            size = len(self.sentence)
            for i, word in enumerate(self.sentence):
                j = min(total, -(-total * (i + 1) // size)) - 1
                word['translated'] = self.shown[j][1] if self.shown else end
            self.words.extend(self.sentence)
            translation = ' '.join(w for w, _ in self.shown)
            self.pairs.append((text, translation))
            self.done_text.append((text, translation))
            self.sentence, self.history, self.shown = [], [], []

    @property
    def shown_pairs(self):
        return self.done_text

    def text(self):
        return ' '.join(t for _, t in self.done_text)


# Translation heads of MiLMMT-46-4B from AlignAtt4LLM (data/alignatt_heads, MIT): the heads ranked high
# for cs-en, en-de, en-it and en-zh; no he-ru calibration exists, so this is their union by rank.
MILMMT_HEADS = [(11, 2), (11, 3), (6, 4), (4, 2), (9, 3), (7, 7), (9, 7), (2, 7), (12, 1), (0, 1)]


class AttentionCapture:
    """Records, for every forward pass, the attention of the last query over all keys in the chosen
    (layer, head)s of the Gemma3 translator. A copy of mlx_lm's Gemma3 attention plus the record."""

    def __init__(self, model, heads):
        import mlx.core as mx
        from mlx_lm.models.base import scaled_dot_product_attention
        language = getattr(model, 'language_model', model)
        layers = language.model.layers
        self.rows = []      # per forward pass: {layer: array [heads, keys]}
        self.active = False
        by_layer = {}
        for layer, head in heads:
            by_layer.setdefault(layer, []).append(head)
        capture = self

        def patched(cls, layer, chosen):
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
                    q = queries[0, mx.array(chosen), -1, :].astype(mx.float32)              # [h, d]
                    k = keys[0, mx.array([h // self.repeats for h in chosen])].astype(mx.float32)  # [h, T, d]
                    scores = (k @ q[:, :, None])[..., 0] * self.scale
                    capture.rows[-1][layer] = mx.softmax(scores, axis=-1)
                output = scaled_dot_product_attention(queries, keys, values, cache=cache, scale=self.scale, mask=mask)
                output = output.transpose(0, 2, 1, 3).reshape(B, L, -1)
                return self.o_proj(output)
            return type(cls.__name__ + 'Capture', (cls,), {'__call__': call})

        for layer, chosen in by_layer.items():
            attention = layers[layer].self_attn
            attention.__class__ = patched(type(attention), layer, chosen)
        self.order = [(layer, i) for layer, chosen in by_layer.items() for i in range(len(chosen))]

    def forward(self):
        self.rows.append({})

    def last(self):
        """[heads, keys] for the last forward pass."""
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


class AlignAttTranslator(AgreementTranslator):
    """AlignAtt for a decoder-only translator (Fuxa & Macháček, IWSLT 2026; AlignAtt4LLM): the growing
    Hebrew of the open sentence is translated after each burst of words, continuing the translation
    already shown; generation stops at the first target token whose attention (median over the
    translation heads of the per-head argmax over raw attention, median filter 7; --zscore normalises
    each head over the tokens of this call as the repository does, which is noise for the 2-5 tokens of
    a burst)
    points at the last Hebrew word or later (it may still go on: border, b=1 word, + `margin` tokens)
    while at least 3% of the attention is there. The words before that token are shown; a word the
    token is in the middle of waits. One call per burst, no agreement between calls."""

    def __init__(self, engine, gpu, heads=4, margin=1, width=7, min_mass=.03, context=2, zscore=False,
                 min_prob=0., hold_end=False):
        super().__init__(engine, gpu, 1, False, context)
        self.zscore = zscore
        # Two more ways to wait, against invented words: a token the model is not sure of
        # (probability below `min_prob`), and a sentence end the Hebrew has not reached (`hold_end`).
        self.min_prob, self.hold_end = min_prob, hold_end
        self.capture = AttentionCapture(engine.model, MILMMT_HEADS[:heads])
        self.margin, self.width, self.min_mass = margin, width, min_mass
        self.stops = {'frontier': 0, 'end': 0, 'cap': 0, 'unsure': 0, 'sentence': 0}
        self.keep_before_end = False

    def prompt(self, text, forced):
        from hebrew_live.languages import prompt_names
        source, target = prompt_names(DIRECTION)
        pairs = self.pairs[-self.context:]
        before = ' '.join(p[0] for p in pairs)
        done = ' '.join(p[1] for p in pairs)
        head = f'Translate this from {source} to {target}:\n{source}: ' + (before + ' ' if before else '')
        content = head + text + f'\n{target}:' + (' ' + done if done else '') + (' ' + forced if forced else '')
        encoded = self.engine.tokenizer._tokenizer(content, add_special_tokens=False, return_offsets_mapping=True)
        ids, offsets = encoded['input_ids'], encoded['offset_mapping']
        # word index of every source token (tokens inside `text`)
        bounds, at = [], len(head)
        for word in text.split(' '):
            bounds.append((at, at + len(word)))
            at += len(word) + 1
        span = []
        for position, (start, end) in enumerate(offsets):
            middle = max(start, end - 1)
            if len(head) <= middle < len(head) + len(text):
                index = next((i for i, (a, b) in enumerate(bounds) if a <= middle < b + 1), len(bounds) - 1)
                span.append((position, index))
        return ids, span, len(bounds)

    def generate(self, text, forced, new_words=None, upto=None, commas=0):
        close = new_words is None
        began = time.perf_counter()
        try:
            return self._generate(text, forced, close, upto, commas)
        finally:
            self.generation = getattr(self, 'generation', [0, 0.])
            self.generation[1] += time.perf_counter() - began

    def _generate(self, text, forced, close, upto=None, commas=0):
        """`upto`: Hebrew words the translation may cover (default: all but the last); `commas`:
        stop after that many clause marks in the output (the Hebrew clauses it may cover)."""
        import mlx.core as mx
        from mlx_lm.models.cache import make_prompt_cache
        ids, span, count = self.prompt(text, forced)
        positions = np.array([p for p, _ in span])
        upto = count - 1 if upto is None else upto
        accessible = sum(1 for _, i in span if i < upto)
        self.last_stop = None
        marks, ended_once = 0, False
        frontier = accessible + self.margin
        model, tokenizer = self.engine.model, self.engine.tokenizer
        eos = set(tokenizer.eos_token_ids)
        cache = make_prompt_cache(model)
        limit = 3 * len(text.split()) + 3 - len(forced.split())
        if getattr(self, 'new_words_cap', None) is not None:
            limit = min(limit, self.new_words_cap)
        tokens, history = [], []
        self.capture.active = not close and accessible < len(positions)
        try:
            self.capture.forward()
            logits = model(mx.array(ids)[None], cache=cache)
            while True:
                token = int(mx.argmax(logits[0, -1]).item())
                self.generation = getattr(self, 'generation', [0, 0.])
                self.generation[0] += 1
                if token in eos:
                    self.stops['end'] += 1
                    self.last_stop = 'end'
                    break
                if not close:
                    reason = None
                    piece = tokenizer.decode([token])
                    if self.hold_end and re.search(r'[.?!…]', piece) and not END.search(text.strip()):
                        reason = 'sentence'
                        # Ended right after the shown words: the model closes a sentence the Hebrew
                        # goes on with; let it, once, and continue.
                        if self.keep_before_end and not tokens and not ended_once:
                            reason, ended_once = None, True
                    elif self.min_prob > 0:
                        probability = float(mx.softmax(logits[0, -1].astype(mx.float32))[token].item())
                        if probability < self.min_prob:
                            reason = 'unsure'
                    if reason:
                        self.stops[reason] += 1
                        self.last_stop = reason
                        self.end_mark = re.search(r'[.?!…]', piece).group() if reason == 'sentence' else None
                        if reason == 'sentence' and self.keep_before_end:
                            # The model would end the sentence here: the words before it are whole.
                            return tokenizer.decode(tokens).split()
                        return self.complete_words(tokenizer, tokens, token)
                if self.capture.active and len(positions):
                    rows = np.array(self.capture.last())[:, positions]          # [heads, source tokens]
                    history.append(rows)
                    stack = np.stack(history)                                     # [tokens, heads, source]
                    if self.zscore and len(stack) > 2:
                        rows = (rows - stack.mean(0)) / np.maximum(stack.std(0), 1e-6)
                    per_head = median_filter(rows, self.width).argmax(-1)
                    aligned = int(np.sort(per_head)[(len(per_head) - 1) // 2])
                    mass = float(np.array(self.capture.last())[:, positions[accessible:]].sum(-1).mean())
                    if aligned >= frontier and mass >= self.min_mass and accessible < len(positions):
                        self.stops['frontier'] += 1
                        self.last_stop = 'frontier'
                        return self.complete_words(tokenizer, tokens, token)
                tokens.append(token)
                if commas and not close and re.search(r'[,;:]', tokenizer.decode([token])):
                    marks += 1
                    if marks >= commas:
                        self.stops['comma'] = self.stops.get('comma', 0) + 1
                        self.last_stop = 'comma'
                        return tokenizer.decode(tokens).split()
                if len(tokenizer.decode(tokens).split()) > limit + 1:
                    self.capped += 1
                    self.stops['cap'] += 1
                    self.last_stop = 'cap'
                    break
                self.capture.forward()
                logits = model(mx.array([[token]]), cache=cache)
        finally:
            self.capture.active = False
            self.capture.rows = []
        words = tokenizer.decode(tokens).split()
        return words if close or self.last_stop == 'end' else words[:-1]   # the last word may still grow

    @staticmethod
    def complete_words(tokenizer, tokens, stop):
        """The words before the token generation stopped at; the last one only if `stop` starts a new word."""
        text_out = tokenizer.decode(tokens)
        words = text_out.split()
        if words and not tokenizer.decode(tokens + [stop]).startswith(text_out + ' ') and not text_out.endswith(' '):
            words = words[:-1]
        return words

    def step(self, now, close=False):
        if not close and self.gpu.free > now:
            self.skipped += 1
            return
        text = ' '.join(w['text'] for w in self.sentence)
        forced = ' '.join(w for w, _ in self.shown)
        added, end = self.gpu.run(now, lambda: self.generate(text, forced, None if close else 0))
        self.chunks += 1
        self.shown.extend((w, end) for w in added)
        if close:
            total = max(1, len(self.shown))
            size = len(self.sentence)
            for i, word in enumerate(self.sentence):
                j = min(total, -(-total * (i + 1) // size)) - 1
                word['translated'] = self.shown[j][1] if self.shown else end
            self.words.extend(self.sentence)
            translation = ' '.join(w for w, _ in self.shown)
            self.pairs.append((text, translation))
            self.done_text.append((text, translation))
            self.sentence, self.history, self.shown = [], [], []


CLAUSE_END = re.compile(r'[,;:]$')


class ClauseTranslator(AlignAttTranslator):
    """AlignAtt that waits for the clause: the open sentence is translated (continuing the shown
    translation) when a clause ends (comma, ;, :) up to that clause, or, if no clause end comes,
    when the first untranslated word would otherwise miss --deadline: then as plain AlignAtt
    (all but the last word). A sentence end or a pause translates the rest. A word counts as
    translated when a call that may cover it ends at its frontier."""
    SAFETY = .3

    def __init__(self, engine, gpu, deadline, heads=4, margin=1, hold_end=True, min_prob=0.):
        super().__init__(engine, gpu, heads, margin, hold_end=hold_end, min_prob=min_prob)
        self.deadline = deadline
        self.keep_before_end = True
        self.end_mark = None    # the sentence end the model wanted after the shown words
        self.covered = 0
        self.tried = None       # (words heard, upto) of a call that added nothing
        self.end_mark_after = None
        self.timings = []

    def estimate(self, words):
        per_word = max([.12] + [(seconds - .25) / max(1, n) for n, seconds in self.timings[-20:]])
        return .25 + per_word * words

    def offer(self, words, now, final=False):
        for word in words:
            self.sentence.append(word)
            if END.search(word['text']):
                self.close(now)
        if final and self.sentence:
            self.close(now, pause=True)
            return
        if not self.sentence or self.gpu.free > now:
            return
        uncovered = self.sentence[self.covered:]
        # a clause end with a word heard after it: the model sees where the clause leads
        clause = max((i for i, w in enumerate(uncovered[:-1]) if CLAUSE_END.search(w['text'])), default=None)
        if clause is not None:
            upto = self.covered + clause + 1
            commas = sum(1 for w in uncovered[:clause + 1] if CLAUSE_END.search(w['text']))
        elif uncovered and now + self.estimate(len(uncovered)) + self.SAFETY >= uncovered[0]['spoken'] + self.deadline:
            # all but the last word; the last one too once it is the one that is due
            # (no newer word for a second: the speaker went quiet without a detected pause)
            alone = len(uncovered) == 1 and now - uncovered[0]['shown'] >= QUIET
            upto, commas = len(self.sentence) - (not alone), 0
        else:
            return
        if upto <= self.covered or self.tried == (len(self.sentence), upto):
            return
        self.call(now, upto, commas)

    def split(self):
        """The model ended its sentence after the shown words while the Hebrew goes on (no
        sentence end heard): end the Russian sentence there and go on with the rest of the Hebrew
        as a new sentence, the finished pair as context. Keeps prompts short and aligned."""
        word, at = self.shown[-1]
        self.shown[-1] = (word + self.end_mark, at)
        he, ru = self.sentence[:self.covered], ' '.join(w for w, _ in self.shown)
        self.words.extend(he)
        self.pairs.append((' '.join(w['text'] for w in he), ru))
        self.done_text.append(self.pairs[-1])
        self.sentence, self.shown, self.covered, self.tried = self.sentence[self.covered:], [], 0, None

    def call(self, now, upto, commas):
        pending = self.end_mark_after
        if pending and self.shown and 0 < self.covered:
            self.end_mark = pending
            upto -= self.covered
            self.split()
        self.end_mark_after = None
        forced = ' '.join(w for w, _ in self.shown)
        began = time.perf_counter()
        # AlignAtt over all heard words; the words after `upto` are seen but not translated.
        text = ' '.join(w['text'] for w in self.sentence)
        if upto == len(self.sentence):   # nothing after: no attention stop, a cap on new words
            self.new_words_cap = new_words_cap(upto - self.covered)
        try:
            added, end = self.gpu.run(now, lambda: self.generate(text, forced, 0, upto, 0))
        finally:
            self.new_words_cap = None
        self.timings.append((upto - self.covered, time.perf_counter() - began))
        if DEBUG:
            print('CALL', round(now, 2), self.covered, upto, len(self.sentence), commas, self.last_stop, added, file=sys.stderr)
        self.chunks += 1
        self.shown.extend((w, end) for w in added)
        # 'end' with nothing added: the shown translation already says what was heard.
        if self.last_stop in ('sentence', 'end') or added and self.last_stop in ('frontier', 'comma'):
            for word in self.sentence[self.covered:upto]:
                word['translated'] = end
            self.covered = upto
            self.tried = None
            if self.last_stop == 'sentence' and self.shown:
                self.end_mark_after = self.end_mark
        else:
            self.tried = (len(self.sentence), upto)

    def close(self, now, pause=False):
        text = ' '.join(w['text'] for w in self.sentence)
        forced = ' '.join(w for w, _ in self.shown)
        if pause and PAUSE_GATES:
            # A pause is not a sentence end: the model must not finish the sentence for the
            # speaker. Gates on, and no more new words than the Hebrew left can need.
            self.new_words_cap = new_words_cap(len(self.sentence) - self.covered)
            try:
                added, end = self.gpu.run(now, lambda: self.generate(text, forced, 0, len(self.sentence), 0))
            finally:
                self.new_words_cap = None
        else:
            added, end = self.gpu.run(now, lambda: self.generate(text, forced, None))
        self.chunks += 1
        self.shown.extend((w, end) for w in added)
        for word in self.sentence[self.covered:]:
            word['translated'] = end
        self.words.extend(self.sentence)
        translation = ' '.join(w for w, _ in self.shown)
        self.pairs.append((text, translation))
        self.done_text.append((text, translation))
        self.sentence, self.history, self.shown = [], [], []
        self.covered, self.tried, self.end_mark_after = 0, None, None


def pauses(audio, piece, silence):
    """Per piece: True where `silence` seconds of quiet end after speech (an energy VAD standing in
    for the app's Silero VAD, which closes a fragment after a pause)."""
    step = int(piece * RATE)
    rms = np.array([np.sqrt(np.mean(audio[i:i + step] ** 2)) if len(audio[i:i + step]) else 0.
                    for i in range(0, len(audio), step)])
    loud = rms > max(1e-4, .1 * np.percentile(rms, 90))
    marks, quiet, spoke = [], 0, False
    for is_loud in loud:
        quiet = 0 if is_loud else quiet + 1
        spoke |= bool(is_loud)
        hit = spoke and quiet * piece >= silence - 1e-9
        if hit:
            spoke = False
        marks.append(hit)
    return marks


def hybrid(audio, folder, translator, piece=.1, tail=1., silence=None, pause_tail=.8):
    import sherpa_onnx
    folder = Path(folder) / 'sherpa-onnx'
    recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(folder / 'tokens.txt'), encoder=str(folder / 'encoder.int8.onnx'),
        decoder=str(folder / 'decoder.int8.onnx'), joiner=str(folder / 'joiner.int8.onnx'),
        model_type='zipformer2', num_threads=1, decoding_method='greedy_search')
    stream = recognizer.create_stream()
    samples = np.concatenate([audio, np.zeros(int(tail * RATE), np.float32)])
    step = int(piece * RATE)
    marks = pauses(samples, piece, silence) if silence else []
    inserted = []   # (stream seconds where zeros were fed, seconds fed) at pauses, as the app does
    def audio_time(stamp):
        return stamp - sum(length for at, length in inserted if at <= stamp)
    fed = flush_until = 0.
    seen, words, current, idle = 0, [], None, 0
    for index, start in enumerate(range(0, len(samples), step)):
        chunk = samples[start:start + step]
        stream.accept_waveform(RATE, chunk)
        fed += len(chunk) / RATE
        pause = index < len(marks) and marks[index]
        if pause:
            flush_until = fed + 2.
            if pause_tail:
                inserted.append((fed, pause_tail))
                noise = np.random.default_rng(0).normal(0, NOISE, int(pause_tail * RATE)).astype(np.float32)
                stream.accept_waveform(RATE, noise)
                fed += pause_tail
        began = time.perf_counter()
        decoded = False
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
            decoded = True
        result = recognizer.get_result_all(stream)
        now = (start + step) / RATE + time.perf_counter() - began
        done = []
        fresh = len(result.tokens) > seen
        for token, stamp in zip(result.tokens[seen:], result.timestamps[seen:]):
            starts = token.startswith((' ', '▁'))
            if starts and current is not None:
                done.append(current)
                current = None
            if current is None:
                current = dict(text='', shown=now)
            current['text'] += token.replace('▁', ' ').strip()
            current['spoken'] = min(audio_time(float(stamp)) + .04, len(audio) / RATE)
        seen = len(result.tokens)
        # Nothing new for a while: the last word is finished (the speaker paused).
        # A word goes on in the next token unless it starts with a space, so it is finished when the
        # next word starts, or when two decoded chunks in a row brought nothing (a pause).
        idle = 0 if fresh else idle + decoded
        # After a pause the words still coming out are the last ones before it: nothing follows them.
        if current is not None and (idle >= 2 or pause or fresh and fed <= flush_until):
            done.append(current)
            current = None
        for w in done:
            w['shown'] = now  # a word is complete when the next one starts
        words.extend(done)
        translator.offer(done, now, final=pause)
    if current is not None:
        current['shown'] = len(samples) / RATE
        words.append(current)
        translator.offer([current], current['shown'], final=True)
    translator.offer([], len(samples) / RATE, final=True)
    return words


def agree(audio, engine, gpu, translator, step=.5, trim=8.):
    """LocalAgreement-2 over Whisper passes on the uncommitted audio."""
    words, previous, base, t = [], [], 0, step
    norm = lambda w: w.strip().strip('.,?!…"\'').strip()
    total = len(audio) / RATE

    def decode(until):
        clip = audio[base:int(until * RATE)]
        text = engine.recognize(clip, 0., preliminary=False, mode='phrases', align_words=True)
        found = getattr(engine, 'recognition_words', None) or []
        return [dict(text=w['word'].strip(), start=base / RATE + w['start'], end=base / RATE + w['end'])
                for w in found if w['word'].strip()] if text else []

    while True:
        final = t >= total
        until = min(t, total)
        hypothesis, done = gpu.run(until, lambda: decode(until))
        if final:
            new = hypothesis
        else:
            agreed = 0
            while (agreed < len(previous) and agreed < len(hypothesis)
                   and norm(previous[agreed]['text']) == norm(hypothesis[agreed]['text'])):
                agreed += 1
            new = hypothesis[:agreed]
        committed = [dict(text=w['text'], spoken=w['end'], shown=done) for w in new]
        words.extend(committed)
        translator.offer(committed, done, final=final)
        if final:
            break
        if new:
            base = int(new[-1]['end'] * RATE)  # the next pass starts after the committed words
            previous = hypothesis[len(new):]
        else:
            previous = hypothesis
            if until - base / RATE > trim and hypothesis:
                base = int(hypothesis[0]['start'] * RATE)
        # the next pass starts when the GPU is free again, but not before new audio arrived
        t = max(t + step, gpu.free)
    return words


def whole(engine, text, context):
    """Sentence by sentence, each as one piece, with the previous sentences as context."""
    sentences = [s.strip() for s in re.findall(r'[^.?!…]+[.?!…]*', text) if s.strip()] or [text]
    pairs = []
    for sentence in sentences:
        out = ''.join(p for p, _ in engine.translate(sentence, context=tuple(pairs[-context:]))).strip()
        pairs.append((sentence, out))
    whole.pairs = pairs
    return ' '.join(t for _, t in pairs)


def doubtful(pairs):
    """Figures and weekdays one side of a (Hebrew, Russian) pair has and the other cannot account for;
    a wrong weekday that weekday_guard fixes in the app counts as fixed, not doubtful."""
    from hebrew_live.number_guard import check
    from hebrew_live.weekday_guard import fix
    found = dict(numbers=0, days=0, days_fixed=0)
    for he, ru in pairs:
        fixed, days = fix(he, ru) if DIRECTION == 'he-ru' else (ru, [])
        found['numbers'] += len(check(he, fixed, 'he', DIRECTION.split('-')[1]))
        found['days'] += sum(1 for item in days if item.kind != 'fixed')
        found['days_fixed'] += sum(1 for item in days if item.kind == 'fixed')
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('wavs', nargs='+', type=Path)
    parser.add_argument('--mode', choices=['hybrid', 'agree', 'mt-agree', 'alignatt', 'clause'], required=True)
    parser.add_argument('--k', type=int, default=2, help='mt-agree: continuations that must agree')
    parser.add_argument('--no-instruction', action='store_true', help='mt-agree: plain prompt')
    parser.add_argument('--span', type=float, default=0., help='seconds of speech before a chunk is sent')
    parser.add_argument('--step', type=float, default=.5, help='agree: seconds between Whisper passes')
    parser.add_argument('--context', type=int, default=4, help='previous chunks given as pairs')
    parser.add_argument('--heads', type=int, default=4, help='alignatt: translation heads used')
    parser.add_argument('--min-prob', type=float, default=0., help='alignatt: wait at a token below this probability')
    parser.add_argument('--hold-end', action='store_true', help='alignatt: wait at a sentence end the Hebrew has not reached')
    parser.add_argument('--zscore', action='store_true', help='alignatt: z-score attention over the call')
    parser.add_argument('--margin', type=int, default=1, help='alignatt: border margin in source tokens')
    parser.add_argument('--translator', type=Path, help='hybrid: an MLX chat model folder instead of MiLMMT')
    parser.add_argument('--direction', default='he-ru', choices=['he-ru', 'he-en'])
    parser.add_argument('--deadline', type=float, help='hybrid: wait for a clause end, but show within this many seconds')
    parser.add_argument('--pause', type=float, help='hybrid: seconds of quiet that end a fragment (feeds 0.8 s of zeros)')
    parser.add_argument('--pause-tail', type=float, default=.8, help='hybrid: seconds of zeros fed at a pause')
    parser.add_argument('--pause-noise', type=float, default=0.)
    parser.add_argument('--zipformer', type=Path)
    parser.add_argument('--text-dir', type=Path)
    args = parser.parse_args()
    global DIRECTION, NOISE
    DIRECTION, NOISE = args.direction, args.pause_noise
    from hebrew_live.cli import Engine
    if args.translator:
        engine = ChatEngine(args.translator)
    else:
        engine = Engine(MODELS, Log())
        engine.language, engine.direction, engine.topic = 'he', args.direction, 'none'
    engine.warmup()
    for wav in args.wavs:
        audio, rate = soundfile.read(wav, dtype='float32')
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if rate != RATE:
            import soxr
            audio = soxr.resample(audio, rate, RATE).astype(np.float32)
        gpu = Gpu()
        if args.mode == 'clause':
            translator = ClauseTranslator(engine, gpu, args.deadline or 4., args.heads, args.margin,
                                          hold_end=args.hold_end, min_prob=args.min_prob)
        elif args.mode == 'alignatt':
            translator = AlignAttTranslator(engine, gpu, args.heads, args.margin, zscore=args.zscore,
                                            min_prob=args.min_prob, hold_end=args.hold_end)
        elif args.mode == 'mt-agree':
            translator = AgreementTranslator(engine, gpu, args.k, not args.no_instruction)
        else:
            translator = Translator(engine, gpu, args.span, args.context, args.deadline)
        began = time.perf_counter()
        logged = len(engine.log.events) if hasattr(engine, 'log') else 0
        if args.mode in ('hybrid', 'mt-agree', 'alignatt', 'clause'):
            words = hybrid(audio, args.zipformer, translator, silence=args.pause, pause_tail=args.pause_tail)
        else:
            words = agree(audio, engine, gpu, translator, args.step)
        hebrew = ' '.join(w['text'] for w in words)
        chunked = translator.text()
        if hasattr(translator, 'generation'):
            generated, generating = translator.generation
        else:
            runs = [e for n, e in engine.log.events[logged:] if n == 'mt_generation'] if hasattr(engine, 'log') else []
            generated, generating = sum(e['tokens'] for e in runs), sum(e['seconds'] for e in runs)
        reference_translation = whole(engine, hebrew, 2)
        row = dict(wav=wav.name, mode=args.mode, direction=args.direction, span=args.span,
                   deadline=args.deadline, pause=args.pause,
                   k=args.k if args.mode == 'mt-agree' else None,
                   instruction=not args.no_instruction if args.mode == 'mt-agree' else None,
                   skipped=getattr(translator, 'skipped', None), stops=getattr(translator, 'stops', None),
                   heads=args.heads if args.mode in ('alignatt', 'clause') else None,
                   margin=args.margin if args.mode in ('alignatt', 'clause') else None, zscore=args.zscore if args.mode in ('alignatt', 'clause') else None,
                   min_prob=args.min_prob if args.mode in ('alignatt', 'clause') else None, hold_end=args.hold_end if args.mode in ('alignatt', 'clause') else None, step=args.step if args.mode == 'agree' else None,
                   seconds=round(len(audio) / RATE, 1), wall=round(time.perf_counter() - began, 1),
                   words=len(words), chunks=translator.chunks, capped=translator.capped,
                   words_per_chunk=round(len(translator.words) / max(1, translator.chunks), 2),
                   hebrew_lag=stats([w['shown'] - w['spoken'] for w in words]),
                   translation_lag=stats([w['translated'] - w['spoken'] for w in translator.words]),
                   gpu_busy=round(gpu.busy / (len(audio) / RATE), 3), erased_words=0,
                   chrf_chunked_vs_whole=round(chrf(chunked, reference_translation), 1),
                   doubtful=doubtful(getattr(translator, 'shown_pairs', None) or translator.shown),
                   doubtful_whole=doubtful(whole.pairs),
                   tokens_per_chunk=round(generated / max(1, translator.chunks), 1),
                   tokens_per_s=round(generated / max(1e-6, generating), 1))
        if args.translator:
            import mlx.core as mx
            calls = engine.calls
            row.update(translator=args.translator.name, peak_gb=round(mx.get_peak_memory() / 1e9, 2),
                       tokens_per_s=round(sum(c[1] for c in calls) / max(1e-6, sum(c[2] for c in calls)), 1),
                       calls=calls)
            engine.calls = []
        reference = wav.with_suffix('.txt')
        if reference.is_file():
            row['wer'] = round(corpus_wer([(reference.read_text(), hebrew)])[0], 4)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if args.text_dir:
            args.text_dir.mkdir(parents=True, exist_ok=True)
            name = f'{wav.stem}.{args.direction}.{args.mode}.{args.span}.d{args.deadline}p{args.pause}.k{args.k}.{int(not args.no_instruction)}' + (f'.h{args.heads}m{args.margin}z{int(args.zscore)}p{args.min_prob}e{int(args.hold_end)}' if args.mode in ('alignatt', 'clause') else '')
            (args.text_dir / f'{name}.json').write_text(json.dumps(dict(
                hebrew=hebrew, chunks=getattr(translator, 'shown_pairs', None) or translator.shown, whole=reference_translation,
                words=[{k: w.get(k) for k in ('text', 'spoken', 'shown', 'translated')} for w in translator.words]),
                ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
