"""Decision budgets use fake monotonic clocks, never synthetic silence."""
import queue,threading,unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from hebrew_live.cli import Inbox,Fragment
from hebrew_live.stream import Settings,Boundary
from hebrew_live.phrase_buffer import PhraseBuffer,edge_allowed,safe_edge
from hebrew_live.phrase_inference import PhraseProcessor

class Clock:
 def __init__(self):self.now=100.
 def __call__(self):return self.now

class Deadlines(unittest.TestCase):
 def setUp(self):
  self.clock=Clock();self.events=[];self.cancel=threading.Event()
  self.engine=SimpleNamespace(phrase_deadline_budgets=(4.,6.),phrase_clock=self.clock,
      recognition_status='accepted',recognition_words=[])
  self.engine.recognize=lambda *a,**kwargs:' '.join(w['word'] for w in self.engine.recognition_words)
  self.pp=PhraseProcessor(self.engine,queue.Queue(),SimpleNamespace(event=lambda k,**v:self.events.append((k,v))),self.cancel)
  self.pp.settings=Settings(mode='phrases',timing=(1.5,1,0,4,.6))
  self.pp.last=SimpleNamespace(end=102.,offset=2.)
  self.pp.audio_origin=100.;self.pp.last_now=2.
 def seed(self,text='אני עובד היום',stable=True):
  self.pp.buffer.pending=[dict(word=w,start=i*.4,end=i*.4+.3,fragment=1,stable=stable,word_stable=stable) for i,w in enumerate(text.split())]
  self.pp.annotate_words([])
 def decisions(self):return [v for k,v in self.events if k=='phrase_deadline_decision']
 def test_deadline_does_not_infer_silence_and_blocked_does_not_spin(self):
  self.seed('על יד')
  self.clock.now=106.;self.pp.service_deadlines()
  self.assertFalse(self.pp.jobs);self.assertIsNone(self.pp.next_deadline())
  self.assertEqual(self.decisions()[-1]['decision_reason'],'blocked_open_edge')
  for _ in range(50):self.pp.service_deadlines()
  self.assertEqual(len(self.decisions()),1)
 def test_soft_waits_for_context_hard_can_emit_incomplete(self):
  self.seed();self.clock.now=104.;self.pp.service_deadlines()
  self.assertFalse(self.pp.jobs);self.assertEqual(self.pp.next_deadline(),106.)
  self.clock.now=106.;self.pp.service_deadlines()
  self.assertEqual(len(self.pp.jobs),1);self.assertTrue(self.pp.jobs[0].unit.incomplete)
  self.assertEqual(self.pp.jobs[0].unit.reason,'hard_deadline')
 def test_no_stable_prefix_is_retained_even_after_hard_budget(self):
  self.seed(stable=False);self.clock.now=110.;self.pp.service_deadlines()
  self.assertFalse(self.pp.jobs);self.assertEqual(self.decisions()[0]['decision_reason'],'no_stable_prefix')
  self.assertEqual(self.decisions()[0]['service_overrun'],4.)
 def test_revisions_do_not_restart_origin_or_continuous_stability(self):
  self.seed();old=[dict(w) for w in self.pp.buffer.pending]
  self.clock.now=105.;self.pp.buffer.pending[0].update(word='אתה',start=.15,word_stable=False,stable=False)
  self.pp.annotate_words(old);head=self.pp.buffer.pending[0]
  self.assertEqual(head['origin_at'],100.);self.assertIsNone(head['stable_since'])
  self.assertEqual(head['first_confirmed_at'],100.)
  self.assertEqual(self.pp.next_deadline(),104.)
  prior=[dict(w) for w in self.pp.buffer.pending];head.update(word_stable=True,stable=True)
  self.clock.now=107.;self.pp.annotate_words(prior)
  self.assertEqual(head['stable_since'],107.);self.assertEqual(head['origin_at'],100.)
 def test_partial_release_preserves_tail_age(self):
  self.seed('אני עובד היום בבית בשקט עכשיו')
  self.clock.now=104.;self.pp.service_deadlines()
  self.assertTrue(self.pp.jobs);tail=self.pp.buffer.pending[0]
  self.assertAlmostEqual(self.pp.next_deadline(),tail['start']+104.)
  self.assertLess(self.pp.next_deadline(),108.)
 def test_new_evidence_retries_blocked_without_new_budget(self):
  self.seed('על יד');self.clock.now=106.;self.pp.service_deadlines()
  old=[dict(w) for w in self.pp.buffer.pending]
  self.pp.buffer.pending.append(dict(word='הבית',start=1.6,end=1.9,fragment=1,word_stable=True,stable=True))
  self.pp.annotate_words(old);self.pp.service_deadlines()
  self.assertEqual(self.decisions()[-1]['deadline_at'],106.)
  self.assertTrue(self.pp.jobs)
 def test_checks_between_mt_jobs_preserve_fifo(self):
  self.seed();saved=self.pp.buffer.pending
  from hebrew_live.phrase_buffer import Unit
  for text in ('old1','old2'):
   self.pp.enqueue(Unit(text,[dict(word=text,start=0,end=.3,fragment=1)],'sentence'))
  trace=[]
  def translate(unit,*a,**k):trace.append(unit.source);self.clock.now+=3.
  self.pp.translate=translate;self.clock.now=103.;self.pp.drain()
  self.assertEqual(trace,['old1','old2','אני עובד היום'])
  self.assertEqual(self.decisions()[0]['deadline_observed_at'],106.)
 def test_barrier_and_cancel_disable_timer(self):
  self.seed();box=Inbox();self.pp.deadline_barrier=box.deadline_blocked
  box.put_boundary(Boundary(Settings(),'clear'));self.clock.now=108.
  self.pp.service_deadlines();self.assertFalse(self.decisions());self.assertIsNone(self.pp.next_deadline())
  box.get();self.cancel.set();self.assertIsNone(self.pp.next_deadline())
 def test_control_flush_invalidates_timers(self):
  self.seed();self.pp.translate=lambda *a,**k:None
  self.pp.flush('clear');self.clock.now=110.;self.pp.service_deadlines()
  self.assertFalse(self.pp.buffer.pending);self.assertIsNone(self.pp.next_deadline())
 def test_asr_finishing_late_records_actual_observation(self):
  self.engine.recognition_words=[dict(word=w,start=i*.4,end=i*.4+.3) for i,w in enumerate('אני עובד היום'.split())]
  def recognize(*a,**kwargs):self.clock.now=108.;return 'אני עובד היום'
  self.engine.recognize=recognize
  f=Fragment(1,1,np.zeros(32000),0,102.,True,self.pp.settings,2.,0.,'window')
  self.pp.process(f,defer=True)
  d=self.decisions()[0]
  self.assertEqual((d['deadline_at'],d['deadline_observed_at']),(106.,108.))
  self.assertEqual(d['service_overrun'],2.)

