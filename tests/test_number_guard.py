import unittest

from hebrew_live.number_guard import Issue, _Side, check, unheard


class NumberGuardTests(unittest.TestCase):
    def numbers(self, text, language):
        return _Side(text, language).values

    def test_a_day_spoken_in_words_must_not_become_a_year(self):
        self.assertEqual(check('הפגישה שלך במרץ שבע', 'Ваша встреча в марте 2007 года'), [Issue('extra', '2007')])
        self.assertEqual(check('הפגישה שלך בשבעה במרץ', 'Ваша встреча 7 марта'), [])

    def test_a_digit_lost_or_changed_is_reported_from_both_sides(self):
        self.assertEqual(check('הפגישה ב-27 במאי', 'Встреча в мае'), [Issue('missing', '27')])
        self.assertEqual(check('הפגישה ב-27 במאי', 'Встреча 17 мая'), [Issue('missing', '27'), Issue('extra', '17')])
        self.assertEqual(check('הפגישה ב-27 במאי', 'Встреча 27 мая'), [])

    def test_digits_spelled_out_in_the_translation_are_accepted(self):
        self.assertEqual(check('הפגישה ב-27 במאי', 'Встреча двадцать седьмого мая'), [])
        self.assertEqual(check('בשנת 1996', 'В тысяча девятьсот девяносто шестом году'), [])
        self.assertEqual(check('בשנת 2026', 'in two thousand twenty-six', 'he', 'en'), [])
        self.assertEqual(check('בשנת 1996', 'in nineteen ninety-six', 'he', 'en'), [])
        self.assertEqual(check('יש 5 דקות', 'Есть пять минут'), [])

    def test_hebrew_number_words_explain_digits_in_the_translation(self):
        for source, translation in (
                ('עשרים ושבע במאי', '27 мая'),
                ('אלפיים עשרים ושש', '2026 год'),
                ('אלף תשע מאות תשעים ושש', '1996 год'),
                ('שלוש מאות ארבעים וחמש שקלים', '345 шекелей'),
                ('שלוש עשרה דקות', '13 минут'),
                ('אחת עשרה ושתים עשרה', '11 и 12'),
                ('עשרים אלף שקל', '20 000 шекелей'),
                ('שלושת אלפים חמש מאות', '3500'),
                ('מאה עשרים', '120'),
                ('חכה שעתיים', 'Подождите 2 часа'),
                ('בקומה השלישית', 'на 3-м этаже')):
            with self.subTest(source=source):
                self.assertEqual(check(source, translation), [])

    def test_two_numbers_in_a_row_are_not_added_together(self):
        self.assertEqual(check('עשרים וארבע שבע', '24/7'), [])
        self.assertIn(24, self.numbers('עשרים וארבע שבע', 'he'))
        self.assertNotIn(31, self.numbers('עשרים וארבע שבע', 'he'))

    def test_digits_read_out_one_by_one(self):
        self.assertEqual(check('אפס חמש ארבע אחת שתיים שלוש ארבע חמש שש שבע', '054-123-45-67'), [])
        self.assertEqual(check('הקש אפס חמש ארבע', 'Нажмите 054'), [])
        self.assertEqual(check('הקש אפס חמש ארבע', 'Нажмите 055'), [Issue('extra', '055')])

    def test_phone_numbers_and_separators_may_be_regrouped(self):
        self.assertEqual(check('הטלפון 0541234567', 'Телефон 054-123-45-67'), [])
        self.assertEqual(check('הטלפון 054-1234567', 'Телефон 0541234567'), [])
        self.assertEqual(check('זה עולה 10,000 שקל', 'Это стоит 10 000 шекелей'), [])
        self.assertEqual(check('זה עולה 10,000 שקל', 'Это стоит 10 тысяч шекелей'), [])
        self.assertEqual(check('זה עולה 10 אלף שקל', 'Это стоит 10000 шекелей'), [])
        self.assertEqual(check('הטלפון 0541234567', 'Телефон 054-123-45-68'), [Issue('missing', '0541234567'), Issue('extra', '68')])

    def test_clock_times(self):
        self.assertEqual(check('בשעה 14:30', 'в 14:30'), [])
        self.assertEqual(check('בשעה 14:30', 'at 2:30 PM', 'he', 'en'), [])
        self.assertEqual(check('בארבע אחר הצהריים', 'в 16:00'), [])
        self.assertEqual(check('בשתיים וחצי', 'в 2:30'), [])
        self.assertEqual(check('ברבע לחמש', 'в 4:45'), [])
        self.assertEqual(check('בשתיים וחצי', 'в 3:40'), [Issue('extra', '3'), Issue('extra', '40')])

    def test_words_without_digits_never_raise_an_issue(self):
        self.assertEqual(check('ביום שני בבוקר', 'В понедельник утром'), [])
        self.assertEqual(check('יש לי שאלה אחת', 'У меня вопрос'), [])
        self.assertEqual(check('בשתיים וחצי', 'в половине третьего'), [])

    def test_russian_weekdays_are_not_ordinals(self):
        values = self.numbers('в пятницу и во вторник', 'ru')
        self.assertFalse(values & {2, 5})
        self.assertIn(5, self.numbers('пятого числа', 'ru'))
        self.assertIn(2026, self.numbers('две тысячи двадцать шестого года', 'ru'))

    def test_russian_source_and_unknown_language(self):
        self.assertEqual(check('Встреча двадцать седьмого мая', 'הפגישה ב-27 במאי', 'ru', 'he'), [])
        self.assertEqual(check('Встреча 27 мая', 'הפגישה ב-17 במאי', 'ru', 'he'), [Issue('missing', '27'), Issue('extra', '17')])
        self.assertEqual(check('27 מאי', '27 mai', 'he', 'fr'), [])
        self.assertEqual(check('עשרים ושבע במאי', '27 mai', 'he', 'fr'), [])


