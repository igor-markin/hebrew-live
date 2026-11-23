"""Append-only live screen (opt-in): shown Hebrew and shown translation are never changed.

    HEBREW_LIVE_APPEND=1  HEBREW_LIVE_HYBRID_MODEL=/path/to/zipformer2-66m-streaming-he
    [HEBREW_LIVE_APPEND_SPAN=2.0]

Hebrew comes word by word from the streaming zipformer (it never rewrites a written word). The
words are translated in chunks that end at a comma or a sentence end, or once the chunk's first
word was spoken HEBREW_LIVE_APPEND_SPAN seconds ago (the cap that keeps the translation within
about three seconds of speech in fast speech without pauses). Each chunk is translated as the
continuation of the chunks before it (`translation.prompt` pairs), so a shown translation is never
redone. A sentence end or a pause closes the card. Whisper is not used.

Measured design: experiments/live-append/simulate.py. Every shown word's lag (from the end of the
word in the audio) goes to the diagnostics: `append_words` for Hebrew, `append_chunk` for its
translation.
"""
import os
import queue
import re
import threading
import time
from types import SimpleNamespace

import numpy as np

from . import streaming_asr

RATE = 16000
CLAUSE = re.compile(r'[.,?!…:;]["»”)]*$')
SENTENCE = re.compile(r'[.?!…]["»”)]*$')
PAUSE_TAIL = .8      # seconds of silence fed at a pause so the last words come out
GAP_LIMIT = .5       # silence fed for a gap between speech pieces
CONTEXT = 4          # previous chunks given to the translator


def enabled():
    return os.environ.get('HEBREW_LIVE_APPEND', '0') == '1'


def span_seconds():
    try:
        return max(.3, float(os.environ.get('HEBREW_LIVE_APPEND_SPAN', '2.0')))
    except ValueError:
        return 2.


class Card:
    def __init__(self, sid, settings, start):
        self.sid, self.settings, self.start = sid, settings, start
        self.words, self.translations = [], []
        self.sent = 0          # words handed to the translator
        self.outstanding = 0   # chunks not translated yet
        self.closing = self.closed = False
        self.reason = None


