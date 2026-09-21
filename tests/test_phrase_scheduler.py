import unittest,queue,threading,time
from types import SimpleNamespace
from unittest.mock import patch
from dataclasses import replace
import numpy as np
from hebrew_live.cli import Inbox,Fragment
from hebrew_live.stream import Settings,Boundary
from hebrew_live.phrase_inference import PhraseProcessor
from hebrew_live.phrase_buffer import Unit

class SchedulerTests(unittest.TestCase):
 def setUp(self):
  self.events=[];self.calls=[]
  self.log=SimpleNamespace(event=lambda k,**v:self.events.append((k,v)))
  self.e=SimpleNamespace(translate=lambda s:self.generate(s))
  self.q=queue.Queue();self.pp=PhraseProcessor(self.e,self.q,self.log,threading.Event())
  self.pp.settings=Settings(mode='phrases');self.pp.last=SimpleNamespace(end=time.monotonic(),offset=1)
 def generate(self,s):
  self.calls.append((s,self.e.direction));yield 'Перевод','stop'
 def unit(self,s):return Unit(s,[dict(word=s,start=0,end=1,fragment=1,stable=True)],'sentence')
 def test_captured_settings_and_audio_anchor_do_not_follow_latest_asr(self):
  self.pp.enqueue(self.unit('first'));old=self.pp.jobs[0]
  self.pp.settings=Settings(part=2,direction='ru-he',language='ru',generation=2);self.pp.last=SimpleNamespace(end=time.monotonic(),offset=20)
  self.pp.translate_next()
  self.assertEqual(self.calls,[('first','he-ru')]);self.assertEqual(self.pp.settings.part,2)
  context=next(v for k,_,v in self.q.queue if k=='context');self.assertEqual(context,old.settings)
  metric=next(v for k,v in self.events if k=='phrase_first_visible');self.assertLess(metric['from_start'],2)
 def test_fifo_dependency_and_no_lost_units_at_flush(self):
  for s in ['one','two','three']:self.pp.enqueue(self.unit(s))
  self.pp.translate_next();self.pp.flush('direction')
  self.assertEqual([s for s,_ in self.calls],['one','two','three']);self.assertFalse(self.pp.jobs)
  ids=[sid for k,sid,_ in self.q.queue if k=='group_final'];self.assertEqual(len(set(ids)),3)
 def test_cancel_preserves_already_published_and_drops_waiting_jobs(self):
  self.pp.enqueue(self.unit('one'));self.pp.enqueue(self.unit('two'));self.pp.translate_next()
  before=list(self.q.queue);self.pp.cancel.set();self.pp.drain()
  self.assertEqual(list(self.q.queue),before);self.assertFalse(self.pp.jobs);self.assertEqual(len(self.calls),1)
 def test_age_policy_and_control_barrier(self):
  inbox=Inbox();f=Fragment(1,1,np.zeros(16000),0,100,False,Settings(mode='phrases'),1)
  with patch('hebrew_live.cli.time.monotonic',return_value=100):inbox.put(f)
  with patch('hebrew_live.cli.time.monotonic',return_value=102):
   self.assertTrue(inbox.asr_due_before_translation(101))
   self.assertFalse(inbox.asr_due_before_translation(95))
   inbox.put_boundary(Boundary(Settings(),'clear'));self.assertFalse(inbox.asr_due_before_translation(101))
 def test_final_revision_keeps_queued_parent_before_correction(self):
  from hebrew_live.phrase_buffer import lexical
  self.e.recognition_status='accepted';self.e.recognition_words=[dict(word='שלום.',start=0,end=.3)]
  self.e.recognize=lambda *a,**kwargs:'שלום.'
  f=Fragment(1,1,np.zeros(32000),0,time.monotonic(),False,Settings(mode='phrases'),2)
  self.pp.process(f,True);self.pp.process(f,True)
  self.assertEqual(len(self.pp.jobs),1)
  self.e.recognition_words=[dict(word='תודה.',start=0,end=.3)];self.e.recognize=lambda *a,**kwargs:'תודה.'
  self.pp.process(replace(f,final=True),True)
  self.assertEqual(len(self.pp.jobs),2);self.assertEqual(self.pp.jobs[1].unit.correction_of,(self.pp.jobs[0].sid,))
  self.pp.drain();self.assertEqual([s for s,_ in self.calls],['שלום.','תודה.'])

class WorkerSchedulingTests(unittest.TestCase):
 def run_policy(self,policy,boundary=None):
  from hebrew_live.feed import inference
  from hebrew_live.model_selection import ModelChange
  trace=[];box=Inbox();settings=Settings(mode='phrases',timing=(1.5,1,0,4,.6))
  f1=Fragment(1,1,np.zeros(32000),0,time.monotonic(),True,settings,2,.6,'silence')
  f2=Fragment(2,1,np.zeros(32000),0,time.monotonic(),True,settings,4,.6,'silence')
  class Engine:
   phrase_scheduler=policy;recognition_status='accepted'
   def recognize(self,a,p,**kwargs):
    self.n=getattr(self,'n',0)+1
    trace.append('prime' if self.n==1 else 'asr'+str(self.n-1))
    if self.n==1:box.put(f1)  # A second accepted hypothesis confirms punctuation.
    texts=['one.','two.'] if self.n<=2 else ['three.']
    self.recognition_words=[dict(word=w,start=i*.9,end=i*.9+.3) for i,w in enumerate(texts)]
    return ' '.join(texts)
   def translate(self,text):
    trace.append('mt:'+text)
    if text=='one.':
     if boundary=='models':box.put_model_change(ModelChange({'asr':'turbo','translation':'milmmt'}))
     elif boundary:box.put_boundary(Boundary(settings,boundary))
     box.put(f2);f2.queued_at=time.monotonic()-3;box.finish()
    yield 'Готово','stop'
   def switch_models(self,selection):trace.append('models')
  log=SimpleNamespace(event=lambda *a,**k:None,error=lambda *a:None)
  box.put(replace(f1,revision=0,final=False,quiet=0,reason=''));box.finish();errors=queue.Queue();updates=queue.Queue()
  inference(box,Engine(),updates,threading.Event(),errors,log)
  self.assertTrue(errors.empty(),list(errors.queue));return [t for t in trace if t!='prime'],list(updates.queue)
 def test_age_reconsiders_asr_between_mt_units(self):
  a,_=self.run_policy('batch');b,_=self.run_policy('age')
  self.assertEqual(a[:4],['asr1','mt:one.','mt:two.','asr2'])
  self.assertEqual(b[:4],['asr1','mt:one.','asr2','mt:two.'])
  self.assertEqual(sorted(a),sorted(b))
 def test_control_boundaries_do_not_overtake_ready_translations(self):
  for boundary in ('clear','pause','direction','models'):
   trace,updates=self.run_policy('age',boundary)
   self.assertLess(trace.index('mt:two.'),trace.index('asr2'))
   if boundary=='models':self.assertLess(trace.index('mt:two.'),trace.index('models'))
   self.assertEqual(sum(k=='group_final' for k,_,_ in updates),3)
