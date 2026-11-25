import os
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from hebrew_live.append_live import AppendProcessor
from hebrew_live.clause_mt import Result
from hebrew_live.cli import Fragment
from hebrew_live.stream import Settings

RATE = 16000


class FakeRecognizer:
    """Writes a scripted token once the stream has been fed past its time (plus a 0.5 s delay)."""

    def __init__(self, script):
        self.script = script  # [(token, seconds)]

    def create_stream(self):
        return SimpleNamespace(samples=0, tokens=[], stamps=[], accept_waveform=None)

    def is_ready(self, stream):
        return False

    def decode_stream(self, stream):
        pass

    def get_result_all(self, stream):
        heard = stream.samples / RATE - .5
        tokens = [(t, s) for t, s in self.script if s <= heard]
        return SimpleNamespace(tokens=[t for t, _ in tokens], timestamps=[s for _, s in tokens])


def feeding(recognizer):
    stream = FakeRecognizer.create_stream(recognizer)
    stream.accept_waveform = lambda rate, samples: setattr(stream, 'samples', stream.samples + len(samples))
    return stream


class FakeGenerator:
    """Translates Hebrew word w as «ru:w», continuing after the forced words (one per Hebrew
    word), up to `upto` words; `stops` scripts the stop of each call ('frontier' by default)."""

    def __init__(self, stops=()):
        self.calls, self.stops = [], list(stops)

    def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
        self.calls.append(dict(text=text, forced=forced, pairs=pairs, upto=upto, close=close, max_new=max_new))
        words = text.split()
        upto = len(words) if close else (len(words) - 1 if upto is None else upto)
        out = ['ru:' + w for w in words[len(forced.split()):upto]]
        last = close or upto == len(words)
        stop = 'end' if last else (self.stops.pop(0) if self.stops else 'frontier')
        return Result(out, stop, '.' if stop == 'sentence' else None)


