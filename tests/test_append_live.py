import queue
import threading
import time
import unittest
from types import SimpleNamespace

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


if __name__ == '__main__':
    unittest.main()
