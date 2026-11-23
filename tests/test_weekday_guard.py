import os
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from hebrew_live.cli import Fragment
from hebrew_live.retranslation import RetranslationProcessor
from hebrew_live.stream import Settings

from hebrew_live.weekday_guard import fix, hebrew_days


class WeekdayGuard(unittest.TestCase):
    # Translations as MiLMMT gave them on the 23.11.2026 recordings.
    def test_wrong_day_after_yom_is_replaced_in_the_same_case(self):
        text, issues = fix('אני רוצה לקבוע תור לרופא שיניים ביום שלישי בשעה עשר בבוקר',
                           'Я хочу записаться к стоматологу в четверг в десять часов утра')
        self.assertEqual(text, 'Я хочу записаться к стоматологу во вторник в десять часов утра')
        self.assertEqual([(i.kind, i.he, i.ru, i.expected) for i in issues], [('fixed', 'שלישי', 'четверг', 'вторник')])

    def test_range_of_days(self):
        text, _ = fix('המרפאה פתוחה בימים ראשון עד חמישי, וביום שישי בין שמונה לשתים עשרה',
                      'Клиника открыта с понедельника по четверг, а в пятницу с 8 до 12')
        self.assertEqual(text, 'Клиника открыта с воскресенья по четверг, а в пятницу с 8 до 12')
        text, _ = fix('פתוח ראשון עד חמישי', 'Открыто с понедельника по пятницу')
        self.assertEqual(text, 'Открыто с воскресенья по четверг')

    def test_next_monday_for_tuesday(self):
        text, _ = fix('קבעתי לשבוע הבא ביום שלישי בעשר וחצי', 'я записался на следующий понедельник в десять тридцать')
        self.assertEqual(text, 'я записался на следующий вторник в десять тридцать')

    def test_ordinals_without_a_day_word_are_not_days(self):
        self.assertEqual(hebrew_days('הוא הגיע ראשון, והשני אחריו'), [])
        self.assertEqual(hebrew_days('שני אנשים'), [])
        text, issues = fix('הוא הגיע ראשון', 'Он пришёл в четверг')
        self.assertEqual(text, 'Он пришёл в четверг')                   # never a silent change
        self.assertEqual([i.kind for i in issues], ['extra'])

    def test_invented_day_is_reported(self):
        # The source says «earlier»; the translator invented Thursday.
        text, issues = fix('ואני רוצה לבדוק אם אפשר להקדים אותו', 'и я хотел узнать, можно ли перенести на четверг')
        self.assertEqual([(i.kind, i.ru) for i in issues], [('extra', 'четверг')])

    def test_letter_days_shabbat_and_correct_days(self):
        self.assertEqual(fix("תור ליום ה' בבוקר", 'Запись на среду утром')[0], 'Запись на четверг утром')
        self.assertEqual(fix('נתראה בשבת', 'Увидимся в шабат'), ('Увидимся в шабат', []))
        self.assertEqual(fix('היום יום שני', 'Сегодня понедельник'), ('Сегодня понедельник', []))
        self.assertEqual(hebrew_days('ה מרפאה'), [])                      # the article is not Thursday

    def test_a_day_adjective_counts_but_is_never_rewritten(self):
        self.assertEqual(fix('כיף שבת זאת', 'приятного субботнего дня'), ('приятного субботнего дня', []))
        text, issues = fix('ביום ראשון', 'в субботний день')
        self.assertEqual(text, 'в субботний день')
        self.assertEqual([i.kind for i in issues], ['wrong'])

    def test_counts_that_do_not_pair_up_are_only_reported(self):
        text, issues = fix('ביום שלישי או ביום רביעי', 'в четверг')
        self.assertEqual(text, 'в четверг')
        self.assertEqual(sorted(i.kind for i in issues), ['extra', 'missing', 'missing'])

    def test_shown_words_are_not_changed(self):
        text, issues = fix('ביום שלישי ואז ביום חמישי', 'в понедельник, а потом в пятницу', frozen=15)
        self.assertEqual(text, 'в понедельник, а потом в четверг')
        self.assertEqual([i.kind for i in issues], ['wrong', 'fixed'])


class LiveScreen(unittest.TestCase):
    def setUp(self):
        self.events, self.results = [], []
        engine = SimpleNamespace(recognize=self.recognize, translate=lambda text: iter([(self.target, 'stop')]))
        self.engine = engine
        self.updates = queue.Queue()
        log = SimpleNamespace(event=lambda name, **values: self.events.append((name, values)),
                              parts={1: SimpleNamespace(text=lambda *args: None)})
        self.processor = RetranslationProcessor(engine, self.updates, log, threading.Event())
        self.settings = Settings(publication='draft', direction='he-ru')
        self.audio = np.zeros(64000, dtype=np.float32)

    def recognize(self, *args, **kwargs):
        text, self.target = self.results.pop(0)
        self.engine.recognition_status = 'accepted'
        return text

    def say(self, text, target, end, final=False):
        self.results.append((text, target))
        self.processor.process(Fragment(1, 1, self.audio[:end].copy(), 0, time.monotonic(), final, self.settings,
                                        end / 16000, 0, 'silence' if final else ''))

    def publications(self):
        return [value for kind, _, value in self.updates.queue if kind == 'live_publication']

    def test_every_version_shows_the_fixed_day_and_the_closed_one_is_logged(self):
        self.say('תור ביום שלישי', 'Запись на четверг', 16000)
        self.assertEqual(self.publications()[-1]['current']['translation'], 'Запись на вторник')
        self.say('תור ביום שלישי', 'unused', 32000, final=True)
        closed = self.publications()[-1]
        self.assertEqual(closed['stage'], 'closed')
        self.assertEqual(closed['current']['translation'], 'Запись на вторник')
        self.assertEqual([d['kind'] for d in closed['days']], ['fixed'])
        (name, logged), = [e for e in self.events if e[0] == 'weekday_check']
        self.assertEqual(logged['issues'], closed['days'])

    def test_the_check_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {'HEBREW_LIVE_WEEKDAY_CHECK': '0'}):
            self.say('תור ביום שלישי', 'Запись на четверг', 16000)
        self.assertEqual(self.publications()[-1]['current']['translation'], 'Запись на четверг')


if __name__ == '__main__':
    unittest.main()
