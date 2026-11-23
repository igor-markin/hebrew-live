import os,queue,threading,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from hebrew_live.cli import Fragment
from hebrew_live.stream import Settings
from hebrew_live.retranslation import RetranslationProcessor
from hebrew_live.display import TranslationScreen
from hebrew_live import session_summary, streaming_asr


class FakeStreaming:
    def __init__(self, texts):
        self.texts, self.calls = texts, []

    def text(self, key, audio):
        self.calls.append((key, len(audio)))
        return self.texts.get(len(audio) // 16000, '')


class Hybrid(unittest.TestCase):
    def setUp(self):
        self.events, self.whisper, self.mt = [], [], []
        self.e = SimpleNamespace(recognize=self.recognize, translate=self.translate)
        self.q = queue.Queue()
        part = SimpleNamespace(text=lambda *a: None)
        self.log = SimpleNamespace(event=lambda name, **v: self.events.append((name, v)), parts={1: part})
        self.p = RetranslationProcessor(self.e, self.q, self.log, threading.Event())
        self.audio = np.zeros(400000, np.float32)
        self.settings = Settings(publication='draft')

    def recognize(self, audio, *args, **kw):
        self.whisper.append((len(audio), kw.get('preliminary')))
        self.e.recognition_status = 'accepted'
        return 'שלום אני רוצה לקבוע תור.'

    def translate(self, text):
        self.mt.append(text)
        yield 'ru:' + text, 'stop'

    def f(self, end, final=False, reason=''):
        return Fragment(1, 1, self.audio[:end].copy(), 0, time.monotonic(), final, self.settings, end / 16000, 0, reason)

    def test_drafts_come_from_the_stream_and_the_closing_decode_from_whisper(self):
        self.p.streaming = FakeStreaming({2: 'שלום אני', 3: 'שלום אני רוצה'})
        self.p.process(self.f(32000))
        self.p.process(self.f(48000))
        self.assertEqual(self.whisper, [])
        self.p.process(self.f(56000, final=True, reason='pause'))
        self.assertEqual(self.whisper, [(56000, False)])
        asr = [v for n, v in self.events if n == 'live_asr']
        self.assertEqual([v.get('draft_engine') for v in asr], ['streaming', 'streaming', None])
        closed = [v for k, _, v in self.q.queue if k == 'live_publication' and v['stage'] == 'closed']
        self.assertEqual(closed[-1]['current']['source'], 'שלום אני רוצה לקבוע תור.')

    def test_newer_hebrew_is_shown_before_its_translation(self):
        self.p.streaming = FakeStreaming({2: 'שלום אני', 3: 'שלום אני רוצה'})
        self.p.process(self.f(32000))
        self.p.process(self.f(48000))
        live = [v for k, _, v in self.q.queue if k == 'live_source']
        self.assertEqual([v['source'] for v in live], ['שלום אני רוצה'])
        self.assertIn('emitted_at', live[0])
        self.assertIn('live_source', [n for n, _ in self.events])

    def test_off_without_the_flag_or_the_model(self):
        with patch.dict(os.environ, {'HEBREW_LIVE_HYBRID': '0'}):
            self.assertIsNone(streaming_asr.load(self.log))
        with patch.dict(os.environ, {'HEBREW_LIVE_HYBRID': '1', 'HEBREW_LIVE_HYBRID_MODEL': '/nonexistent'}):
            self.assertIsNone(streaming_asr.load(self.log))
        self.assertEqual(self.events[-1][0], 'hybrid_unavailable')


class Screen(unittest.TestCase):
    def test_live_source_survives_an_older_translation_until_the_group_closes(self):
        screen = TranslationScreen(native_bidi=True)
        open_value = dict(current=dict(source='שלום', translation='Привет'), history=[], stage='open')
        screen.update('live_publication', 7, open_value)
        screen.update('live_source', 7, dict(source='שלום אני רוצה'))
        screen.update('live_publication', 7, dict(open_value, current=dict(source='שלום אני', translation='Привет, я')))
        self.assertEqual(screen.groups[7]['source_live']['source'], 'שלום אני רוצה')
        screen.update('live_publication', 7, dict(open_value, stage='closed'))
        self.assertNotIn('source_live', screen.groups[7])
        screen.update('live_source', 7, dict(source='x'))
        self.assertNotIn('source_live', screen.groups[7])


class Summary(unittest.TestCase):
    def test_closing_change_against_the_last_draft(self):
        events = [
            dict(event='live_publication', elapsed=1, segment=1, stage='open', audio_lag=.5,
                 current=dict(source='שלום אני', translation='Привет')),
            dict(event='live_source', elapsed=1.5, segment=1, source='שלום אני רוצה', audio_lag=.3),
            dict(event='live_publication', elapsed=1.8, segment=1, stage='open', audio_lag=.9,
                 current=dict(source='שלום אני', translation='Привет, я')),
            dict(event='live_publication', elapsed=3, segment=1, stage='closed', audio_lag=.9,
                 current=dict(source='שלום אני רוצה לקבוע', translation='Здравствуйте')),
            dict(event='live_asr', elapsed=1, seconds=.02, draft_engine='streaming'),
            dict(event='live_asr', elapsed=3, seconds=.5),
        ]
        for event in events:
            event['_part'] = '001'
        backend = session_summary.summarize(events)['backend']
        self.assertEqual(backend['closing_vs_last_draft'], dict(groups=1, changed=0, erased_words=0, draft_words=3))
        self.assertEqual(backend['hebrew_moves']['erased_words'], 0)  # the older publication is not on screen
        self.assertEqual(backend['whisper_total_seconds'], .5)
        self.assertEqual(backend['streaming_draft_seconds']['count'], 1)


if __name__ == '__main__':
    unittest.main()
