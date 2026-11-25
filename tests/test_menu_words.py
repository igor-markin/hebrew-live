import unittest
from unittest import mock

from hebrew_live.menu_words import button, fix
import test_append_live
from test_append_live import FakeGenerator


class Words(unittest.TestCase):
    def test_press_and_please_are_put_right_and_the_count_of_words_stays(self):
        for heard, right in (('לשירותי עזרה ראשונה, אנאה קישו 3,', 'לשירותי עזרה ראשונה, אנא הקישו 3,'),
                             ('הענה כי שו 2', 'הענה אנא הקישו 2'),
                             ('קיים הענק ישו 2', 'קיים אנא הקישו 2'),
                             ('שעות הפעילות הקישוש 3.', 'שעות הפעילות הקישו 3.'),
                             ('קיים הקיישו-שתיים', 'קיים הקישו-2'),
                             ('לחידוש פוליסה יש להקיש שתיים, לתביעה', 'לחידוש פוליסה יש להקיש 2, לתביעה'),
                             ('מבית מכבי, אנה קישושיש.', 'מבית מכבי, אנא הקישו-6.'),
                             ('חיסכון יש להקי 3.', 'חיסכון יש להקיש 3.')):
            self.assertEqual(fix(heard), right)
            self.assertEqual(len(heard.split(' ')), len(right.split(' ')))

    def test_ordinary_speech_is_left_alone(self):
        for text in ('שלחתי לך קישור', 'הקישור לא עובד', 'בשעה שתיים', 'יש שתיים', 'אמא באה ב 5', 'ישו נולד', 'כי שוב 2', 'אנה הלכה', '', 'בשעה 3'):
            self.assertEqual(fix(text), text)

    def test_a_button_is_a_number_after_press_with_its_subject_before(self):
        for text in ('לשירות לקוחות הקישו 2', 'לחידוש פוליסה יש להקיש שתיים,', 'לשירות אנה קישו ארבע', 'לאסתטיקה אנה קישושיש'):
            self.assertTrue(button(text.split()), text)
        for text in ('הקישו 2', 'אנא הקישו 2', 'יש להקיש שתיים', 'לשירות לקוחות הקישו', 'בשעה 2', 'קישור'):
            self.assertFalse(button(text.split()), text)


class Screen(unittest.TestCase):
    setUp, make, feed, publications, finish = (getattr(test_append_live.Append, n) for n in ('setUp', 'make', 'feed', 'publications', 'finish'))
    MENU = [(' לשירות', .2), (' קישו', .6), (' 2', 1.), (' לאסותא', 1.4), (' קישו', 1.8), (' 3', 2.2), (' תודה', 2.6)]

    def run_menu(self, script=MENU):
        processor = self.make(list(script), deadline=100.)
        self.feed(processor, 4., final=True, reason='silence')
        self.finish(processor)
        return [p['current'] for p in self.publications() if p['stage'] == 'closed']

    def test_every_button_is_a_sentence_of_its_own_and_the_shown_hebrew_stays(self):
        closed = self.run_menu()
        self.assertEqual([c['source'] for c in closed], ['לשירות קישו 2', 'לאסותא קישו 3', 'תודה'])
        self.assertEqual([(c['text'], c['close']) for c in self.generator.calls[:2]],
                         [('לשירות הקישו 2.', True), ('לאסותא הקישו 3.', True)])
        self.assertEqual(self.generator.calls[1]['pairs'], (('לשירות הקישו 2.', 'ru:לשירות ru:הקישו ru:2.'),))

    def test_a_comma_after_the_number_ends_its_word(self):
        closed = self.run_menu([*self.MENU[:3], (',', 1.1), *self.MENU[3:]])
        self.assertEqual(closed[0]['source'], 'לשירות קישו 2,')
        self.assertEqual(self.generator.calls[0]['text'], 'לשירות הקישו 2.')

    def test_a_sentence_end_before_the_number_is_not_taken(self):
        processor = self.make([(' לשירות', .2), (' לקוחות', .5), (' קישו', .8), (' 4', 3.)], deadline=1.,
                              generator=FakeGenerator(['sentence']))
        self.feed(processor, 4.)
        self.assertEqual([(c['text'], c['close']) for c in self.generator.calls], [('לשירות לקוחות הקישו', False)])
        self.feed(processor, 5., final=True, reason='silence')
        self.finish(processor)
        closed = [p['current'] for p in self.publications() if p['stage'] == 'closed']
        self.assertEqual((self.generator.calls[-1]['text'], self.generator.calls[-1]['forced']),
                         ('לשירות לקוחות הקישו 4.', 'ru:לשירות ru:לקוחות'))
        self.assertEqual(closed[0]['translation'], 'ru:לשירות ru:לקוחות ru:הקישו ru:4.')

    def test_it_can_be_switched_off(self):
        with mock.patch.dict('os.environ', HEBREW_LIVE_MENU='0'):
            closed = self.run_menu()
        self.assertEqual([c['source'] for c in closed], ['לשירות קישו 2 לאסותא קישו 3 תודה'])
        self.assertIn('קישו 2', self.generator.calls[0]['text'])


if __name__ == '__main__':
    unittest.main()