class Edges(unittest.TestCase):
 def words(self,text):return [dict(word=w,start=i*.3,end=i*.3+.25,stable=True,word_stable=True,fragment=1) for i,w in enumerate(text.split())]
 def test_veto_after_preposition_and_incomplete_complement(self):
  words=self.words('אפשר לשים על יד הדלת שלי')
  for cut in (3,4):
   self.assertFalse(edge_allowed(words,cut));self.assertFalse(safe_edge(words,cut,lookahead=False))
  b=PhraseBuffer(pending=words)
  units=b.take(20,deadline_policy='hard')
  self.assertTrue(units);self.assertNotIn(units[0].source,('אפשר לשים על','אפשר לשים על יד'))
 def test_hard_never_rejects_a_cut_with_sufficient_strict_context(self):
  w=self.words('לעשות משפט על את')
  soft=PhraseBuffer(pending=[dict(x) for x in w]).take(20,deadline_policy='soft')
  hard=PhraseBuffer(pending=[dict(x) for x in w]).take(20,deadline_policy='hard')
  self.assertTrue(soft);self.assertTrue(hard)
  self.assertEqual(hard[0].source,'לעשות משפט')
 def test_force_cannot_be_used_as_deadline(self):
  b=PhraseBuffer(pending=self.words('אפשר על'))
  with self.assertRaises(ValueError):b.take(20,force='hard_deadline')
  self.assertEqual(len(b.pending),2)
 def test_hard_never_takes_unstable_or_unconfirmed_retained_words(self):
  for stable in (False,True):
   w=self.words('אני עובד היום');w[1].update(stable=stable,word_stable=False,unconfirmed=True)
   b=PhraseBuffer(pending=w);self.assertFalse(b.take(10,deadline_policy='hard'))
 def test_natural_sentence_can_publish_before_four_seconds(self):
  b=PhraseBuffer(pending=self.words('אני עובד.'));b.pending[-1]['boundary_stable']=True
  self.assertEqual(b.take(1,deadline_policy='natural')[0].source,'אני עובד.')

