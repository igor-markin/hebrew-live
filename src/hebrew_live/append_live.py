"""Append-only live screen for Hebrew speech: shown Hebrew and shown translation are never changed.

    [HEBREW_LIVE_APPEND=0]  [HEBREW_LIVE_HYBRID_MODEL=/path/to/zipformer2-66m-streaming-he]
    [HEBREW_LIVE_APPEND_DEADLINE=4.5]

On by default; HEBREW_LIVE_APPEND=0, another source language, or a missing streaming model keep
the retranslating screen (DraftRouter). The model is the one bundled with the app unless
HEBREW_LIVE_HYBRID_MODEL names another.

Hebrew comes word by word from the streaming zipformer (it never rewrites a written word). The
open sentence is translated by MiLMMT continuing the translation already shown (clause_mt:
forced prefix, AlignAtt stop), so a shown translation is never redone. A call is made when a
clause ends (comma, ;, :) and a word after it is heard, up to that clause; or, without a clause
end, when the first untranslated word would otherwise miss HEBREW_LIVE_APPEND_DEADLINE seconds
(the call time is estimated from the calls so far), up to all but the last word. A sentence end
or a pause closes the card with a call that translates the rest. When the model ends a sentence
the Hebrew goes on with, the Russian sentence ends there and the rest starts a new one.
A live call also stops before a number or a day (weekday, «сегодня») the Hebrew has not said.
When a card closes with a number or a day that does not match its Hebrew, the sentence is
translated once more as a whole and, if that matches better, added after the shown translation
as «(Уточнение: …)» with the words that changed. Every sentence of the card is checked, also one
that ended before the card closed. A translation that was cut short or still does not match is not
shown. HEBREW_LIVE_CLOSE_RECHECK=0 switches this off.
HEBREW_LIVE_APPEND_MIN_PROB (default 0) also stops at a token the model is less sure of.
Whisper is not used.

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
PUNCTUATION = re.compile(r'[.,?!…:;]+')
PUNCTUATION_WORD = re.compile(r'[.,?!…:;»"”)\]]+')   # not a dash: «— 80» starts a word group
PAUSE_TAIL = .8      # seconds of silence fed at a pause so the last words come out
GAP_LIMIT = .5       # silence fed for a gap between speech pieces
CONTEXT = 4          # previous chunks given to the translator
_EDGE = '.,?!…:;«»"”()[]—–-'
SAFETY = .3          # seconds kept in reserve before the deadline
QUIET = 1.           # seconds without a newer word after which the last word may be translated
TICK = .1            # how often waiting chunks are checked against their deadline


def _facts(words, language):
    """The numbers (figures or words) and days named in these translation words."""
    from .number_guard import _classify
    from .weekday_guard import _RELATIVE, _russian_days
    found = []
    for word in words:
        bare = word.strip(_EDGE).lower()
        number, days = _classify(bare, language), _russian_days(bare)
        if any(c.isdigit() for c in bare) or bare in _RELATIVE:
            found.append(bare)
        elif number:
            found.append(str(number[1]))
        elif days:
            found.append(days[0][0])
    return sorted(found)


def _days(words):
    from .weekday_guard import _RELATIVE, _russian_days
    return any(w.strip(_EDGE).lower() in _RELATIVE or _russian_days(w) for w in words)


def changed_piece(shown, again, language='ru', context=2):
    """The words of `again` that changed where a number or a day is named, with `context` words
    around them; '' when the numbers and days are the same. Several places are joined with «… »."""
    import difflib
    a, b = shown.split(), again.split()
    keys = [[w.strip(_EDGE).lower() for w in words] for words in (a, b)]
    spans = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, *keys, autojunk=False).get_opcodes():
        if tag == 'equal' or _facts(a[i1:i2], language) == _facts(b[j1:j2], language):
            continue
        if i1 == i2 == len(a) and not any(c.isdigit() for w in b[j1:j2] for c in w) and not _days(b[j1:j2]):
            continue   # words of the next sentence («Стоимость первого посещения»), not a change
        start, end = max(0, j1 - context), min(len(b), j2 + context)
        if spans and start <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    pieces = [('… ' if start else '') + ' '.join(b[start:end]) + (' …' if end < len(b) else '') for start, end in spans]
    return ' '.join(pieces).replace('… …', '…')


def enabled():
    return os.environ.get('HEBREW_LIVE_APPEND', '1') == '1'


def hebrew_source(settings):
    from .languages import split_direction
    try:
        return split_direction(settings.direction)[0] == 'he'
    except (AttributeError, ValueError):
        return False


class DraftRouter:
    """The live screen feed.inference drives: append-only (AppendProcessor) for Hebrew speech,
    or the retranslating screen (RetranslationProcessor) when the streaming model cannot be
    loaded. The product engine no longer recognizes whole groups (Whisper is gone), so there
    that fallback only reports errors; the app checks the streaming model before a session
    starts (runtime.run_session). Both number groups from one counter."""
    COUNTERS = ('counter', 'export_counter', 'mt_counter')

    def __init__(self, engine, updates, log, cancel, append=None):
        from .retranslation import RetranslationProcessor
        self.retranslation = RetranslationProcessor(engine, updates, log, cancel)
        self.append = append
        if self.append is None and enabled():
            try:
                self.append = AppendProcessor(engine, updates, log, cancel)
            except Exception as error:
                try:
                    log.event('append_unavailable', error=type(error).__name__, detail=str(error)[:200])
                except Exception:
                    pass
        self.active = self.append or self.retranslation
        self._inbox = None

    def _pick(self, settings):
        wanted = self.append if self.append is not None and hebrew_source(settings) else self.retranslation
        if wanted is not self.active:
            self.active.flush('direction')
            for name in self.COUNTERS:
                setattr(wanted, name, max(getattr(wanted, name), getattr(self.active, name)))
            self.active = wanted

    def process(self, f):
        self._pick(f.settings)
        self.active.process(f)

    def __getattr__(self, name):
        if name in DraftRouter.COUNTERS or name in ('async_mt', '_mt_outstanding', 'poll_mt', 'flush', 'drain_mt'):
            return getattr(self.active, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in DraftRouter.COUNTERS:
            setattr(self.active, name, value)
        elif name == 'catchup_inbox':
            self.retranslation.catchup_inbox = value
            if self.append is not None:
                self.append.catchup_inbox = value
        else:
            object.__setattr__(self, name, value)

    def shutdown_mt(self):
        if self.append is not None:
            self.append.shutdown_mt()
        self.retranslation.shutdown_mt()


def new_words_cap(hebrew_words):
    """New translation words allowed when nothing heard follows (a pause, a quiet): a little more
    than the Hebrew needs, too few to finish the speaker's sentence for them."""
    return int(1.25 * hebrew_words) + 1


