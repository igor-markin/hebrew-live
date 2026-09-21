import json
import queue
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from hebrew_live.cli import Fragment, Inbox
from hebrew_live.stream import Settings, Boundary
from hebrew_live.retranslation import RetranslationProcessor
from hebrew_live import preferences

class CatchupTests(unittest.TestCase):
 def setUp(self):
  self.audio=np.arange(700000,dtype=np.float32)
  self.settings=Settings(publication='draft',draft_max_audio_seconds=30.,draft_catchup_enabled=True)
  self.events=[];self.mt=[];self.pcm=[];self.results=[];self.saved=[];self.hook=lambda:None
  self.cancel=threading.Event();self.q=queue.Queue();self.inbox=Inbox()
  self.e=SimpleNamespace(recognize=self.recognize,translate=self.translate)
  part=SimpleNamespace(text=lambda kind,f,text:self.saved.append((kind,f.offset,text)))
  self.log=SimpleNamespace(parts={1:part},event=lambda name,**v:self.events.append((name,v)))
  self.p=RetranslationProcessor(self.e,self.q,self.log,self.cancel);self.p.catchup_inbox=self.inbox
 def recognize(self,a,*args,**kw):
  self.pcm.append(a.copy());text,status=self.results.pop(0);self.e.recognition_status=status;self.hook();return text
 def translate(self,text):
  self.mt.append(text);yield 'RU '+text,'stop'
 def f(self,end,rev=1,final=False,reason='',start=0,settings=None,sid=1):
  return Fragment(sid,rev,self.audio[start:end].copy(),0,100+end/16000,final,settings or self.settings,end/16000,0,reason)
 def runf(self,f,*results):
  self.results.extend((x if isinstance(x,tuple) else (x,'accepted')) for x in results);self.p.process(f)
 def pubs(self):return [v for k,_,v in self.q.queue if k=='live_publication']
 def ev(self,name):return [v for k,v in self.events if k==name]
 def prime(self):self.runf(self.f(32000),'first')
 def test_one_yield_and_age(self):
  self.prime();self.inbox.put(self.f(96000,3))
  self.hook=lambda:self.inbox.put(self.f(128000,4)) if len(self.pcm)==3 else None
  self.runf(self.f(64000,2),'pending','newer')
  self.assertEqual(self.mt,['first','newer']);self.assertEqual(self.inbox.get().revision,4)
  self.assertEqual(len(self.ev('mt_deferred_for_asr')),1)
  a,b=self.ev('mt_requested')[-2:]
  self.assertEqual((a['job_id'],a['first_ready_at']),(b['job_id'],b['first_ready_at']))
  self.assertEqual(b['job_version'],2);self.assertTrue(b['catchup_used'])
  np.testing.assert_array_equal(self.p.audio,self.audio[:96000])
 def test_first_cache_and_closing_do_not_yield(self):
  self.inbox.put(self.f(128000,4));self.prime()
  self.runf(self.f(64000,2),'first');self.runf(self.f(96000,3,True,'silence'),'last')
  self.assertEqual(self.mt,['first','last']);self.assertEqual(self.inbox.get().revision,4)
  self.assertEqual(self.ev('mt_deferred_for_asr'),[]);self.assertEqual(self.pubs()[-1]['stage'],'closed')
 def test_failed_preliminary_preserves_provenance(self):
  for status in ('empty','rejected'):
   with self.subTest(status=status):
    self.setUp();self.prime();self.inbox.put(self.f(96000,3))
    with patch('hebrew_live.retranslation.time.monotonic',return_value=200):
     self.runf(self.f(64000,2),'pending',('',status))
    v=self.pubs()[-1];self.assertEqual(v['end'],4.);self.assertEqual(v['current']['revision'],2)
    self.assertEqual(v['current']['source_status'],'accepted');self.assertEqual(self.saved[-1][1],4.)
    self.assertEqual(self.ev('live_publication')[-1]['audio_lag'],96.)
    self.assertEqual(self.mt,['first','pending']);self.assertEqual(self.p.end,96000)
 def test_catchup_closing(self):
  for status in ('accepted','empty','rejected'):
   with self.subTest(status=status):
    self.setUp();self.prime();self.inbox.put(self.f(96000,3,True,'silence'))
    self.runf(self.f(64000,2),'pending',('final' if status=='accepted' else '',status))
    self.assertEqual(self.mt,['first','final'] if status=='accepted' else ['first'])
    self.assertEqual(self.pubs()[-1]['stage'],'closed' if status=='accepted' else 'unavailable')
 def test_catchup_cache(self):
  self.prime();self.inbox.put(self.f(96000,3));self.runf(self.f(64000,2),'pending','first')
  self.assertEqual(self.mt,['first']);self.assertEqual(len(self.ev('mt_cached')),1)
 def test_window_does_not_close(self):
  self.prime();self.inbox.put(self.f(96000,3,True,'window'));self.runf(self.f(64000,2),'pending','new')
  self.assertFalse(self.p.closed);self.assertEqual(self.pubs()[-1]['stage'],'open')
 def test_queue_refusals_leave_next_intact(self):
  current=self.f(64000,2)
  candidates=[self.f(96000,3,sid=2),self.f(96000,3,settings=replace(self.settings,generation=1)),
   self.f(96000,3,settings=replace(self.settings,direction='ru-he')),self.f(96000,3,settings=replace(self.settings,models=('other','other'))),
   self.f(96000,2),self.f(64000,3),self.f(96000,3,start=65000),self.f(480000,3),self.f(500000,3),self.f(96000,3,True,'pause')]
  for f in candidates:
   with self.subTest(f=f.revision,end=f.offset):
    inbox=Inbox();inbox.put(f);taken,reason=inbox.take_draft_catchup(current,0,64000)
    self.assertIsNone(taken);self.assertIs(inbox.get(),f)
 def test_barrier_eof_and_fifo(self):
  for kind in ('barrier','eof','fifo'):
   inbox=Inbox();f=self.f(96000,3,True,'silence');inbox.put(f)
   if kind=='barrier':inbox.put_boundary(Boundary(self.settings,'clear'))
   if kind=='eof':inbox.finish()
   if kind=='fifo':f.settings=replace(self.settings,generation=1);inbox.put(self.f(128000,4,True,'silence'))
   self.assertIsNone(inbox.take_draft_catchup(self.f(64000,2),0,64000)[0]);self.assertIs(inbox.get(),f)
 def test_missing_snapshot_and_disabled(self):
  for enabled in (False,True):
   self.setUp();self.settings=replace(self.settings,draft_catchup_enabled=enabled);self.prime()
   if not enabled:self.inbox.put(self.f(96000,3))
   self.runf(self.f(64000,2),'pending');self.assertEqual(self.mt,['first','pending']);self.assertFalse(self.ev('mt_deferred_for_asr'))
 def test_cancel_during_catchup(self):
  self.prime();self.inbox.put(self.f(96000,3));self.hook=lambda:self.cancel.set() if len(self.pcm)==3 else None
  self.runf(self.f(64000,2),'pending','new');self.assertEqual(self.mt,['first'])
 def test_mt_failure_and_engine_error(self):
  self.prime();old=self.pubs()[-1];self.e.translate=lambda text:iter([('','stop')])
  self.runf(self.f(64000,2),'pending');self.assertEqual(self.pubs()[-1],old);self.assertEqual(self.p.source,'')
  def fail(text):raise RuntimeError('engine')
  self.e.translate=fail
  with self.assertRaisesRegex(RuntimeError,'engine'):self.runf(self.f(96000,3),'new')
 def test_stale_model_result(self):
  self.prime();old=self.pubs()[-1]
  def translate(text):
   self.e.translation_size='changed';yield 'new','stop'
  self.e.translate=translate;self.runf(self.f(64000,2),'pending');self.assertEqual(self.pubs()[-1],old)
 def test_overlap_rejected_without_mutation(self):
  self.prime();f=self.f(64000,2);f.audio[0]=-1
  with self.assertRaisesRegex(ValueError,'overlap'):self.runf(f,'unused')
  np.testing.assert_array_equal(self.p.audio,self.audio[:32000])
 def test_tail_eof_and_continuation(self):
  for closing in ('eof','silence','continue','direction'):
   self.setUp();self.settings=replace(self.settings,draft_max_audio_seconds=2.)
   self.runf(self.f(32768),'first');self.assertEqual(len(self.pcm),1)
   if closing=='continue':self.runf(self.f(60000,2),'tail')
   elif closing=='silence':self.runf(self.f(32768,2,True,'silence'),'tail')
   else:self.results.append(('tail','accepted'));self.p.flush(closing)
   np.testing.assert_array_equal(np.concatenate(self.pcm),self.audio[:60000 if closing=='continue' else 32768])

 def test_worker_path(self):
  from hebrew_live.feed import inference
  self.results=[('first','accepted'),('pending','accepted'),('new','accepted'),('final','accepted')]
  self.inbox.put(self.f(32000))
  def hook():
   n=len(self.pcm)
   if n==1:self.inbox.put(self.f(64000,2))
   if n==2:self.inbox.put(self.f(96000,3))
   if n==3:self.inbox.put(self.f(128000,4,True,'silence'));self.inbox.finish()
  self.hook=hook;errors=queue.Queue();stop=threading.Event()
  inference(self.inbox,self.e,self.q,stop,errors,self.log,self.cancel)
  self.assertTrue(errors.empty());self.assertFalse(stop.is_set())
  self.assertEqual(self.mt,['first','new','final']);self.assertEqual(len(self.ev('mt_deferred_for_asr')),1)
  self.assertEqual(self.pubs()[-1]['stage'],'closed');self.assertEqual(list(self.q.queue)[-1][0],'done')
 def test_clear_rejects_old_publications(self):
  from hebrew_live.display import TranslationScreen
  self.prime();self.inbox.put(self.f(96000,3))
  screen=TranslationScreen();screen.clear(1)
  self.runf(self.f(64000,2),'pending','new')
  for event in self.q.queue:screen.update(*event)
  self.assertEqual(screen.groups,{})

 def test_model_barrier_on_continuous_audio(self):
  from hebrew_live.feed import inference
  from hebrew_live.model_selection import ModelChange
  switches=[];self.e.switch_models=lambda selection:switches.append(selection)
  self.results=[('old','accepted'),('new','accepted')]
  self.inbox.put(self.f(32000,1,True,'silence'))
  self.inbox.put_model_change(ModelChange(dict(asr='turbo',translation='milmmt')))
  self.inbox.put(self.f(64000,1,True,'silence',start=32000,sid=2,settings=replace(self.settings,models=('turbo','milmmt'))))
  self.inbox.finish();errors=queue.Queue()
  inference(self.inbox,self.e,self.q,threading.Event(),errors,self.log,self.cancel)
  self.assertTrue(errors.empty());self.assertEqual(len(switches),1);self.assertEqual(self.mt,['old','new'])
  np.testing.assert_array_equal(np.concatenate(self.pcm),self.audio[:64000])
 def test_direction_resets_group_and_coordinates(self):
  self.prime();oldid=self.p.sid;self.p.flush('direction')
  self.settings=replace(self.settings,direction='ru-he',language='ru',generation=1)
  self.runf(self.f(32000),'other');self.assertNotEqual(oldid,self.p.sid)
  self.assertEqual(self.pubs()[-1]['start'],0.);self.assertEqual(self.mt,['first','other'])

class ConfigTests(unittest.TestCase):
 def test_strict_boolean_and_preservation(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'preferences.json';path.write_text('{}')
   self.assertFalse(preferences.read(folder)['draft_catchup_enabled'])
   preferences.save(folder,draft_catchup_enabled=True);preferences.save(folder,draft_max_audio_seconds=30.)
   self.assertTrue(preferences.read(folder)['draft_catchup_enabled']);before=path.read_bytes()
   for bad in (1,0,'false',None,[],{}):
    with self.assertRaisesRegex(ValueError,'boolean'):preferences.save(folder,draft_catchup_enabled=bad)
    self.assertEqual(path.read_bytes(),before)
    path.write_text(json.dumps({'draft_catchup_enabled':bad}))
    with self.assertRaisesRegex(ValueError,'boolean'):preferences.read(folder)
    path.write_bytes(before)
