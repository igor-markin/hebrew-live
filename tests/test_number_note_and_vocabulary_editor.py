"""A closed phrase notes figures its translation lost or added; the window edits the owner's
vocabulary and the running engine picks the change up before its next translation."""
import json
import os
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from hebrew_live import vocabulary
from hebrew_live.browser_ui import BrowserUI
from hebrew_live.cli import Engine, Fragment
from hebrew_live.retranslation import RetranslationProcessor
from hebrew_live.stream import Settings
from hebrew_live.vocabulary import Entry, Watched


class NumberNoteTests(unittest.TestCase):
    def setUp(self):
        self.events = []; self.results = []
        self.engine = SimpleNamespace(recognize=self.recognize, translate=self.translate)
        self.updates = queue.Queue()
        part = SimpleNamespace(text=lambda *args: None)
        log = SimpleNamespace(event=lambda name, **values: self.events.append((name, values)), parts={1: part})
        self.processor = RetranslationProcessor(self.engine, self.updates, log, threading.Event())
        self.settings = Settings(publication='draft', direction='he-ru')
        self.audio = np.zeros(200000, dtype=np.float32)

    def recognize(self, *args, **kwargs):
        text, self.target = self.results.pop(0); self.engine.recognition_status = 'accepted'; return text

    def translate(self, text):
        yield self.target, 'stop'

    def say(self, text, target, end, final=False):
        self.results.append((text, target))
        self.processor.process(Fragment(1, 1, self.audio[:end].copy(), 0, time.monotonic(), final, self.settings,
                                        end / 16000, 0, 'silence' if final else ''))

    def publications(self):
        return [value for kind, _, value in self.updates.queue if kind == 'live_publication']

    def test_closed_phrase_notes_the_figures_that_differ_and_an_open_one_never(self):
        self.say('התור בשעה 10 בבוקר', 'Очередь в 11 утра', 16000)
        self.say('התור בשעה 10 בבוקר', 'Очередь в 11 утра', 32000)
        self.assertTrue(all('numbers' not in value for value in self.publications()))   # still growing
        self.say('התור בשעה 10 בבוקר', 'unused', 48000, final=True)
        closed = self.publications()[-1]
        self.assertEqual(closed['stage'], 'closed')
        self.assertEqual(closed['numbers'], [dict(kind='missing', number='10'), dict(kind='extra', number='11')])
        self.assertIsNone(closed['issue'])                       # a note, never a failed phrase
        (name, logged), = [event for event in self.events if event[0] == 'number_mismatch']
        self.assertEqual(set(logged), {'part', 'segment', 'stage', 'issues'})   # figures only, no speech text
        self.assertEqual(logged['issues'], closed['numbers'])

    def test_matching_figures_leave_an_empty_list_and_no_event(self):
        self.say('התור בשעה 10 בבוקר', 'Очередь в 10 утра', 16000)
        self.say('התור בשעה 10 בבוקר', 'unused', 32000, final=True)
        self.assertEqual(self.publications()[-1]['numbers'], [])
        self.assertFalse([event for event in self.events if event[0] == 'number_mismatch'])

    def test_frozen_sentences_count_with_the_tail(self):
        self.processor.freeze_enabled = True
        self.say('ואחר כך עוד אחד', 'А потом ещё одно', 16000)
        self.processor.frozen_source, self.processor.frozen_target = ['שלחו 5 מכתבים.'], ['Отправили 5 писем.']
        self.say('ואחר כך עוד אחד', 'unused', 32000, final=True)
        closed = self.publications()[-1]
        self.assertIn('5', closed['current']['source']); self.assertEqual(closed['numbers'], [])

    def test_a_figure_in_a_frozen_sentence_is_compared_too(self):
        self.processor.freeze_enabled = True
        self.say('ואחר כך עוד אחד', 'А потом ещё одно', 16000)
        self.processor.frozen_source, self.processor.frozen_target = ['שלחו 5 מכתבים.'], ['Отправили 6 писем.']
        self.say('ואחר כך עוד אחד', 'unused', 32000, final=True)
        self.assertEqual(self.publications()[-1]['numbers'], [dict(kind='missing', number='5'), dict(kind='extra', number='6')])

    def test_the_check_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {'HEBREW_LIVE_NUMBER_CHECK': '0'}):
            self.say('בשעה 10', 'В 11', 16000); self.say('בשעה 10', 'unused', 32000, final=True)
        self.assertEqual(self.publications()[-1]['numbers'], [])


