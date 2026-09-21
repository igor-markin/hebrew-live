import unittest
from types import SimpleNamespace
from hebrew_live.script_filter import clearly_non_hebrew
from hebrew_live.cli import Engine

class ScriptFilterTests(unittest.TestCase):
 def test_text_not_language_claim(self):
  for text in ('Hello doctor','Здравствуйте','مرحبا'):self.assertTrue(clearly_non_hebrew(text))
  for text in ('שלום','שָׁלוֹם','שלום Google','15:30','?!',''):self.assertFalse(clearly_non_hebrew(text))
 def engine(self,text):
  e=Engine.__new__(Engine);e.language='he';e.direction='he-ru';e.early_reject=False;e.encoder_reuse=False;e.asr_path='fake'
  e.log=SimpleNamespace(event=lambda *a,**kw:None)
  e.asr=SimpleNamespace(transcribe=lambda *a,**kw:dict(language='he',segments=[dict(words=[dict(word=text,start=0,end=1)])]))
  return e
 def test_default_recognition_rejects_foreign_script_without_new_model(self):
  e=self.engine('Здравствуйте')
  self.assertEqual(e.recognize([],mode='phrases'),'');self.assertEqual(e.recognition_status,'rejected')
  self.assertEqual(e.recognition_words,[]);self.assertEqual(e.raw_recognition,'Здравствуйте')
  self.assertEqual(e.recognition_issue,'non-Hebrew transcript')
 def test_hebrew_and_reverse_direction_remain_available(self):
  e=self.engine('שלום');self.assertEqual(e.recognize([]),'שלום')
  e=self.engine('Здравствуйте');e.direction='ru-he';e.language='ru'
  self.assertEqual(e.recognize([]),'Здравствуйте');self.assertEqual(e.recognition_status,'accepted')
 def test_rejected_foreign_final_does_not_publish_stale_draft(self):
  import queue,threading,time,numpy as np
  from hebrew_live.retranslation import RetranslationProcessor
  from hebrew_live.cli import Fragment
  from hebrew_live.stream import Settings
  e=self.engine('Hello');q=queue.Queue();p=RetranslationProcessor(e,q,e.log,threading.Event())
  p.process(Fragment(1,1,np.zeros(16000,dtype=np.float32),0,time.monotonic(),True,Settings(publication='revisable'),1,0,'silence'))
  result=[v for k,_,v in q.queue if k=='live_publication'][-1]
  self.assertEqual(result['stage'],'unavailable');self.assertIn('другом языке',result['issue']);self.assertFalse(result['current']['translation'])
