import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hebrew_live import vocabulary
from hebrew_live.cli import Engine
from hebrew_live.vocabulary import Entry, add, asr_prompt, load, remove, save


def words(text):
    return len(text.replace(',', ' ').split())


class VocabularyFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.file = Path(self.folder.name) / 'nested' / 'vocabulary.json'

    def test_missing_or_broken_file_is_an_empty_vocabulary(self):
        self.assertEqual(load(self.file), [])
        self.file.parent.mkdir()
        for broken in ('{', '[]', '{"entries": 3}', '{"entries": ["word"]}'):
            self.file.write_text(broken)
            self.assertEqual(load(self.file), [], broken)

    def test_order_survives_saving_and_blank_or_repeated_entries_are_dropped(self):
        save([Entry('תכנית', 'программа'), Entry('ארנונה', en='arnona')], self.file)
        self.assertEqual(load(self.file), [Entry('תכנית', 'программа'), Entry('ארנונה', en='arnona')])
        self.assertEqual(os.listdir(self.file.parent), ['vocabulary.json'])      # no temporary file left
        self.file.write_text(json.dumps(dict(entries=[dict(he='  גן   ילדים '), dict(he=''), dict(ru='x'),
                                                      dict(he='גן ילדים', ru='later')])))
        self.assertEqual(load(self.file), [Entry('גן ילדים')])

    def test_added_word_goes_first_and_replaces_its_old_entry(self):
        entries = add(add([], 'תכנית'), 'ארנונה')
        self.assertEqual([entry.he for entry in entries], ['ארנונה', 'תכנית'])
        entries = add(entries, ' תכנית ', ru='программа')
        self.assertEqual(entries, [Entry('תכנית', 'программа'), Entry('ארנונה')])
        self.assertEqual(remove(entries, 'תכנית'), [Entry('ארנונה')])
        with self.assertRaises(ValueError):
            add(entries, '  ')

    def test_default_file_lives_in_the_app_data_folder(self):
        with mock.patch.dict('os.environ', {'HEBREW_LIVE_HOME': self.folder.name}):
            self.assertEqual(vocabulary.path(), Path(self.folder.name) / 'vocabulary.json')


class RecognizerPromptTests(unittest.TestCase):
    def test_prompt_keeps_the_top_of_the_list_within_the_budget(self):
        entries = [Entry('אחת'), Entry('שתיים שלוש ארבע'), Entry('חמש'), Entry('שש')]
        text, used = asr_prompt(entries, words, budget=3)
        self.assertEqual(text, 'אחת, חמש, שש.')                # the long entry is skipped, later short ones fit; a period ends the list
        self.assertEqual(used, [entries[0], entries[2], entries[3]])
        self.assertEqual(asr_prompt([], words), ('', []))
        self.assertEqual(asr_prompt(entries, words, budget=0), ('', []))

class TranslatorTermsTests(unittest.TestCase):
    ENTRIES = [Entry('חיפה', 'Хайфа', 'Haifa'), Entry('גן ילדים', 'детский сад'), Entry('תכנית', en='programme'),
               Entry('רז', 'Раз')]

    def test_only_words_said_in_the_phrase_with_a_translation_into_the_language(self):
        text = 'יש לי תכנית מגן ילדים, ובחיפה אמרו לחכות.'
        self.assertEqual(vocabulary.relevant(self.ENTRIES, text, 'ru'), [('חיפה', 'Хайфа'), ('גן ילדים', 'детский сад')])
        self.assertEqual(vocabulary.relevant(self.ENTRIES, text, 'en'), [('חיפה', 'Haifa'), ('תכנית', 'programme')])
        self.assertEqual(vocabulary.relevant(self.ENTRIES, text, 'fr'), [])
        self.assertEqual(vocabulary.relevant(self.ENTRIES, 'גן קטן של ילדים', 'ru'), [])

    def test_a_short_name_inside_another_word_is_not_a_match(self):
        self.assertEqual(vocabulary.relevant(self.ENTRIES, 'זה ארז ולא מרזה', 'ru'), [])     # ארז, מרזה are other words
        self.assertEqual(vocabulary.relevant(self.ENTRIES, 'דיברתי עם רז.', 'ru'), [('רז', 'Раз')])
        self.assertEqual(vocabulary.relevant(self.ENTRIES, 'ולרז יש זמן', 'ru'), [('רז', 'Раз')])

    def test_terms_open_the_translation_request(self):
        from hebrew_live.translation import prompt
        tokenizer = SimpleNamespace(encode=lambda text, add_special_tokens=False: text)
        plain = prompt(tokenizer, 'milmmt', 'בחיפה', 'he-ru')
        self.assertEqual(prompt(tokenizer, 'milmmt', 'בחיפה', 'he-ru', terms=[('חיפה', 'Хайфа')]),
                         'Use these translations of names and terms:\nחיפה = Хайфа\n' + plain)
        self.assertEqual(prompt(tokenizer, 'milmmt', 'בחיפה', 'he-ru', terms=[]), plain)

    CLINIC = [Entry('מכבידנט כרמיאל', 'Маккабидент Кармиэль'), Entry('מכבידנט', 'Маккабидент'), Entry('מכבי', 'Маккаби')]

    def test_live_terms_are_found_however_the_recognizer_split_them(self):
        heard = lambda text: vocabulary.heard(self.CLINIC, text, 'ru')
        self.assertEqual(heard('ברוכים הבאים למכבי דנט, מיד'), [('מכבי דנט', 'Маккабидент')])
        self.assertEqual(heard('במכבי-דנט כרמיאל.'), [('מכבי-דנט כרמיאל', 'Маккабидент Кармиэль')])
        self.assertEqual(heard('מכבידנט מבית מכבי שירותי בריאות'), [('מכבידנט', 'Маккабидент'), ('מכבי', 'Маккаби')])
        self.assertEqual(heard('שלום לכולם'), [])
        self.assertEqual(vocabulary.heard(self.CLINIC, 'מכבי', 'en'), [])         # no translation into it

    def test_live_terms_do_not_match_inside_another_word(self):
        self.assertEqual(vocabulary.heard(self.ENTRIES, 'זה ארז ולא מרזה', 'ru'), [])
        self.assertEqual(vocabulary.heard(self.ENTRIES, 'ולרז יש זמן', 'ru'), [('רז', 'Раз')])
        self.assertEqual(vocabulary.heard([Entry("רז", "Раз")] + [Entry(f'מילה{i}', 'x') for i in range(9)],
                                          'רז ' + ' '.join(f'מילה{i}' for i in range(9)), 'ru')[-1], ('מילה6', 'x'))