class WatchedVocabularyTests(unittest.TestCase):
    def test_a_saved_change_is_read_again_and_nothing_else_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'vocabulary.json'; watched = Watched(target)
            self.assertEqual(watched.current(), [])
            vocabulary.save([Entry('חיפה', 'Хайфа')], target)
            self.assertEqual(watched.current(), [Entry('חיפה', 'Хайфа')])
            with mock.patch.object(vocabulary, 'load', side_effect=AssertionError('read again')):
                watched.current()                                    # unchanged file: one stat, no read
            vocabulary.save([Entry('חיפה', 'Хайфа'), Entry('תכנית', 'программа')], target)
            self.assertEqual(len(watched.current()), 2)
            target.unlink(); self.assertEqual(watched.current(), [])

    def test_a_running_engine_translates_with_the_new_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'vocabulary.json'
            engine = object.__new__(Engine)
            engine.model = object(); engine.direction = 'he-ru'; engine.topic = 'none'; engine.translation_context = []
            engine.tokenizer = SimpleNamespace(encode=lambda text, add_special_tokens=False: [1, 2, 3])
            events = []; engine.log = SimpleNamespace(event=lambda name, **values: events.append((name, values)))
            engine.vocabulary_file = Watched(target); engine.vocabulary = engine.vocabulary_file.current()
            seen = []
            sample_utils = types.ModuleType('mlx_lm.sample_utils'); sample_utils.make_sampler = lambda **_: object()
            with mock.patch.dict(sys.modules, {'mlx_lm.sample_utils': sample_utils}), \
                    mock.patch('hebrew_live.mt_generate.generate', lambda *a, **k: iter([('ok', 'stop')])), \
                    mock.patch('hebrew_live.translation.prompt', lambda *a, **k: (seen.append(k['terms']), [1])[1]):
                list(engine.translate('בחיפה אמרו לחכות'))
                vocabulary.save([Entry('חיפה', 'Хайфа')], target)
                list(engine.translate('בחיפה אמרו לחכות'))
            self.assertEqual(seen, [[], [('חיפה', 'Хайфа')]])
            self.assertIn(('vocabulary_loaded', dict(entries=1, reason='changed')), events)
            self.assertEqual([values['terms'] for name, values in events if name == 'mt_generation'], [0, 1])


def post(ui, payload):
    request = urllib.request.Request(ui.url + 'action', data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json', 'Origin': 'http://' + ui.host})
    try:
        with urllib.request.urlopen(request) as response: return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b'{}')


class VocabularyEditorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.home = Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {'HEBREW_LIVE_HOME': tmp.name}); patcher.start(); self.addCleanup(patcher.stop)
        self.ui = BrowserUI(open_browser=False).__enter__()
        def close(): self.ui.finished_seen.set(); self.ui.__exit__(None, None, None)
        self.addCleanup(close)

    def listed(self):
        with urllib.request.urlopen(self.ui.url + 'vocabulary') as response: return json.load(response)

    def test_add_edit_replace_and_delete(self):
        self.assertEqual(self.listed()['entries'], [])
        status, body = post(self.ui, {'action': 'vocabulary_set', 'value': {'he': ' חיפה ', 'ru': 'Хайфа'}})
        self.assertEqual((status, body['entries']), (200, [dict(he='חיפה', ru='Хайфа', en='')]))
        post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'תכנית', 'en': 'programme'}})
        status, body = post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'חיפה', 'ru': 'Хайфа', 'en': 'Haifa'}})
        self.assertEqual([entry['he'] for entry in body['entries']], ['חיפה', 'תכנית'])   # a duplicate replaces
        self.assertEqual(body['entries'][0]['en'], 'Haifa')
        status, body = post(self.ui, {'action': 'vocabulary_set', 'previous': 'תכנית',
                                      'value': {'he': 'תוכנית', 'en': 'programme'}})
        self.assertEqual([entry['he'] for entry in body['entries']], ['חיפה', 'תוכנית'])   # renamed in place of the old
        status, body = post(self.ui, {'action': 'vocabulary_delete', 'he': 'חיפה'})
        self.assertEqual([entry['he'] for entry in body['entries']], ['תוכנית'])
        self.assertEqual(vocabulary.load(self.home / 'vocabulary.json'), [Entry('תוכנית', '', 'programme')])

    def test_an_edit_keeps_the_place_and_takes_over_a_spelling_already_listed(self):
        for he in ('קופת חולים כללית', 'קופת חולים', 'מכבי'):
            post(self.ui, {'action': 'vocabulary_set', 'value': {'he': he, 'ru': he}})
        status, body = post(self.ui, {'action': 'vocabulary_set', 'previous': 'קופת חולים',
                                      'value': {'he': 'קופת חולים', 'ru': 'больничная касса'}})
        self.assertEqual([(entry['he'], entry['ru']) for entry in body['entries']][1], ('קופת חולים', 'больничная касса'))
        status, body = post(self.ui, {'action': 'vocabulary_set', 'previous': 'מכבי', 'value': {'he': 'קופת חולים', 'ru': 'касса'}})
        self.assertEqual([(entry['he'], entry['ru']) for entry in body['entries']],
                         [('קופת חולים', 'касса'), ('קופת חולים כללית', 'קופת חולים כללית')])

    def test_bad_entries_are_refused_and_change_nothing(self):
        post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'חיפה', 'ru': 'Хайфа'}})
        before = (self.home / 'vocabulary.json').read_bytes()
        for value, code in (({'he': '  ', 'ru': 'x'}, 'empty_hebrew'), ({'he': 'Haifa', 'ru': 'x'}, 'not_hebrew'),
                            ({'he': 'חיפה'}, 'no_translation'), ({'he': 'א' * 61, 'ru': 'x'}, 'too_long'),
                            ({'he': 'חיפה', 'ru': 'x' * 121}, 'too_long'), ({'he': 'חיפה', 'ru': 1}, 'invalid'),
                            ({'he': 'חיפה', 'ru': 'x', 'de': 'y'}, 'invalid'), ('חיפה', 'invalid')):
            self.assertEqual(post(self.ui, {'action': 'vocabulary_set', 'value': value}), (400, {'error': code}), value)
        self.assertEqual(post(self.ui, {'action': 'vocabulary_delete', 'he': ''})[0], 400)
        self.assertEqual((self.home / 'vocabulary.json').read_bytes(), before)

    def test_a_list_that_cannot_be_read_is_never_overwritten(self):
        (self.home / 'vocabulary.json').write_text('{"entries": [', encoding='utf8')
        self.assertTrue(self.listed()['damaged'])
        self.assertEqual(post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'חיפה', 'ru': 'Хайфа'}}),
                         (409, {'error': 'damaged'}))
        self.assertEqual((self.home / 'vocabulary.json').read_text(encoding='utf8'), '{"entries": [')

    def test_the_list_has_a_size_limit(self):
        with mock.patch('hebrew_live.browser_ui.VOCABULARY_LIMIT', 2):
            post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'אחת', 'ru': 'один'}})
            post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'שתיים', 'ru': 'два'}})
            self.assertEqual(post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'שלוש', 'ru': 'три'}}),
                             (409, {'error': 'too_many'}))
            self.assertEqual(post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'אחת', 'ru': 'раз'}})[0], 200)

    def test_a_file_adds_new_words_at_the_end_and_updates_known_ones_in_place(self):
        post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'חיפה', 'ru': 'Хайфа'}})
        post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'עכו', 'ru': 'Акко'}})
        status, body = post(self.ui, {'action': 'vocabulary_import', 'entries': [
            {'he': 'סולמית', 'ru': 'решётка (#)'}, {'he': ' חיפה ', 'ru': 'Хайфа', 'en': 'Haifa'},
            {'he': 'כוכבית', 'ru': 'звёздочка'}, {'he': 'כוכבית', 'ru': 'звёздочка (*)'}]})
        self.assertEqual(status, 200)
        self.assertEqual([(entry['he'], entry['ru'], entry['en']) for entry in body['entries']],
                         [('עכו', 'Акко', ''), ('חיפה', 'Хайфа', 'Haifa'), ('סולמית', 'решётка (#)', ''),
                          ('כוכבית', 'звёздочка (*)', '')])

    def test_a_file_with_one_bad_entry_changes_nothing(self):
        post(self.ui, {'action': 'vocabulary_set', 'value': {'he': 'חיפה', 'ru': 'Хайфа'}})
        before = (self.home / 'vocabulary.json').read_bytes()
        self.assertEqual(post(self.ui, {'action': 'vocabulary_import', 'entries': [
            {'he': 'סולמית', 'ru': 'решётка'}, {'he': 'Haifa', 'ru': 'Хайфа'}]}), (400, {'error': 'not_hebrew', 'index': 1}))
        self.assertEqual(post(self.ui, {'action': 'vocabulary_import', 'entries': []})[0], 400)
        with mock.patch('hebrew_live.browser_ui.VOCABULARY_LIMIT', 2):
            self.assertEqual(post(self.ui, {'action': 'vocabulary_import', 'entries': [
                {'he': 'אחת', 'ru': 'один'}, {'he': 'שתיים', 'ru': 'два'}]}), (409, {'error': 'too_many'}))
        self.assertEqual((self.home / 'vocabulary.json').read_bytes(), before)

    def test_a_whole_list_of_500_long_entries_fits_in_one_request(self):
        entries = [{'he': 'א' * 55 + f'{index:05d}', 'ru': 'я' * 120, 'en': 'e' * 120} for index in range(500)]
        status, body = post(self.ui, {'action': 'vocabulary_import', 'entries': entries})
        self.assertEqual((status, len(body['entries'])), (200, 500))


if __name__ == '__main__':
    unittest.main()
