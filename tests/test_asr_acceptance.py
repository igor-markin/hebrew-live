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
 def test_real_recognize_rejection_never_translated_in_phrase_mode(self):
  for language,text in [('he','א'+'ה'*30),('ru','שלום')]:
   log=SimpleNamespace(event=lambda *a,**kw:None)
   e=Engine.__new__(Engine);e.language=language;e.asr_path='fake';e.log=log;e.language_check='off'
   e.asr=SimpleNamespace(transcribe=lambda *a,**k:dict(segments=[dict(words=[dict(word=text,start=0,end=1)])]))
   e.translate=lambda *a:(_ for _ in ()).throw(AssertionError('Rejected words translated'))
   pp=PhraseProcessor(e,queue.Queue(),log,threading.Event())
   pp.process(Fragment(1,1,np.zeros(32000),0,time.monotonic(),True,Settings(language=language,mode='phrases'),2,0))
   self.assertEqual(e.recognition_status,'rejected');self.assertEqual(e.recognition_words,[]);self.assertEqual(e.raw_recognition,text)
