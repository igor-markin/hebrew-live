import queue
import threading
import time
import unittest
from types import SimpleNamespace

import numpy as np

from hebrew_live.append_live import AppendProcessor
from hebrew_live.cli import Fragment
from hebrew_live.session_summary import summarize
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


class Append(unittest.TestCase):
    def setUp(self):
        self.events, self.calls = [], []
        self.updates = queue.Queue()
        self.log = SimpleNamespace(event=lambda name, **v: self.events.append((name, v)))

    def make(self, script, span=2., translate=None):
        recognizer = FakeRecognizer(script)
        recognizer.create_stream = lambda: feeding(recognizer)

        def default(text, context=()):
            self.calls.append((text, context))
            yield 'ru(' + text + ')', 'stop'
        engine = SimpleNamespace(translate=translate or default)
        return AppendProcessor(engine, self.updates, self.log, threading.Event(), recognizer=recognizer, span=span)

    def feed(self, processor, seconds, final=False, reason=''):
        audio = np.zeros(int(seconds * RATE), np.float32)
        now = time.monotonic()
        processor.process(Fragment(1, 1, audio, 0, now, final, Settings(publication='draft'), seconds, 0, reason))

    def publications(self):
        return [v for kind, _, v in list(self.updates.queue) if kind == 'live_publication']

    def test_text_is_only_appended_and_chunks_end_at_commas(self):
        script = [(' שלום', .2), (',', .3), (' אני', .6), (' רוצה', .9), (' לק', 1.2), ('בוע', 1.3), (' תור', 1.6), ('.', 1.7)]
        processor = self.make(script)
        for seconds in (1., 1.5, 2., 2.5):
            self.feed(processor, seconds)
        self.feed(processor, 2.6, final=True, reason='pause')
        processor.drain_mt()
        processor.shutdown_mt()
        self.assertEqual([text for text, _ in self.calls], ['שלום,', 'אני רוצה לקבוע תור.'])
        self.assertEqual(self.calls[1][1], (('שלום,', 'ru(שלום,)'),))  # continues the shown chunk
        shown = self.publications()
        for before, after in zip(shown, shown[1:]):
            if before['current']['source'] and after['start'] == before['start']:
                self.assertTrue(after['current']['source'].startswith(before['current']['source']))
                self.assertTrue(after['current']['translation'].startswith(before['current']['translation']))
        self.assertEqual(shown[-1]['stage'], 'closed')
        self.assertEqual(shown[-1]['current']['source'], 'שלום, אני רוצה לקבוע תור.')

    def test_speech_without_commas_is_cut_after_the_span(self):
        script = [(' מילה', t / 10) for t in range(2, 40, 3)]
        processor = self.make(script, span=1.)
        for step in range(5, 46, 3):
            self.feed(processor, step / 10)
        processor.drain_mt()
        processor.shutdown_mt()
        self.assertGreaterEqual(len(self.calls), 2)
        self.assertTrue(all(len(text.split()) <= 5 for text, _ in self.calls))

    def test_runaway_translation_is_cut_and_not_used_as_context(self):
        def runaway(text, context=()):
            self.calls.append((text, context))
            for _ in range(200):
                yield '0', None
        processor = self.make([(' אחת', .2), (',', .3), (' שתיים', .6), (',', .7)], translate=runaway)
        self.feed(processor, 1.5, final=True, reason='pause')
        processor.drain_mt()
        processor.shutdown_mt()
        self.assertEqual(self.calls[1][1], ())
        chunks = [v for n, v in self.events if n == 'append_chunk']
        self.assertTrue(all(chunk['capped'] for chunk in chunks))
        summary = summarize([dict(e, event=n, _part='001') for n, e in self.events])
        self.assertEqual(summary['append']['capped'], 2)
        self.assertEqual(summary['append']['translation_word_lag']['count'], 2)


if __name__ == '__main__':
    unittest.main()
