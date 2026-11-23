import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from hebrew_live.browser_ui import BrowserUI, ui_log_entry
from hebrew_live import session_summary


class UiLogEntry(unittest.TestCase):
    def test_render_gets_screen_lag_from_the_echoed_publication_time(self):
        name, fields = ui_log_entry(dict(type='render', group='0:1', revision=3, shown='live', complete=False,
                                         source='שלום', translation='Привет', source_changed=True,
                                         translation_changed=True, erased_translation=0, emitted_at=100.,
                                         audio_lag=.5, age_ms=20, view='cards'), 100.3, {'0:1': 2})
        self.assertEqual(name, 'ui_render')
        self.assertEqual(fields['part'], 2)
        self.assertAlmostEqual(fields['publish_to_screen'], .28)
        self.assertAlmostEqual(fields['screen_lag'], .78)

    def test_render_without_publication_time_has_no_lag(self):
        _, fields = ui_log_entry(dict(type='render', group='0:1'), 5., {})
        self.assertNotIn('screen_lag', fields)
        self.assertEqual(fields['shown'], 'none')

    def test_input_records_keep_only_known_fields(self):
        self.assertEqual(ui_log_entry(dict(type='scroll', top=10, height=900, client_height=500, secret='x'), 1., {}),
                         ('ui_scroll', dict(top=10, height=900, client_height=500, age=0.)))
        self.assertIsNone(ui_log_entry(dict(type='unknown'), 1., {}))
        self.assertIsNone(ui_log_entry('render', 1., {}))
        self.assertIsNone(ui_log_entry(dict(type='render', group=5), 1., {}))


class UiLogAction(unittest.TestCase):
    def test_a_batch_reaches_the_diagnostics(self):
        with BrowserUI(open_browser=False) as ui:
            received = []
            ui.on_preview_seen = lambda event, **data: received.append((event, data))
            ui.state['groups'] = [dict(id='0:3000001', part=1)]
            def send(body):
                request = urllib.request.Request(ui.url + 'action', data=json.dumps(body).encode(),
                    headers={'Origin': 'http://' + ui.host, 'Content-Type': 'application/json'})
                return urllib.request.urlopen(request)
            items = [dict(type='render', group='0:3000001', source='ש' * 3000, translation='п' * 3000,
                          emitted_at=time.monotonic() - .1, audio_lag=.4)] * 3 + [dict(type='click', target='button')]
            with send(dict(action='ui_log', items=items)) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual([event for event, _ in received], ['ui_render'] * 3 + ['ui_click'])
            self.assertGreaterEqual(received[0][1]['screen_lag'], .5)
            # Only a log batch may be larger than a single report.
            with self.assertRaises(urllib.error.HTTPError):
                send(dict(action='ui_ticker', group='0:3000001', source='live', black='x' * 9000, grey=''))
            with self.assertRaises(urllib.error.HTTPError):
                send(dict(action='ui_log', items=[{}] * 401))
            ui.finished_seen.set()


class Summary(unittest.TestCase):
    def test_counts_lags_rewrites_and_runs(self):
        events = [
            dict(event='device', elapsed=0, input='phone'),
            dict(event='live_publication', elapsed=1, segment=1, stage='open', audio_lag=.5,
                 current=dict(source='שלום אני', translation='Привет. Я')),
            dict(event='live_publication', elapsed=2, segment=1, stage='open', audio_lag=.7,
                 current=dict(source='שלום אני רוצה', translation='Здравствуйте. Я хочу')),
            dict(event='live_publication', elapsed=3, segment=1, stage='closed', audio_lag=.9,
                 current=dict(source='שלום אני רוצה...', translation='Здравствуйте. Я хочу')),
            dict(event='ui_render', elapsed=1.1, group='0:1', source='שלום', translation='', complete=False,
                 source_changed=True, translation_changed=False, screen_lag=.6),
            dict(event='ui_render', elapsed=1.2, group='0:1', source='שלום', translation='Привет', complete=False,
                 source_changed=False, translation_changed=True, screen_lag=.9),
            dict(event='mt_interrupted', elapsed=2), dict(event='mt_requested', elapsed=2),
            dict(event='worker_memory', elapsed=3, peak_mlx=10, peak_rss=5),
        ]
        for event in events:
            event['_part'] = '001'
        result = session_summary.summarize(events)
        self.assertEqual(result['input'], 'phone')
        self.assertEqual(result['screen']['hebrew_lag']['p50'], .6)
        self.assertEqual(result['screen']['translation_lag']['p50'], .9)
        moves = result['backend']['translation_moves']
        self.assertEqual(moves['finished_sentences_rewritten'], 1)   # "Привет." became "Здравствуйте."
        self.assertEqual(moves['erased_words'], 2)   # both words moved from their place
        self.assertEqual(result['backend']['hebrew_moves']['erased_words'], 0)  # a trailing "..." is not an erasure
        self.assertEqual(result['translation_runs']['interrupted'], 1)
        self.assertEqual(result['memory'], dict(peak_mlx_bytes=10, peak_rss_bytes=5))

    def test_writes_the_file_next_to_the_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '001-he-ru.diagnostics.jsonl'
            path.write_text(json.dumps(dict(event='mt_requested', elapsed=1)) + '\nnot json\n')
            summary = session_summary.write(folder)
            self.assertEqual(summary['translation_runs']['requested'], 1)
            self.assertEqual(json.loads((Path(folder) / 'summary.json').read_text())['duration_seconds'], 1)


if __name__ == '__main__':
    unittest.main()