def min_probability():
    try:
        return float(os.environ.get('HEBREW_LIVE_APPEND_MIN_PROB', '0'))
    except ValueError:
        return 0.


def deadline_seconds():
    try:
        return max(1., float(os.environ.get('HEBREW_LIVE_APPEND_DEADLINE', '4.5')))
    except ValueError:
        return 4.5


class EngineGenerator:
    """clause_mt through the engine (cli.Engine.clause_generate), which may live in a worker
    process (remote_engine): the model is used only where it was loaded."""

    def __init__(self, engine, min_prob=0.):
        self.engine, self.min_prob = engine, min_prob

    def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
        from .clause_mt import Result
        value = self.engine.clause_generate(text, forced, [list(p) for p in pairs], direction, upto=upto,
                                            close=close, max_new=max_new, min_prob=self.min_prob)
        return Result(value['words'], value['stop'], value.get('end_mark'), value.get('tokens', 0))


class Card:
    def __init__(self, sid, settings, start):
        self.sid, self.settings, self.start = sid, settings, start
        self.words, self.out = [], []   # Hebrew words (dicts), translation words shown
        self.covered = 0       # Hebrew words the shown translation covers
        self.base = self.base_out = 0   # where the open sentence starts in words / out
        self.notes = []        # (start, end) of the «(Уточнение: …)» in out
        self.tried = None      # (words heard, upto) of a call that added nothing: not again
        self.end_mark = None   # the sentence end the model wanted after the shown words
        self.closing = self.closed = False
        self.reason = None