if __name__ == '__main__':
    unittest.main()


class LiveTranslationTests(unittest.TestCase):
    def pairs(self, direction, text, entries, pairs=()):
        from hebrew_live.clause_mt import Result
        engine = object.__new__(Engine)
        if entries is not None: engine.vocabulary_file = SimpleNamespace(current=lambda: entries)
        seen = []
        engine._clause_generator = SimpleNamespace(min_prob=0., generate=lambda text, forced, given, *a, **k:
                                                   (seen.append(given), Result(['ок'], 'end'))[1])
        engine.clause_generate(text, '', pairs, direction)
        return seen[0]

    def test_terms_said_come_before_the_context_as_finished_sentences(self):
        entries = [Entry('מכבידנט', 'Маккабидент')]
        self.assertEqual(self.pairs('he-ru', 'למכבי דנט שלום', entries, [['כן.', 'Да.']]),
                         (('מכבי דנט.', 'Маккабидент.'), ('כן.', 'Да.')))
        self.assertEqual(self.pairs('he-ru', 'שלום', entries, [['כן.', 'Да.']]), (('כן.', 'Да.'),))
        self.assertEqual(self.pairs('he-en', 'למכבי דנט', entries), ())
        self.assertEqual(self.pairs('he-ru', 'למכבי דנט', None), ())      # an engine built without a vocabulary
        self.assertEqual(self.pairs('ru-he', 'מכבידנט', entries), ())


class EngineTranslationTests(unittest.TestCase):
    def requests(self, direction, entries):
        import sys, types
        engine = object.__new__(Engine)
        engine.model = object(); engine.direction = direction; engine.topic = 'none'; engine.translation_context = []
        engine.tokenizer = SimpleNamespace(encode=lambda text, add_special_tokens=False: [1, 2, 3])
        engine.log = SimpleNamespace(event=lambda name, **values: None)
        if entries is not None: engine.vocabulary = entries
        seen = []
        sample_utils = types.ModuleType('mlx_lm.sample_utils'); sample_utils.make_sampler = lambda **_: object()
        with mock.patch.dict(sys.modules, {'mlx_lm.sample_utils': sample_utils}), \
                mock.patch('hebrew_live.mt_generate.generate', lambda *a, **k: iter([('ok', 'stop')])), \
                mock.patch('hebrew_live.translation.prompt', lambda *a, **k: (seen.append(k['terms']), [1])[1]):
            list(engine.translate('בחיפה אמרו לחכות'))
        return seen

    def test_translation_request_gets_the_terms_of_the_phrase(self):
        entries = [Entry('חיפה', 'Хайфа', 'Haifa'), Entry('תכנית', 'программа')]
        self.assertEqual(self.requests('he-ru', entries), [[('חיפה', 'Хайфа')]])
        self.assertEqual(self.requests('he-en', entries), [[('חיפה', 'Haifa')]])
        self.assertEqual(self.requests('ru-he', entries), [[]])        # Hebrew terms describe Hebrew speech only
        self.assertEqual(self.requests('he-ru', None), [[]])           # an engine built without a vocabulary