class UnheardTests(unittest.TestCase):
    def test_a_number_waits_until_the_hebrew_says_it(self):
        self.assertEqual(unheard('לביטוח נסיעות לחו"ל יש להקיש', '', 'Для страхования путешествий — 4'.split()), 4)
        self.assertIsNone(unheard('לביטוח נסיעות לחו"ל יש להקיש ארבע', '', 'Для страхования путешествий — 4'.split()))
        self.assertEqual(unheard('יש להקיש', 'Для', 'страхования нажмите четыре'.split()), 2)

    def test_a_number_said_once_is_used_once(self):
        hebrew = 'לביטוח רכב יש להקיש אחת, לביטוח דירה יש להקיש'
        self.assertEqual(unheard(hebrew, 'Для автострахования нажмите 1,', 'для жилья — тоже 1.'.split()), 4)
        self.assertIsNone(unheard(hebrew + ' שתיים', 'Для автострахования нажмите 1,', 'для жилья — 2.'.split()))
        self.assertEqual(unheard('press one', '', 'нажмите один, потом один'.split(), 'en', 'ru'), 3)

    def test_spoken_numbers_times_and_english(self):
        self.assertIsNone(unheard('בשעה עשרים ושלוש', '', 'в двадцать три часа'.split()))
        self.assertIsNone(unheard('בשעה עשר בבוקר', '', 'в 10:00 утра'.split()))
        self.assertIsNone(unheard('הקישו 2', '', 'press two'.split(), 'he', 'en'))
        self.assertEqual(unheard('שלום', '', 'Hello, press one'.split(), 'he', 'en'), 2)
        self.assertIsNone(unheard('שלום', '', 'Здравствуйте, это вторник'.split()))
        self.assertEqual(unheard('להשמעה חוזרת יש', 'Для повтора', 'нажмите «восьмёрку»'.split()), 1)
        self.assertIsNone(unheard('לחזרה הקישו שמונה', '', 'Назад — нажмите «восьмерку»'.split()))


if __name__ == '__main__':
    unittest.main()