class AppendProcessor:
    """The interface `feed.inference` uses: process, flush, poll_mt, drain_mt, shutdown_mt."""
    async_mt = False
    _mt_outstanding = 0
    catchup_inbox = None

    def __init__(self, engine, updates, log, cancel, recognizer=None, deadline=None, ticker=True, generator=None):
        self.engine, self.updates, self.log, self.cancel = engine, updates, log, cancel
        if recognizer is None:
            draft = streaming_asr.load(log, flag='HEBREW_LIVE_APPEND', default='1')
            if draft is None:
                raise RuntimeError('append mode needs the streaming model (HEBREW_LIVE_HYBRID_MODEL)')
            recognizer = draft.recognizer
        self.recognizer = recognizer
        self.deadline = deadline_seconds() if deadline is None else deadline
        self.timings = []        # (words, seconds) of recent translation calls
        self.busy = False        # a call is queued or running
        self.cards = []          # cards not closed yet, oldest first
        if generator is None:
            generator = EngineGenerator(engine, min_probability())
        self.generator = generator
        self.counter = self.export_counter = self.mt_counter = 0
        self.lock = threading.RLock()
        self.jobs = queue.Queue()
        self.pairs = []
        self.settings = None
        self.clock = None
        self.card = None
        self.new_stream()
        self.stopped = threading.Event()
        self.worker = threading.Thread(target=self._translate_loop, name='append-translation', daemon=True)
        self.worker.start()
        if ticker:
            threading.Thread(target=self._tick_loop, name='append-deadline', daemon=True).start()

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
            piece = token.replace('▁', ' ').strip()
            if PUNCTUATION.fullmatch(piece):
                # «תור ,»: the mark ends the word before it, it is not a word of its own
                if self.current is not None:
                    self.current['text'] += piece
                    continue
                if done:
                    done[-1]['text'] += piece
                    continue
                self.punctuate(piece)
                continue
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
                    self.cards.append(self.card)
                word['shown'] = now
                self.card.words.append(word)
                if self.card not in touched:
                    touched.append(self.card)
                if SENTENCE.search(word['text']):
                    self.card.closing = True
                    self.card.reason = 'sentence'
            for card in touched:
                if not card.closed:
                    self.publish(card, lag=max(0., now - card.words[-1]['end'] / RATE))
        self.log.event('append_words', part=self.settings.part, count=len(words),
                       lags=[round(max(0., now - w['end'] / RATE), 3) for w in words])

    def punctuate(self, mark):
        """A punctuation token after its word was shown: it ends that word (only the end of the
        shown Hebrew changes, by the mark), also after a pause while the card is closing; with
        no open card it is dropped."""
        with self.lock:
            card = self.card
            if card is None or card.closed or not card.words:
                return True   # nothing to end: a mark alone is not shown
            card.words[-1]['text'] += mark
            if SENTENCE.search(mark) and not card.closing:
                card.closing = True
                card.reason = 'sentence'
            self.publish(card, lag=max(0., self.audio_now() - card.words[-1]['end'] / RATE))
            return True

    def chunk(self, final, reason, sentence=False, tick=False):
        """A pause (final) closes the card; then start a translation call if one is due."""
        with self.lock:
            if final and self.card is not None and not self.card.closing:
                self.card.closing = True
                self.card.reason = reason or 'pause'
            self.schedule()

    def estimate(self, words):
        """Seconds a call for `words` Hebrew words is expected to take: the slowest recent rate."""
        per_word = max([.12] + [(seconds - .25) / max(1, n) for n, seconds in self.timings[-20:]])
        return .25 + per_word * words

    def due(self, card):
        """(upto, why) of the call the open card needs now, or None.

        A clause end (comma, ;, :) with a word heard after it: up to the clause. No clause end,
        but the first untranslated word would otherwise miss the deadline: all but the last word,
        or the last word when it is the only one left."""
        words = card.words
        uncovered = words[card.covered:]
        if not uncovered:
            return None
        clause = max((i for i, w in enumerate(uncovered[:-1]) if CLAUSE.search(w['text'])), default=None)
        if clause is not None:
            return card.covered + clause + 1, 'clause'
        now = self.audio_now()
        if now + self.estimate(len(uncovered)) + SAFETY >= uncovered[0]['end'] / RATE + self.deadline:
            # all but the last word; the last one too once it is the one that is due and no
            # newer word came for QUIET seconds (a quiet the pause detector did not take for a pause)
            alone = len(uncovered) == 1 and now - uncovered[0]['shown'] >= QUIET
            return len(words) - (not alone), 'deadline'
        return None

    def schedule(self):
        """Hand the translator its next call while it is idle: the oldest card that is over gets
        its last call, else the open card one if due. Called under the lock."""
        if self.busy or self.cancel.is_set():
            return
        for card in self.cards:
            if card.closed:
                continue
            if card.closing:
                self.busy = True
                self.jobs.put((card, None, 'close', card.settings))
                return
            due = self.due(card)
            if due is None:
                return
            upto, why = due
            if upto <= card.covered or card.tried == (len(card.words), upto):
                return
            self.busy = True
            self.jobs.put((card, upto, why, card.settings))
            return

    def _tick_loop(self):
        while not self.stopped.wait(TICK):
            if self.clock is not None and not self.cancel.is_set():
                with self.lock:
                    self.schedule()

    def publish(self, card, lag, stage='open'):
        source = ' '.join(w['text'] for w in card.words)
        translation = ' '.join(card.out)
        end = card.words[-1]['end'] if card.words else card.start
        value = dict(current=dict(source=source, translation=translation, fragment=card.sid,
                                  revision=len(card.words) + len(card.out), source_status='accepted'),
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
        if card in self.cards:
            self.cards.remove(card)
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
            part.text('target', record, label + ' '.join(card.out))

    # ---- translation -----------------------------------------------------------------
    def _translate_loop(self):
        while True:
            job = self.jobs.get()
            try:
                if job is None:
                    return
                try:
                    self._translate(*job)
                except Exception as error:  # a failed call must not stop the screen
                    try:
                        import traceback
                        where = traceback.extract_tb(error.__traceback__)[-1]
                        self.log.event('append_failed', error=type(error).__name__, detail=str(error)[:200],
                                       where=f'{os.path.basename(where.filename)}:{where.lineno}')
                    except Exception:
                        pass
                    with self.lock:
                        card = job[0]
                        if job[2] == 'close' and not card.closed:
                            self.close(card)
                        else:
                            card.tried = (len(card.words), job[1])
            finally:
                with self.lock:
                    self.busy = False
                    if job is not None:
                        self.schedule()
                self.jobs.task_done()

    def _split(self, card):
        """The model ended its sentence after the shown words while the Hebrew went on (no
        sentence end heard): end the translation's sentence there and go on with the rest of the
        Hebrew as a new sentence, the finished pair as context. Keeps prompts short and aligned."""
        card.out[-1] += card.end_mark
        hebrew = ' '.join(w['text'] for w in card.words[card.base:card.covered])
        shown = ' '.join(card.out[card.base_out:])
        before = tuple(self.pairs[-CONTEXT:])
        self.pairs.append((hebrew, shown))
        card.base, card.base_out, card.end_mark = card.covered, len(card.out), None
        return hebrew, shown, before

    def _translate(self, card, upto, why, settings):
        e = self.engine
        e.language, e.direction, e.topic = settings.language, settings.direction, settings.topic
        began = time.monotonic()
        close = why == 'close'
        with self.lock:
            ended = None
            if card.end_mark and card.out and card.covered > card.base:
                ended = self._split(card)
            card.end_mark = None
        if ended:
            hebrew, shown, before = ended
            better, piece = self._recheck(card, hebrew, shown, before, settings, 'split')
            if piece:
                with self.lock:
                    self._note(card, piece, settings)
                    self.pairs[-1] = (hebrew, better)
                    self.publish(card, lag=0.)
        with self.lock:
            words = card.words[card.base:]
            text = ' '.join(w['text'] for w in words)
            forced = ' '.join(card.out[card.base_out:])
            pairs = tuple(self.pairs[-CONTEXT:])
        result = None
        if text and not self.cancel.is_set():
            if close and card.reason != 'sentence':
                # A pause is not a sentence end: the model must not finish the sentence for the
                # speaker. Stops on, all words may be covered, and no more new words than the
                # Hebrew left can need.
                left = len(words) - (card.covered - card.base)
                result = self.generator.generate(text, forced, pairs, settings.direction, upto=len(words),
                                                 close=False, max_new=new_words_cap(left))
            elif close:
                result = self.generator.generate(text, forced, pairs, settings.direction, close=True)
            else:
                relative = upto - card.base
                # nothing heard after: no attention stop, so a cap on new words
                cap = new_words_cap(upto - card.covered) if relative == len(words) else None
                result = self.generator.generate(text, forced, pairs, settings.direction, upto=relative,
                                                 max_new=cap)
        added = list(result.words) if result else []
        stop = result.stop if result else 'empty'
        with self.lock:
            upto = len(card.words) if close else upto
            # A mark the model puts first («?», «»», «.») belongs to the word before it; at the
            # start of a card there is none, and a mark alone is not shown.
            while added and PUNCTUATION_WORD.fullmatch(added[0]):
                mark = added.pop(0)
                if card.out:
                    card.out[-1] += mark
            if not close and added:
                cut = self._numbers(card, added, settings)
                if cut is not None:
                    added, stop = added[:cut], 'number'
                cut = self._unheard_day(card, added, settings)
                if cut is not None:
                    added, stop = added[:cut], 'day'
            new, days = self._weekdays(card, upto, self._plain(card), ' '.join(added), settings)
            added = new.split()
            card.out.extend(added)
            now = self.audio_now()
            covered = []
            # 'end' with nothing added: the shown translation already says what was heard.
            if close or stop in ('sentence', 'end') or added and stop == 'frontier':
                covered = card.words[card.covered:upto]
                card.covered, card.tried = upto, None
                if stop == 'sentence' and card.out:
                    card.end_mark = result.end_mark
            else:
                card.tried = (len(card.words), upto)
            lags = [round(max(0., now - w['end'] / RATE), 3) for w in covered]
            self.timings = self.timings[-19:] + [(max(1, len(covered)), time.monotonic() - began)]
            self.mt_counter += 1
            if added or close:
                self.publish(card, lag=max(lags) if lags else 0.)
        if close:
            shown = ' '.join(card.out[card.base_out:])
            better, piece = self._recheck(card, text, shown, pairs, settings, 'close')
            with self.lock:
                if card.covered > card.base or shown:
                    self.pairs.append((' '.join(w['text'] for w in card.words[card.base:]), better or shown))
                if piece:
                    self._note(card, piece, settings)
                self.close(card)
        self.log.event('append_chunk', part=settings.part, segment=card.sid, why=why, stop=stop,
                       words=len(covered), added=len(added), seconds=round(time.monotonic() - began, 3),
                       capped=stop == 'cap', lags=lags)
        if days:
            self.log.event('weekday_check', part=settings.part, segment=card.sid, stage='append', issues=days)

    def _numbers(self, card, added, settings):
        """Index of the first new word with a number the open sentence's Hebrew has not said
        (number_guard.unheard), or None. A live call stops there and the words wait for the
        number to be heard; the last call of a card (the sentence is over) is not held."""
        if os.environ.get('HEBREW_LIVE_NUMBER_WAIT', '1') == '0':
            return None
        from .languages import split_direction
        source, target = split_direction(settings.direction)
        if source != 'he':
            return None
        from .number_guard import unheard
        hebrew = ' '.join(w['text'] for w in card.words[card.base:])
        return unheard(hebrew, ' '.join(card.out[card.base_out:]), added, 'he', target)

    def _unheard_day(self, card, added, settings):
        """Index of the first new word with a weekday or «сегодня», «завтра» the open sentence's
        Hebrew has not said (weekday_guard.unheard), or None. Held like a number."""
        if os.environ.get('HEBREW_LIVE_WEEKDAY_CHECK', '1') == '0' or not added:
            return None
        from .languages import split_direction
        if split_direction(settings.direction) != ('he', 'ru'):
            return None
        from .weekday_guard import unheard
        hebrew = ' '.join(w['text'] for w in card.words[card.base:])
        return unheard(hebrew, ' '.join(card.out[card.base_out:]), added)

    def _mismatches(self, hebrew, translation, settings):
        """Numbers and days that differ between a sentence and its translation."""
        from .languages import split_direction
        from .number_guard import check
        source, target = split_direction(settings.direction)
        found = [f'{issue.kind} {issue.number}' for issue in check(hebrew, translation, source, target)]
        if (source, target) == ('he', 'ru'):
            from .weekday_guard import fix, relative_days
            _, days = fix(hebrew, translation, len(translation) + 1)   # nothing replaced, all reported
            found += [f'{issue.kind} {issue.ru or issue.he}' for issue in days]
            found += [f'extra {word}' for _, word in relative_days(hebrew, translation)]
        return found

    def _recheck(self, card, text, shown, pairs, settings, stage):
        """(translation, changed words) of a sentence translated once more as a whole, when the
        shown translation has a number or a day its Hebrew does not, and the new one has none and
        was not cut short; else ('', '')."""
        if os.environ.get('HEBREW_LIVE_CLOSE_RECHECK', '1') == '0' or not text or not shown or self.cancel.is_set():
            return '', ''
        issues = self._mismatches(text, shown, settings)
        if not issues:
            return '', ''
        from .languages import split_direction
        began = time.monotonic()
        result = self.generator.generate(text, '', pairs, settings.direction, close=True)
        again = ' '.join(result.words)
        if settings.direction == 'he-ru':
            from .weekday_guard import fix
            again, _ = fix(text, again)
        left = self._mismatches(text, again, settings) if again else ['empty']
        why = 'cut' if result.stop != 'end' or len(again.split()) < .6 * len(shown.split()) else 'mismatch' if left else ''
        piece = '' if why else changed_piece(shown, again, split_direction(settings.direction)[1])
        self.log.event('close_recheck', part=settings.part, segment=card.sid, stage=stage, issues=issues,
                       better=bool(piece), rejected=why or (None if piece else 'same'),
                       seconds=round(time.monotonic() - began, 3))
        return (again, piece) if piece else ('', '')

    def _note(self, card, piece, settings):
        """The changed words, after the shown translation; the next sentence starts after them."""
        label = 'Уточнение' if settings.direction.endswith('ru') else 'Correction'
        start = len(card.out)
        card.out.extend(f'({label}: {piece})'.split())
        card.notes.append((start, len(card.out)))
        card.base_out = len(card.out)

    def _plain(self, card):
        """The shown translation without the notes."""
        return ' '.join(w for i, w in enumerate(card.out) if not any(a <= i < b for a, b in card.notes))

    def _weekdays(self, card, upto, shown, out, settings):
        """The call's new words with a weekday the Hebrew does not name replaced (weekday_guard).
        The card's Hebrew up to `upto` is the context («ביום» may end the words before); only the
        new words can change, the shown translation stays."""
        if os.environ.get('HEBREW_LIVE_WEEKDAY_CHECK', '1') == '0' or not out:
            return out, []
        from .languages import split_direction
        if split_direction(settings.direction) != ('he', 'ru'):
            return out, []
        from .weekday_guard import fix
        source = ' '.join(w['text'] for w in card.words[:upto])
        frozen = len(shown) + 1 if shown else 0
        fixed, issues = fix(source, (shown + ' ' + out) if shown else out, frozen)
        new = fixed[frozen:] if shown else fixed
        new_hebrew = ' '.join(w['text'] for w in card.words[card.covered:upto])
        issues = [item._asdict() for item in issues if item.kind == 'fixed'
                  or item.kind == 'extra' and item.ru in new or item.kind == 'missing' and item.he in new_hebrew]
        return new, issues

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
            for card in list(self.cards):   # a call that failed to come: close what is shown
                card.closing = True
                card.reason = card.reason or reason
                self.close(card)
            self.card = None
        if reason in ('settings', 'direction', 'models'):
            self.pairs = []
        self.new_stream()

    def finish(self, reason, valid=False, job=None):
        self.flush(reason)

    def shutdown_mt(self):
        self.stopped.set()
        self.jobs.put(None)
        self.worker.join(timeout=5)