class Append(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.updates = queue.Queue()
        self.log = SimpleNamespace(event=lambda name, **v: self.events.append((name, v)))

    def make(self, script, deadline=4., generator=None):
        recognizer = FakeRecognizer(script)
        recognizer.create_stream = lambda: feeding(recognizer)
        self.generator = generator or FakeGenerator()
        return AppendProcessor(SimpleNamespace(), self.updates, self.log, threading.Event(), recognizer=recognizer,
                               deadline=deadline, ticker=False, generator=self.generator)

    def feed(self, processor, seconds, final=False, reason=''):
        audio = np.zeros(int(seconds * RATE), np.float32)
        now = time.monotonic()
        processor.process(Fragment(1, 1, audio, 0, now, final, Settings(publication='draft'), seconds, 0, reason))
        processor.drain_mt()

    def publications(self):
        return [v for kind, _, v in list(self.updates.queue) if kind == 'live_publication']

    def finish(self, processor):
        processor.drain_mt()
        processor.shutdown_mt()

    def warmed(self, already=False, generator=None):
        processor = self.make([(' שלום', .2), (' לך', .5), ('.', .6)], generator=generator)
        started = threading.Event()
        if already:
            started.set()
        processor.warm_on(started)
        return processor, started

    def test_start_warms_the_translator_once_and_shows_nothing(self):
        processor, started = self.warmed()
        processor.warm_if_started()
        self.assertEqual(self.generator.calls, [])   # waiting for Start
        started.set()
        for _ in range(3):
            processor.warm_if_started()
            processor.jobs.join()
        self.assertEqual([(c['close'], c['max_new'], c['pairs']) for c in self.generator.calls], [(True, 1, ())])
        self.assertEqual((self.publications(), processor.pairs, processor.timings), ([], [], []))
        self.assertEqual([n for n, _ in self.events], ['mt_prewarm'])
        started.clear()                              # the start was refused (no phone)
        processor.warm_if_started()
        started.set()
        processor.warm_if_started()
        processor.jobs.join()
        self.assertEqual(len(self.generator.calls), 2)
        self.finish(processor)

    def test_a_session_already_started_is_not_warmed(self):
        processor, _ = self.warmed(already=True)
        processor.warm_if_started()
        processor.jobs.join()
        self.assertEqual(self.generator.calls, [])
        self.finish(processor)

    def test_a_failed_warming_does_not_stop_the_translation(self):
        class Failing(FakeGenerator):
            def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
                if max_new == 1 and close:
                    raise RuntimeError('no')
                return super().generate(text, forced, pairs, direction, upto, close, max_new)
        processor, started = self.warmed(generator=Failing())
        started.set()
        processor.warm_if_started()
        processor.jobs.join()
        self.feed(processor, 1.6, final=True, reason='pause')
        self.finish(processor)
        self.assertEqual(self.publications()[-1]['current']['translation'], 'ru:שלום ru:לך.')
        self.assertIn('append_failed', [n for n, _ in self.events])

    def test_text_is_only_appended_and_a_clause_is_translated_once_a_word_follows_it(self):
        script = [(' שלום', .2), (',', .3), (' אני', .6), (' רוצה', .9), (' לק', 1.2), ('בוע', 1.3), (' תור', 1.6), ('.', 1.7)]
        processor = self.make(script)
        for seconds in (1., 1.5, 2., 2.5):
            self.feed(processor, seconds)
        self.feed(processor, 2.6, final=True, reason='pause')
        self.finish(processor)
        calls = self.generator.calls
        self.assertEqual((calls[0]['upto'], calls[0]['close']), (1, False))   # «שלום,» once «אני» is heard
        self.assertTrue(calls[-1]['close'])   # the Hebrew sentence ended: no stops
        shown = self.publications()
        for before, after in zip(shown, shown[1:]):
            if before['current']['source'] and after['start'] == before['start']:
                self.assertTrue(after['current']['source'].startswith(before['current']['source']))
                self.assertTrue(after['current']['translation'].startswith(before['current']['translation']))
        self.assertEqual(shown[-1]['stage'], 'closed')
        self.assertEqual(shown[-1]['current']['source'], 'שלום, אני רוצה לקבוע תור.')
        self.assertEqual(shown[-1]['current']['translation'], 'ru:שלום, ru:אני ru:רוצה ru:לקבוע ru:תור.')

    def test_without_a_clause_end_the_deadline_sends_the_words_due(self):
        script = [(' מילה', t / 10) for t in range(2, 40, 3)]
        processor = self.make(script, deadline=1.5)
        for step in range(5, 46, 3):
            self.feed(processor, step / 10)
        self.finish(processor)
        calls = [c for c in self.generator.calls if not c['close']]
        self.assertGreaterEqual(len(calls), 2)
        # all but the last word, or the last word alone once it is due (then with a cap)
        self.assertTrue(any(c['upto'] == len(c['text'].split()) - 1 for c in calls))
        self.assertTrue(all(c['upto'] == len(c['text'].split()) - 1 and c['max_new'] is None
                            or c['upto'] == len(c['text'].split()) and c['max_new'] for c in calls))
        lags = [lag for n, e in self.events if n == 'append_chunk' for lag in e['lags']]
        self.assertTrue(lags and max(lags) <= 1.5 + .5)

    def test_a_clause_waits_while_the_deadline_allows(self):
        script = [(' אני', .2), (' רוצה', .5), (' לקבוע', .8), (' תור', 1.1)]
        processor = self.make(script, deadline=4.)
        for seconds in (1., 1.3, 1.6):
            self.feed(processor, seconds)
        self.finish(processor)
        self.assertEqual(self.generator.calls, [])

    def test_a_separate_punctuation_token_ends_the_word_before_it(self):
        script = [(' שלום', .2), (' ,', .3), (' אני', .6), (' כאן', .9)]
        processor = self.make(script)
        self.feed(processor, 2., final=True, reason='pause')
        self.finish(processor)
        self.assertEqual(self.publications()[-1]['current']['source'], 'שלום, אני כאן')

    def test_a_mark_after_a_closed_card_is_not_a_card_of_its_own(self):
        script = [(' שלום', .2), (' ?', 3.)]
        processor = self.make(script)
        self.feed(processor, 1.5, final=True, reason='pause')
        self.feed(processor, 4.)
        self.feed(processor, 4.1, final=True, reason='pause')
        self.finish(processor)
        sources = {p['current']['source'] for p in self.publications()}
        self.assertNotIn('?', sources)

    def test_the_last_word_goes_alone_only_after_a_quiet(self):
        processor = self.make([], deadline=2.)
        processor.settings = Settings(publication='draft')
        at = lambda seconds: setattr(processor, 'clock', time.monotonic() - seconds)
        at(1.)
        processor.show([dict(text='אחת', end=int(.2 * RATE)), dict(text='שתיים', end=int(.5 * RATE))])
        for seconds in (1., 1.4, 1.8, 2.2, 2.6, 3.):
            at(seconds)
            with processor.lock:
                processor.schedule()
            processor.drain_mt()
        self.finish(processor)
        calls = self.generator.calls
        self.assertEqual(calls[0]['upto'], 1)   # «אחת» while «שתיים» is the newest word
        self.assertEqual(calls[-1]['upto'], 2)  # then «שתיים» too: nothing came after it for a second
        self.assertIsNotNone(calls[-1]['max_new'])

    def test_a_mark_the_model_puts_first_goes_to_the_word_before_it(self):
        class Marks(FakeGenerator):
            replies = [['»', 'Привет'], ['?', 'Да']]

            def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
                self.calls.append(dict(close=close))
                return Result(self.replies.pop(0) if self.replies else [], 'end')
        script = [(' א', .2), (',', .25), (' ב', .5), (',', .55), (' ג', .8)]
        processor = self.make(script, generator=Marks())
        for seconds in (1.1, 1.4):
            self.feed(processor, seconds)
        self.feed(processor, 2., final=True, reason='pause')
        self.finish(processor)
        self.assertEqual(self.publications()[-1]['current']['translation'], 'Привет? Да')

    def test_a_sentence_the_model_ends_early_starts_a_new_one_with_the_pair_as_context(self):
        script = [(' א', .2), (',', .25), (' ב', .5), (',', .55), (' ג', .8)]
        processor = self.make(script, generator=FakeGenerator(stops=['sentence']))
        for seconds in (1.1, 1.4):
            self.feed(processor, seconds)
        self.feed(processor, 2., final=True, reason='pause')
        self.finish(processor)
        calls = self.generator.calls
        self.assertEqual(calls[0]['forced'], '')
        self.assertEqual(calls[1]['pairs'][-1], ('א,', 'ru:א,.'))
        self.assertEqual(calls[1]['text'], 'ב, ג')
        self.assertEqual(self.publications()[-1]['current']['translation'], 'ru:א,. ru:ב, ru:ג')
        # a pause is not a sentence end: the last call keeps its stops and a cap on new words
        self.assertEqual((calls[-1]['close'], calls[-1]['upto'], calls[-1]['max_new']), (False, 2, 3))

    def test_wrong_weekday_in_new_words_is_replaced_with_the_cards_hebrew(self):
        class Days(FakeGenerator):
            def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
                self.calls.append(dict(close=close))
                return Result(['Запись', 'в', 'четверг.'] if close else [], 'end')
        script = [(' תור', .2), (' ביום', .5), (' שלישי', .9), ('.', 1.)]
        processor = self.make(script, generator=Days())
        self.feed(processor, 1.6, final=True, reason='pause')
        self.finish(processor)
        self.assertEqual(self.publications()[-1]['current']['translation'], 'Запись во вторник.')
        checks = [v for n, v in self.events if n == 'weekday_check']
        self.assertEqual([i['kind'] for c in checks for i in c['issues']], ['fixed'])

    def test_a_live_call_stops_before_a_number_the_hebrew_has_not_said(self):
        class Numbers(FakeGenerator):
            def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
                self.calls.append(dict(text=text, forced=forced, close=close))
                if close:
                    return Result(['Для', 'жилья', 'нажмите', '2.'][len(forced.split()):], 'end')
                return Result(['Для', 'жилья', 'нажмите', '2'][len(forced.split()):], 'end')
        script = [(' לביטוח', .2), (' דירה', .5), (' הקישו', .8), (' שתיים', 3.6), ('.', 3.7)]
        processor = self.make(script, deadline=1.5, generator=Numbers())
        for step in range(5, 36, 3):
            self.feed(processor, step / 10)
        shown = self.publications()[-1]['current']['translation']
        self.assertEqual(shown, 'Для жилья нажмите')          # the number is not guessed
        self.assertIn('number', [e['stop'] for n, e in self.events if n == 'append_chunk'])
        self.feed(processor, 4.6, final=True, reason='pause')
        self.finish(processor)
        self.assertEqual(self.publications()[-1]['current']['translation'], 'Для жилья нажмите 2.')

    def test_a_live_call_stops_before_a_day_the_hebrew_has_not_said(self):
        class Days(FakeGenerator):
            def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
                self.calls.append(dict(text=text, forced=forced, close=close))
                return Result(['Запись', 'на', 'сегодня'][len(forced.split()):], 'end')
        script = [(' אני', .2), (' רוצה', .5), (' תור', .8), (' ביום', 3.6), ('.', 3.7)]
        processor = self.make(script, deadline=1.5, generator=Days())
        for step in range(5, 30, 3):
            self.feed(processor, step / 10)
        self.assertEqual(self.publications()[-1]['current']['translation'], 'Запись на')
        self.assertIn('day', [e['stop'] for n, e in self.events if n == 'append_chunk'])

    def recheck(self, whole, direction_words=('Запись', 'на', 'сегодня.'), stop='end'):
        class Twice(FakeGenerator):
            def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
                self.calls.append(dict(text=text, forced=forced, close=close))
                return Result(list(direction_words), 'end') if len(self.calls) == 1 else Result(whole, stop)
        processor = self.make([(' תור', .2), (' ביום', .5), (' שלישי', .9), ('.', 1.)], generator=Twice())
        self.feed(processor, 1.6, final=True, reason='pause')
        self.finish(processor)
        return self.publications()[-1]['current']['translation']

    def rechecks(self):
        return [v for n, v in self.events if n == 'close_recheck']

    def test_a_closed_card_with_a_wrong_day_gets_the_changed_words_after_the_shown_ones(self):
        shown = self.recheck(['Запись', 'во', 'вторник.'])
        self.assertEqual(shown, 'Запись на сегодня. (Уточнение: Запись во вторник.)')
        self.assertEqual(self.generator.calls[1]['forced'], '')   # the whole sentence, nothing forced
        self.assertEqual([v['better'] for v in self.rechecks()], [True])

    def test_a_whole_translation_that_still_does_not_match_is_not_shown(self):
        self.assertEqual(self.recheck(['Запись', 'на', 'завтра.']), 'Запись на сегодня.')
        self.assertEqual(self.rechecks()[0]['rejected'], 'mismatch')

    def test_a_whole_translation_cut_short_is_not_shown(self):
        for stop in ('cap', 'cancel', 'sentence'):
            self.events.clear()
            self.assertEqual(self.recheck(['Запись', 'во', 'вторник.'], stop=stop), 'Запись на сегодня.', stop)
            self.assertEqual(self.rechecks()[0]['rejected'], 'cut')

    def test_a_whole_translation_much_shorter_than_the_shown_one_is_not_shown(self):
        words = ('Я', 'хочу', 'записаться', 'на', 'сегодня,', 'если', 'это', 'возможно.')
        self.assertNotIn('Уточнение', self.recheck(['Во', 'вторник.'], words))
        self.assertEqual(self.rechecks()[0]['rejected'], 'cut')

    def test_a_card_that_matches_its_hebrew_is_not_translated_again(self):
        self.recheck([], ('Запись', 'во', 'вторник.'))
        self.assertEqual(len(self.generator.calls), 1)

    def test_the_recheck_can_be_switched_off(self):
        with mock.patch.dict(os.environ, HEBREW_LIVE_CLOSE_RECHECK='0'):
            self.assertEqual(self.recheck(['Запись', 'во', 'вторник.']), 'Запись на сегодня.')

    def test_a_sentence_that_ended_before_the_card_closed_is_checked_too(self):
        class Scripted(FakeGenerator):
            def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
                self.calls.append(dict(text=text, forced=forced, close=close, pairs=pairs))
                if len(self.calls) == 1:
                    return Result(['Запись', 'на', '17'], 'sentence', '.')
                if close:
                    return Result(['Запись', 'без', 'числа.'], 'end')
                return Result(['ru:' + w for w in text.split()], 'end')
        script = [(' תור', .2), (',', .25), (' ועוד', .5), (',', .55), (' מחר', .8)]
        processor = self.make(script, generator=Scripted())
        with mock.patch.dict(os.environ, HEBREW_LIVE_NUMBER_WAIT='0'):
            for seconds in (1.1, 1.4):
                self.feed(processor, seconds)
            self.feed(processor, 2., final=True, reason='pause')
            self.finish(processor)
        shown = self.publications()[-1]['current']['translation']
        self.assertEqual([v['stage'] for v in self.rechecks() if v['better']], ['split'])
        self.assertTrue(shown.startswith('Запись на 17. (Уточнение: Запись без числа.) '), shown)
        # the corrected sentence is the context of the next call
        self.assertEqual(self.generator.calls[2]['pairs'][-1], ('תור,', 'Запись без числа.'))

    def sentence_then_rest(self, first, script, rest=None):
        class Scripted(FakeGenerator):
            def generate(self, text, forced, pairs, direction, upto=None, close=False, max_new=None):
                self.calls.append(dict(text=text, forced=forced, close=close, pairs=pairs))
                if len(self.calls) == 1:
                    return Result(list(first), 'sentence', '.')
                return Result(list(rest or ['дальше']), 'end')
        processor = self.make(script, generator=Scripted())
        for seconds in (1.1, 1.4):
            self.feed(processor, seconds)
        self.feed(processor, 2., final=True, reason='pause')
        self.finish(processor)
        return self.publications()[-1]['current']['translation']

    def test_a_number_the_ended_sentence_already_has_stays_with_it(self):
        script = [(' הקישו', .2), (',', .25), (' 2', .5), (',', .55), (' לעזרה', .8)]
        shown = self.sentence_then_rest(['нажмите', '2'], script)
        self.assertEqual(shown, 'нажмите 2. дальше')
        self.assertEqual(self.rechecks(), [])   # no false «extra 2»
        self.assertEqual(self.generator.calls[1]['pairs'][-1], ('הקישו, 2,', 'нажмите 2.'))
        self.assertEqual(self.generator.calls[1]['text'], 'לעזרה')

    def test_a_number_no_near_word_says_does_not_move_the_end_of_the_sentence(self):
        script = [(' הקישו', .2), (',', .25), (' 2', .5), (',', .55), (' לעזרה', .8)]
        with mock.patch.dict(os.environ, HEBREW_LIVE_NUMBER_WAIT='0'):
            self.sentence_then_rest(['нажмите', '7'], script)
        self.assertEqual([v['issues'] for v in self.rechecks() if v['stage'] == 'split'], [['extra 7']])
        self.assertEqual(self.generator.calls[-1]['text'], '2, לעזרה')

    def test_an_ended_sentence_without_a_number_takes_no_more_words(self):
        script = [(' שלום', .2), (',', .25), (' 2', .5), (',', .55), (' לעזרה', .8)]
        self.sentence_then_rest(['привет'], script, ['2,', 'дальше'])
        self.assertEqual(self.generator.calls[1]['text'], '2, לעזרה')

    def test_the_note_has_the_changed_words_only(self):
        from hebrew_live.append_live import changed_piece
        shown = 'Мы работаем с понедельника по четверг с 8 утра, приходите в любое время, будем рады вас видеть.'
        again = 'Мы работаем с воскресенья по четверг с 8 утра, приходите в любое время, будем рады вас видеть.'
        self.assertEqual(changed_piece(shown, again), '… работаем с воскресенья по четверг …')
        self.assertEqual(changed_piece(shown, shown), '')
        # a rewording that keeps the number is left out, also when the number is in the changed words
        self.assertEqual(changed_piece('Во вторник мы открыты, а первое посещение стоит дорого.',
                                       'В среду мы открыты, а первый приём стоит дорого.'), 'В среду мы открыты, …')
        # the beginning of the next sentence is not a change; a number the shown one lost is
        self.assertEqual(changed_piece('с понедельника по четверг.', 'с воскресенья по четверг. Стоимость первого посещения'),
                         'с воскресенья по четверг. …')
        self.assertEqual(changed_piece('Приходите завтра', 'Приходите завтра в 10'), 'Приходите завтра в 10')
        # a rewording without a number or a day is not a correction
        self.assertEqual(changed_piece('Мы рады вас видеть', 'Мы очень рады вас принять'), '')

    def test_the_days_of_a_note_do_not_count_in_the_next_weekday_check(self):
        from hebrew_live.append_live import Card
        processor = self.make([])
        card = Card(1, Settings(direction='he-ru'), 0)
        card.out = ['Запись', 'в', 'четверг.']
        processor._note(card, 'во вторник', Settings(direction='he-ru'))
        self.assertEqual(processor._plain(card), 'Запись в четверг.')
        self.assertEqual(card.base_out, len(card.out))


class WordsCutShort(unittest.TestCase):
    """The last word of a translation cut at its limit is not shown unfinished."""
    def generate(self, close, pieces, **kw):
        import mlx.core as mx
        from hebrew_live.clause_mt import ClauseGenerator
        EOS = len(pieces)
        step = [0]

        class Tokenizer:
            eos_token_ids = [EOS]
            def decode(self, tokens):
                return ''.join(pieces[t] for t in tokens)

        class Model:
            def __call__(self, ids, cache=None):
                row = np.zeros((1, 1, EOS + 1), np.float32)
                row[0, 0, min(step[0], EOS)] = 1.
                step[0] += 1
                return mx.array(row)
        generator = ClauseGenerator(SimpleNamespace(model=Model(), tokenizer=Tokenizer()))
        generator._capture = lambda: SimpleNamespace(active=False, rows=[], forward=lambda: None, last=lambda: None)
        generator.prompt = lambda *a: ([1], [(0, 0)], 1)
        with mock.patch('mlx_lm.models.cache.make_prompt_cache', return_value=None):
            return generator.generate('א', '', (), 'he-ru', close=close, **kw)

    def test_the_last_call_of_a_card_drops_the_unfinished_word(self):
        # one Hebrew word: the limit is 6 words, the eighth is the first over it
        pieces = [f' слово{i}' for i in range(7)] + [' K', 'ysho', ' Five']
        result = self.generate(True, pieces)
        self.assertEqual((result.stop, result.words), ('cap', [f'слово{i}' for i in range(7)]))

    def test_a_finished_translation_keeps_its_last_word(self):
        result = self.generate(True, [' на', 'жмите', ' 5', '.'])
        self.assertEqual((result.stop, result.words), ('end', ['нажмите', '5.']))


class AllAudio(unittest.TestCase):
    """Audio between speech segments ('background') and the audio that leads a segment."""
    setUp, make, feed, publications, finish = (Append.setUp, Append.make, Append.feed, Append.publications, Append.finish)

    def background(self, processor, start, end, lead=None):
        audio = np.zeros(int((end - start) * RATE), np.float32)
        processor.process(Fragment(0, 1, audio, 0, time.monotonic(), False, Settings(publication='draft'), end, 0,
                                   'background', lead))
        processor.drain_mt()

    def test_words_the_vad_took_for_no_speech_are_shown_and_end_after_a_quiet(self):
        processor = self.make([(' שלום', .5), (' לך', .8)], deadline=100.)
        self.background(processor, 0., 2.)
        self.assertEqual([c.closing for c in processor.cards], [False])
        self.background(processor, 0., 3.6)
        processor.drain_mt()
        self.finish(processor)
        closed = [p for p in self.publications() if p['stage'] == 'closed']
        self.assertEqual([p['current']['source'] for p in closed], ['שלום לך'])

    def test_background_audio_is_fed_once_and_only_what_was_not_fed(self):
        processor = self.make([], deadline=100.)
        self.background(processor, 0., 1.)
        self.background(processor, 0., 1.6)
        self.assertEqual(processor.stream_samples, int(1.6 * RATE))
        self.finish(processor)

    def test_the_lead_of_a_segment_is_fed_instead_of_silence(self):
        processor = self.make([], deadline=100.)
        self.feed(processor, 1.)
        audio = np.ones(int(.5 * RATE), np.float32)
        lead = np.ones(int(1.5 * RATE), np.float32)
        processor.process(Fragment(2, 1, audio, 0, time.monotonic(), False, Settings(publication='draft'), 3., 0, '', lead))
        self.assertEqual(processor.stream_samples, 3 * RATE)
        self.finish(processor)


class Router(unittest.TestCase):
    def make(self, append=None):
        from hebrew_live.append_live import DraftRouter
        engine = SimpleNamespace(independent_mt=False)
        log = SimpleNamespace(event=lambda *a, **k: None)
        return DraftRouter(engine, queue.Queue(), log, threading.Event(), append=append)

    def test_without_the_streaming_model_the_retranslating_screen_is_used(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {'HEBREW_LIVE_HYBRID_MODEL': '/nonexistent'}):
            router = self.make()
        self.assertIsNone(router.append)
        self.assertIs(router.active, router.retranslation)

    def test_hebrew_goes_to_the_append_screen_and_other_languages_do_not(self):
        seen = []
        append = SimpleNamespace(counter=5, export_counter=2, mt_counter=7, async_mt=False, _mt_outstanding=0,
                                 process=lambda f: seen.append(('append', f.settings.direction)),
                                 flush=lambda reason: seen.append(('flush', reason)))
        router = self.make(append)
        router.retranslation.process = lambda f: seen.append(('retranslation', f.settings.direction))
        router.process(SimpleNamespace(settings=Settings(direction='he-ru')))
        router.process(SimpleNamespace(settings=Settings(direction='ru-he')))
        self.assertEqual(seen, [('append', 'he-ru'), ('flush', 'direction'), ('retranslation', 'ru-he')])
        self.assertEqual(router.counter, 5)   # group numbers go on from the append screen's

    def test_only_the_streaming_recognizer_hears_background_audio(self):
        router = self.make(SimpleNamespace())
        self.assertTrue(router.hears_background(Settings(direction='he-ru')))
        self.assertFalse(router.hears_background(Settings(direction='ru-he')))
        with mock.patch.dict(os.environ, {'HEBREW_LIVE_HYBRID_MODEL': '/nonexistent'}):
            self.assertFalse(self.make().hears_background(Settings(direction='he-ru')))


if __name__ == '__main__':
    unittest.main()
