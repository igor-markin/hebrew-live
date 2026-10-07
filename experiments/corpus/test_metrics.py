"""Local tests: `.venv/bin/python -m unittest discover -s experiments/corpus`."""
import unittest

from metrics import chrf, corpus_wer, edit_counts, wer
from normalize import normalize


class NormalizeTests(unittest.TestCase):
    def test_leaderboard_steps(self):
        self.assertEqual(normalize('שָׁלוֹם, עולם!'), 'שלום עולם')               # niqqud and punctuation
        self.assertEqual(normalize('הוא אמר "לא" ו\'כן\''), 'הוא אמר לא וכן')   # quotes are deleted, not spaced
        self.assertEqual(normalize('a‏b  [noise] (x) C'), 'ab c')           # invisible chars, brackets, case
        self.assertEqual(normalize('כך-וכך'), 'כך וכך')                          # maqaf-like hyphen becomes a space
    def test_finals_are_kept_unless_requested(self):
        self.assertEqual(normalize('ספרים'), 'ספרים')
        self.assertEqual(normalize('ספרים', fold_finals=True), 'ספרימ')
    def test_digits_survive(self):
        self.assertEqual(normalize('ב-15 בחודש'), 'ב 15 בחודש')


class WerTests(unittest.TestCase):
    def test_edit_counts(self):
        self.assertEqual(edit_counts('a b c'.split(), 'a b c'.split()), (0, 0, 0))
        self.assertEqual(edit_counts('a b c'.split(), 'a x c'.split()), (1, 0, 0))
        self.assertEqual(edit_counts('a b c'.split(), 'a c'.split()), (0, 1, 0))
        self.assertEqual(edit_counts('a b'.split(), 'a x b'.split()), (0, 0, 1))
    def test_wer_uses_the_normaliser(self):
        self.assertEqual(wer('שלום עולם.', 'שלום עולם'), 0.)
        self.assertAlmostEqual(wer('אני רוצה תור לרופא', 'אני רוצה תור רופא'), 1 / 4)
        self.assertIsNone(wer('', 'x'))
    def test_corpus_wer_is_micro_averaged(self):
        value, words = corpus_wer([('a b', 'a b'), ('c d e f', 'c x e f')])
        self.assertEqual((value, words), (1 / 6, 6))


class ChrfTests(unittest.TestCase):
    def test_identical_and_disjoint(self):
        self.assertAlmostEqual(chrf('The cat sat.', 'The cat sat.'), 100.)
        self.assertEqual(chrf('abc', 'xyz'), 0.)
    def test_closer_text_scores_higher_and_empty_is_zero(self):
        reference = 'He is going to the doctor on Tuesday.'
        near = chrf('He goes to the doctor on Tuesday.', reference)
        far = chrf('She is going to the shop on Friday.', reference)
        self.assertGreater(near, far)
        self.assertGreater(far, 0)
        self.assertEqual(chrf('', reference), 0.)


if __name__ == '__main__':
    unittest.main()