class InboxTimeout(unittest.TestCase):
 def test_timeout_eof_and_job_are_distinct(self):
  box=Inbox()
  with patch('hebrew_live.cli.time.monotonic',return_value=10):
   self.assertIs(box.get(deadline_at=9),Inbox.TIMEOUT)
   box.put_boundary(Boundary(Settings(),'pause'));self.assertIsInstance(box.get(9),Boundary)
   box.finish();self.assertIsNone(box.get(9))
 def test_absolute_deadline_survives_spurious_wake(self):
  box=Inbox();clock=Clock();waits=[]
  def wait(seconds):waits.append(seconds);clock.now+=2.
  with patch('hebrew_live.cli.time.monotonic',clock),patch.object(box.condition,'wait',wait):
   self.assertIs(box.get(103.),Inbox.TIMEOUT)
  self.assertEqual(waits,[3.,1.])

class WorkerTimer(unittest.TestCase):
 def run_worker(self,busy=False):
  from hebrew_live.feed import inference
  clock=Clock();events=[];trace=[]
  class Box(Inbox):
   def get(self,deadline_at=None):
    if not self.finals and self.preview is None and not self.done:
     if deadline_at is None:raise AssertionError('Worker would wait indefinitely')
     trace.append(('wait',deadline_at));clock.now=deadline_at
     return self.TIMEOUT
    return super().get(deadline_at)
  box=Box();settings=Settings(mode='phrases',timing=(1.5,1,0,4,.6))
  class Engine:
   phrase_deadline_budgets=(4.,6.);phrase_clock=clock;recognition_status='accepted'
   def recognize(self,a,p,**kwargs):
    trace.append(('asr',clock.now))
    clock.now=102. if len([x for x in trace if x[0]=='asr'])==1 else 108.
    self.recognition_words=[dict(word=w,start=i*.4,end=i*.4+.3) for i,w in enumerate('אני עובד היום'.split())]
    return 'אני עובד היום'
   def translate(self,text):
    trace.append(('mt',clock.now));box.finish();yield 'Я работаю сегодня','stop'
  box.put(Fragment(1,1,np.zeros(32000),0,102.,True,settings,2.,0.,'window'))
  if busy:box.put(Fragment(1,2,np.zeros(32000),0,102.,True,settings,2.,0.,'window'))
  errors=queue.Queue()
  inference(box,Engine(),queue.Queue(),threading.Event(),errors,
            SimpleNamespace(event=lambda k,**v:events.append((k,v)),error=lambda *a:None))
  self.assertTrue(errors.empty(),list(errors.queue));return trace,events
 def test_idle_queue_wakes_without_flush_and_publishes_at_hard_decision(self):
  trace,events=self.run_worker()
  self.assertIn(('wait',104.),trace);self.assertIn(('wait',106.),trace)
  self.assertIn(('mt',106.),trace)
  units=[v for k,v in events if k=='phrase_unit'];self.assertEqual(units[0]['reason'],'hard_deadline')
 def test_nonempty_queue_and_late_asr_are_serviced_without_timeout(self):
  trace,events=self.run_worker(True)
  self.assertNotIn('wait',[k for k,v in trace]);self.assertIn(('mt',108.),trace)
  d=next(v for k,v in events if k=='phrase_deadline_decision')
  self.assertEqual(d['deadline_observed_at'],108.);self.assertEqual(d['deadline_at'],106.)