class AppendProcessor:
    """The interface `feed.inference` uses: process, flush, poll_mt, drain_mt, shutdown_mt."""
    async_mt = False
    _mt_outstanding = 0
    catchup_inbox = None

    def __init__(self, engine, updates, log, cancel, recognizer=None, span=None):
        self.engine, self.updates, self.log, self.cancel = engine, updates, log, cancel
        if recognizer is None:
            draft = streaming_asr.load(log, flag='HEBREW_LIVE_APPEND')
            if draft is None:
                raise RuntimeError('append mode needs the streaming model (HEBREW_LIVE_HYBRID_MODEL)')
            recognizer = draft.recognizer
        self.recognizer = recognizer
        self.span = span_seconds() if span is None else span
        self.counter = self.export_counter = self.mt_counter = 0
        self.lock = threading.RLock()
        self.jobs = queue.Queue()
        self.pairs = []
        self.settings = None
        self.clock = None
        self.card = None
        self.new_stream()
        self.worker = threading.Thread(target=self._translate_loop, name='append-translation', daemon=True)
        self.worker.start()

    # ---- audio and words -------------------------------------------------------------
    def new_stream(self):
        self.stream = self.recognizer.create_stream()
        self.fed = None          # absolute sample fed up to
        self.stream_samples = 0
        self.mapping = []        # (stream sample, absolute sample) where a run of real audio starts
        self.seen = 0
        self.current = None
        self.idle = 0

    def audio_now(self):
        return time.monotonic() - self.clock if self.clock is not None else 0.

    def _feed(self, samples, absolute=None):
        if absolute is not None:
            self.mapping.append((self.stream_samples, absolute))
        self.stream.accept_waveform(RATE, np.asarray(samples, dtype=np.float32))
        self.stream_samples += len(samples)
        decoded = False
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
            decoded = True
        return decoded

    def _absolute(self, seconds):
        sample = int(seconds * RATE)
        for stream_start, absolute in reversed(self.mapping):
            if stream_start <= sample:
                return absolute + sample - stream_start
        return self.mapping[0][1] if self.mapping else 0

    def process(self, f):
        if self.cancel.is_set():
            return
        if self.settings is not None and f.settings != self.settings:
            self.flush('settings')
        self.settings = f.settings
        self.clock = f.end - f.offset
        end = round(f.offset * RATE)
        start = end - len(f.audio)
        decoded = False
        if self.fed is None or end > self.fed:
            begin = start if self.fed is None else max(self.fed, start)
            if self.fed is not None and start > self.fed:
                decoded |= self._feed(np.zeros(min(start - self.fed, int(GAP_LIMIT * RATE)), np.float32))
            decoded |= self._feed(np.asarray(f.audio)[begin - start:], absolute=begin)
            self.fed = end
        closing = f.final and f.reason != 'window'
        if closing:
            decoded |= self._feed(np.zeros(int(PAUSE_TAIL * RATE), np.float32))
        self.collect(decoded, final=closing, reason=f.reason if closing else None)

    def collect(self, decoded, final=False, reason=None):
        result = self.recognizer.get_result_all(self.stream)
        tokens, stamps = list(result.tokens), list(result.timestamps)
        fresh = len(tokens) > self.seen
        done = []
        for token, stamp in zip(tokens[self.seen:], stamps[self.seen:]):
            if token.startswith((' ', '▁')) and self.current is not None:
                done.append(self.current)
                self.current = None
            if self.current is None:
                self.current = dict(text='')
            self.current['text'] += token.replace('▁', ' ').strip()
            self.current['end'] = self._absolute(float(stamp) + .04)
        self.seen = len(tokens)
        # A word goes on in the next token unless that one starts with a space: it is finished
        # when the next word starts, at a pause, or after two decoded chunks that brought nothing.
        self.idle = 0 if fresh else self.idle + decoded
        if self.current is not None and (final or self.idle >= 2):
            done.append(self.current)
            self.current = None
        done = [w for w in done if w['text']]
        if done:
            self.show(done)
        self.chunk(final, reason)

    # ---- the screen ------------------------------------------------------------------
    def show(self, words):
        now = self.audio_now()
        with self.lock:
            touched = []
            for word in words:
                if self.card is None or self.card.closing:
                    self.counter += 1
                    self.card = Card(3_000_000 + self.counter, self.settings, word['end'])
                word['shown'] = now
                self.card.words.append(word)
                if self.card not in touched:
                    touched.append(self.card)
                if SENTENCE.search(word['text']):
                    self.chunk(False, None, sentence=True)
            for card in touched:
                if not card.closed:
                    self.publish(card, lag=max(0., now - card.words[-1]['end'] / RATE))
        self.log.event('append_words', part=self.settings.part, count=len(words),
                       lags=[round(max(0., now - w['end'] / RATE), 3) for w in words])

    def chunk(self, final, reason, sentence=False):
        """Hand the words that are due to the translator."""
        with self.lock:
            card = self.card
            if card is None or card.closing:
                return
            pending = card.words[card.sent:]
            if pending:
                cut = next((i + 1 for i, w in enumerate(pending) if CLAUSE.search(w['text'])), None)
                if cut is None and (final or self.audio_now() - pending[0]['end'] / RATE >= self.span):
                    cut = len(pending)
                while cut:
                    self.send(card, pending[:cut])
                    pending = pending[cut:]
                    cut = next((i + 1 for i, w in enumerate(pending) if CLAUSE.search(w['text'])), None)
                    if cut is None and final and pending:
                        cut = len(pending)
            if sentence or final:
                card.closing = True
                card.reason = reason or 'sentence'
                if not card.outstanding:
                    self.close(card)

    def send(self, card, words):
        card.sent += len(words)
        card.outstanding += 1
        self.mt_counter += 1
        self.jobs.put((card, words, self.settings))

    def publish(self, card, lag, stage='open'):
        source = ' '.join(w['text'] for w in card.words)
        translation = ' '.join(t for t in card.translations if t)
        end = card.words[-1]['end'] if card.words else card.start
        value = dict(current=dict(source=source, translation=translation, fragment=card.sid,
                                  revision=len(card.words) + len(card.translations), source_status='accepted'),
                     history=[], stage=stage, issue=None, reason=card.reason if stage != 'open' else None,
                     start=card.start / RATE, end=end / RATE)
        now = time.monotonic()
        self.updates.put(('context', card.sid, card.settings))
        self.updates.put(('live_publication', card.sid, dict(value, emitted_at=now, audio_lag=lag)))
        self.log.event('live_publication', part=card.settings.part, segment=card.sid, **value, audio_lag=lag)

    def close(self, card):
        if card.closed:
            return
        card.closed = True
        self.publish(card, lag=0., stage='closed')
        try:
            part = self.log.parts[card.settings.part]
        except (AttributeError, KeyError, TypeError):
            part = None
        if part:
            self.export_counter += 1
            record = SimpleNamespace(id=6_000_000 + self.export_counter, start=card.start / RATE,
                                     offset=card.words[-1]['end'] / RATE if card.words else card.start / RATE,
                                     audio=(), prefix=0.)
            label = f'[Группа {card.sid}; дописывание; closed]\n'
            part.text('source', record, label + ' '.join(w['text'] for w in card.words))
            part.text('target', record, label + ' '.join(t for t in card.translations if t))

    # ---- translation -----------------------------------------------------------------
    def _translate_loop(self):
        while True:
            job = self.jobs.get()
            try:
                if job is None:
                    return
                self._translate(*job)
            except Exception as error:  # a failed chunk must not stop the screen
                try:
                    self.log.event('append_failed', error=type(error).__name__)
                except Exception:
                    pass
            finally:
                self.jobs.task_done()

    def _translate(self, card, words, settings):
        text = ' '.join(w['text'] for w in words)
        e = self.engine
        e.language, e.direction, e.topic = settings.language, settings.direction, settings.topic
        began = time.monotonic()
        out, capped = '', False
        limit_words, limit_chars = 3 * len(words) + 3, 3 * len(text) + 20
        if not self.cancel.is_set():
            for piece, _ in e.translate(text, context=tuple(self.pairs[-CONTEXT:])):
                out += piece
                if len(out.split()) > limit_words or len(out) > limit_chars or self.cancel.is_set():
                    capped = True
                    break
        out = out.strip()
        now = self.audio_now()
        with self.lock:
            # A runaway that had to be cut stays on screen but is not context for the next chunks.
            if not capped:
                self.pairs.append((text, out))
            card.translations.append(out)
            card.outstanding -= 1
            lags = [round(max(0., now - w['end'] / RATE), 3) for w in words]
            self.publish(card, lag=max(lags))
            if card.closing and not card.outstanding:
                self.close(card)
        self.log.event('append_chunk', part=settings.part, segment=card.sid, words=len(words),
                       seconds=round(time.monotonic() - began, 3), capped=capped, lags=lags)

    # ---- the feed interface ----------------------------------------------------------
    def poll_mt(self, wait=False):
        if wait:
            self.drain_mt()

    def drain_mt(self):
        self.jobs.join()

    def flush(self, reason='eof'):
        if self.settings is not None and self.fed is not None:
            decoded = self._feed(np.zeros(int(PAUSE_TAIL * RATE), np.float32))
            self.collect(decoded, final=True, reason=reason)
        self.drain_mt()
        with self.lock:
            if self.card is not None and not self.card.closed:
                self.card.closing = True
                self.card.reason = self.card.reason or reason
                self.close(self.card)
            self.card = None
        if reason in ('settings', 'direction', 'models'):
            self.pairs = []
        self.new_stream()

    def finish(self, reason, valid=False, job=None):
        self.flush(reason)

    def shutdown_mt(self):
        self.jobs.put(None)
        self.worker.join(timeout=5)
