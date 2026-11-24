import unittest,queue,threading,time
from types import SimpleNamespace
import numpy as np
from hebrew_live.cli import Engine,Fragment
from hebrew_live.phrase_buffer import PhraseBuffer
from hebrew_live.phrase_inference import PhraseProcessor
from hebrew_live.stream import Settings

class AcceptanceTests(unittest.TestCase):
 def words(self):return [dict(word=w,start=i*.3,end=(i+1)*.3) for i,w in enumerate(['we','can','proceed'])]
 def test_empty_and_rejected_preserve_without_confirming(self):
  for status in ('empty','rejected'):
   b=PhraseBuffer();b.update(self.words(),0,2,1)
   b.update(self.words() if status=='rejected' else [],0,3,1,True,status)
   self.assertFalse(any(w['stable'] for w in b.pending));self.assertEqual(b.take(3,quiet=.6,final=True),[])
   units=b.take(3,force='eof');self.assertEqual(len(units),1);self.assertTrue(units[0].unconfirmed)
   self.assertFalse(b.pending)
 def test_later_accepted_result_confirms_preserved_tail(self):
  b=PhraseBuffer();b.update(self.words(),0,2,1);b.update([],0,3,1,True,'empty')
  b.update(self.words(),0,4,1,True,'accepted');u=b.take(4,quiet=.6,final=True)
  self.assertFalse(u[0].unconfirmed)
