import unittest
from types import SimpleNamespace
from hebrew_live.script_filter import clearly_non_hebrew

class ScriptFilterTests(unittest.TestCase):
 def test_text_not_language_claim(self):
  for text in ('Hello doctor','Здравствуйте','مرحبا'):self.assertTrue(clearly_non_hebrew(text))
  for text in ('שלום','שָׁלוֹם','שלום Google','15:30','?!',''):self.assertFalse(clearly_non_hebrew(text))
