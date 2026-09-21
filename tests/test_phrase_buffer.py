import unittest,queue,threading,time,tempfile
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from hebrew_live.phrase_buffer import PhraseBuffer,ending,punctuation
from hebrew_live.phrase_inference import PhraseProcessor
from hebrew_live.cli import Inbox,Fragment,segment
from hebrew_live.stream import Settings,AudioBlock,Boundary
from hebrew_live.feed import inference
from hebrew_live.translation import prompt,configure

def words(text,start=0):
 return [dict(word=(' ' if i else '')+w,start=start+i*.3,end=start+(i+1)*.3) for i,w in enumerate(text.split())]
class Log:
 def __init__(self):self.events=[]
 def event(self,name,**kwargs):self.events.append((name,kwargs))
 def error(self,*a):pass
class PhraseTests(unittest.TestCase):
 def test_sentence_then_open_tail_does_not_publish_twice(self):
  b=PhraseBuffer();w=words('מחר תביא מחברת. אבל הספר לא');b.update(w,0,3,1);self.assertEqual(b.take(3),[])
  b.update(w,0,3.2,1);u=b.take(3.2);self.assertEqual([x.source for x in u],['מחר תביא מחברת.'])
  b.update(words('מחר תביא מחברת. אבל הספר לא נחוץ.'),0,3.5,1,True)
  u=b.take(3.5,quiet=.6,final=True);self.assertEqual([x.source for x in u],['אבל הספר לא נחוץ.'])
 def test_tail_crosses_window_and_pause(self):
  b=PhraseBuffer();b.update(words('ההתחייבות עדיין'),0,1,1,True);self.assertEqual(b.take(1,quiet=.7,final=True),[])
  b.update(words('לא אושרה.'),1,2,2,True);u=b.take(2,.7,final=True)
  self.assertEqual(u[0].source,'ההתחייבות עדיין לא אושרה.')
  self.assertEqual(u[0].fragments,[1,2])
 def test_actual_repeated_words_survive(self):
  b=PhraseBuffer();b.update(words('כן כן כן.'),0,1.2,1,True)
  self.assertEqual(b.take(1.2,quiet=.6,final=True)[0].source,'כן כן כן.')
 def test_expired_unconfirmed_tail_cannot_block_later_windows(self):
  b=PhraseBuffer();b.update(words('עוד'),0,1,1)
  self.assertEqual(b.take(1),[])
  b.update(words('נדבר מחר.'),10,11,2,True)
  units=b.take(11,quiet=.6,final=True)
  self.assertEqual([u.source for u in units],['עוד נדבר מחר.'])
  self.assertTrue(units[0].unconfirmed)
  self.assertEqual(units[0].fragments,[1,2])
  self.assertEqual(b.take(12),[])
  b.update(words('תודה.'),12,13,3,True)
  self.assertEqual([u.source for u in b.take(13,quiet=.6,final=True)],['תודה.'])
 def test_overlapping_unconfirmed_tail_can_still_be_revised(self):
  b=PhraseBuffer();b.update(words('אולי'),0,1,1)
  b.update(words('מחר ניפגש.'),0,2,1,True)
  units=b.take(2,quiet=.6,final=True)
  self.assertEqual(units[0].source,'מחר ניפגש.')
  self.assertFalse(units[0].unconfirmed)
 def test_negation_revision_before_publish(self):
  b=PhraseBuffer();b.update(words('הוא אישר'),0,1,1);b.update(words('הוא לא אישר.'),0,1.4,1,True)
  self.assertEqual(b.take(1.4,quiet=.6,final=True)[0].source,'הוא לא אישר.')
 def test_deadline_marks_incomplete_and_stop_releases_tail(self):
  b=PhraseBuffer();b.update(words('אני חושב אבל'),0,1,1,True)
  self.assertEqual(b.take(5),[])  # No confirmed boundary or two-word lookahead.
  u=b.take(5,force='eof')[0];self.assertEqual(u.source,'אני חושב אבל');self.assertTrue(u.incomplete)
 def test_short_no_and_decimal_quotes(self):
  b=PhraseBuffer();b.update(words('לא'),0,.5,1,True);self.assertEqual(b.take(.5,.6,final=True)[0].reason,'short_reply')
  self.assertFalse(punctuation(words('3. 14'),0));self.assertFalse(punctuation(words('ולכן...'),0))
  self.assertTrue(punctuation(words('«שלום!»'),0))
 def test_timestamp_shift_of_committed_prefix(self):
  b=PhraseBuffer();b.update(words('שלום.'),0,.5,1,True);b.take(.5,quiet=.6,final=True)
  b.update(words('שלום. שלום.',.1),0,1,1,True)
  self.assertEqual([u.source for u in b.take(1,quiet=.6,final=True)],['שלום.'])
 def test_40_causal_sequences(self):
  # Separate lexical fixtures with two known stable ASR snapshots; no future input.
  fixtures=[('מחר','יום ראשון'),('המחיר','עשרים שקלים'),('התור','בשעה שמונה'),('הדלת','עדיין סגורה'),('הספר','על השולחן'),('השליח','בדרך לכאן'),('הילדים','בבית היום'),('התשלום','כבר התקבל'),('החדר','נמצא למעלה'),('הבקשה','לא אושרה'),('העבודה','עוד לא הסתיימה'),('הבדיקה','ביום שלישי'),('הכרטיס','אצל המזכירה'),('הכתובת','כתובה בהודעה'),('המספר','חמש עשרה'),('הרופא','לא הגיע'),('החבילה','לא נפתחה'),('הדוח','נשלח אתמול'),('האוטובוס','מגיע בעשר'),('האישור','עדיין לא הגיע')]
  for left,right in fixtures:
   for noise in (False,True):
    b=PhraseBuffer();s=left+' '+right+'.';w=words(s)
    b.update(words(left+' אולי') if noise else w,0,2,1)
    b.update(w,0,2.5,1)
    if noise:b.update(w,0,3,1)
    got=b.take(3)
    self.assertEqual(' '.join(x.source for x in got),s)
 def test_milmmt_prompt_and_eos_are_not_hy_chat(self):
  class Tokenizer:
   def encode(self,s,add_special_tokens):self.value=s;self.special=add_special_tokens;return [1]
   def apply_chat_template(self,*a,**kw):raise AssertionError('MiL must not use chat')
  t=Tokenizer();configure(t,'milmmt');prompt(t,'milmmt','שלום','he-ru');self.assertEqual(t.eos_token_ids,{1,106});self.assertFalse(t.special)
  self.assertEqual(t.value,'Translate this from Hebrew to Russian:\nHebrew: שלום\nRussian:')
  prompt(t,'milmmt','Привет','ru-he');self.assertIn('Russian to Hebrew',t.value)
 def test_boundary_flushes_old_generation_and_mode(self):
  events=queue.Queue();log=Log();engine=SimpleNamespace(translation_context=[],mx=SimpleNamespace(get_peak_memory=lambda:0))
  engine.translate=lambda s:iter([('Уже ',None),('видно','stop')])
  pp=PhraseProcessor(engine,events,log,threading.Event());pp.settings=Settings(mode='phrases');pp.last=SimpleNamespace(end=time.monotonic(),offset=1);pp.buffer.update(words('אבל'),0,1,1,True)
  pp.flush('clear');items=list(events.queue);self.assertEqual(items[0][0],'context');self.assertEqual(items[0][2].generation,0)
  self.assertTrue(any(x[0]=='group_final' for x in items));self.assertFalse(pp.buffer.pending)
 def test_segment_sends_control_even_after_silence_closed_audio(self):
  raw=queue.Queue();box=Inbox();errors=queue.Queue();settings=Settings(mode='phrases',timing=(1.5,1,0,4,.6))
  raw.put(AudioBlock(np.ones(16000),time.monotonic(),1,settings));raw.put(AudioBlock(np.zeros(16000),time.monotonic(),2,settings));raw.put(Boundary(settings,'pause'));raw.put(None)
  segment(raw,box,lambda a:float(np.max(a)),threading.Event(),Log(),errors)
  self.assertTrue(errors.empty(),list(errors.queue));items=[]
  while (x:=box.get()) is not None:items.append(x)
  self.assertTrue(any(isinstance(x,Boundary) and x.reason=='pause' for x in items))

class PhraseContractTests(unittest.TestCase):
 def test_unstable_continuation_does_not_detach_negation_at_deadline(self):
  b=PhraseBuffer();b.update(words('לא.'),0,1,1)
  b.update(words('לא. להתקשר היום'),0,5,1)
  self.assertEqual(b.take(5),[])
  b.update(words('לא להתקשר היום.'),0,6,1,True)
  self.assertEqual(b.take(6,quiet=.6,final=True)[0].source,'לא להתקשר היום.')
 def test_final_correction_is_separate_and_punctuation_is_ignored(self):
  q=queue.Queue();log=Log();e=SimpleNamespace(mx=SimpleNamespace(get_peak_memory=lambda:0))
  e.translate=lambda text:iter([('Готово','stop')])
  pp=PhraseProcessor(e,q,log,threading.Event());settings=Settings(mode='phrases',timing=(1.5,1,0,4,.6))
  f=Fragment(1,1,np.zeros(32000),0,time.monotonic(),False,settings,2,0)
  e.recognition_words=words('אני עובד.');e.recognize=lambda *a,**kwargs:'אני עובד.'
  pp.process(f);pp.process(f)
  self.assertEqual(sum(k=='group_final' for k,_,_ in q.queue),1)
  e.recognition_words=words('אני לומד.');e.recognize=lambda *a,**kwargs:'אני לומד.'
  from dataclasses import replace
  pp.process(replace(f,final=True))
  finals=[v for k,_,v in q.queue if k=='group_final']
  self.assertEqual(finals[0]['source'],'אני עובד.')
  self.assertEqual(finals[1]['source'],'אני לומד.')
  self.assertEqual(finals[1]['correction_of'],(1000001,))
  self.assertEqual(sum(k=='phrase_first_visible' for k,v in log.events),2)
 def test_single_word_completion_has_first_visible_metric(self):
  e=SimpleNamespace(translate=lambda s:iter([('Нет','stop')]))
  pp=PhraseProcessor(e,queue.Queue(),Log(),threading.Event());pp.settings=Settings(mode='phrases');pp.last=SimpleNamespace(end=time.monotonic(),offset=1)
  b=PhraseBuffer();b.update(words('לא'),0,1,1,True)
  pp.translate(b.take(1,.7,final=True)[0])
  self.assertEqual(sum(k=='phrase_first_visible' for k,v in pp.log.events),1)
 def test_source_is_published_before_translation_starts(self):
  q=queue.Queue();log=Log()
  def translate(source):
   progress=[v for k,_,v in q.queue if k=='group_progress']
   self.assertEqual(len(progress),1)
   self.assertEqual(progress[0]['source'],source)
   self.assertEqual(progress[0]['translation'],'')
   self.assertIsNone(progress[0]['first_delay'])
   self.assertFalse(any(k=='phrase_first_visible' for k,_ in log.events))
   return iter([('Привет','stop')])
  pp=PhraseProcessor(SimpleNamespace(translate=translate),q,log,threading.Event())
  pp.settings=Settings(mode='phrases');pp.last=SimpleNamespace(end=time.monotonic(),offset=1)
  b=PhraseBuffer();b.update(words('שלום.'),0,1,1,True);pp.translate(b.take(1,quiet=.6,final=True)[0])
  self.assertEqual(sum(k=='phrase_source_visible' for k,_ in log.events),1)
  self.assertEqual(sum(k=='phrase_first_visible' for k,_ in log.events),1)
 def test_future_preferences_schema_is_not_silently_read(self):
  import json
  from hebrew_live.preferences import read,save
  with tempfile.TemporaryDirectory() as folder:
   Path(folder,'preferences.json').write_text(json.dumps({'schema_version':99}))
   with self.assertRaises(ValueError):read(folder)
 def test_source_saved_when_translation_fails(self):
  from hebrew_live.session import Session
  class Engine:
   def translate(self,s):raise RuntimeError('test translation failure')
  with tempfile.TemporaryDirectory() as folder:
   s=Session(Path(folder),'he-ru',{})
   pp=PhraseProcessor(Engine(),queue.Queue(),s,threading.Event());pp.settings=Settings(mode='phrases');pp.last=SimpleNamespace(end=time.monotonic(),offset=1);pp.part=s.parts[1]
   b=PhraseBuffer();b.update(words('שלום.'),0,1,1,True)
   with self.assertRaises(RuntimeError):pp.translate(b.take(1,quiet=.6,final=True)[0])
   s.close();text=(s.path/'001-he-ru.transcript.txt').read_text();target=(s.path/'001-he-ru.translation.txt').read_text()
   self.assertIn('שלום.',text);self.assertEqual(text.count('[1000001'),1);self.assertIn('Ошибка перевода',target)

class PhraseFilesTests(unittest.TestCase):
 def test_unconfirmed_fallback_is_labelled_without_changing_model_input(self):
  from hebrew_live.session import Session
  from hebrew_live.display import TranslationScreen
  with tempfile.TemporaryDirectory() as folder:
   session=Session(Path(folder),'he-ru',{});q=queue.Queue();calls=[]
   def translate(source):calls.append(source);return iter([('Ещё поговорим завтра.','stop')])
   pp=PhraseProcessor(SimpleNamespace(translate=translate),q,session,threading.Event())
   pp.settings=Settings(mode='phrases');pp.last=SimpleNamespace(end=time.monotonic(),offset=11);pp.part=session.parts[1]
   b=PhraseBuffer();b.update(words('עוד'),0,1,1);b.update(words('נדבר מחר.'),10,11,2,True)
   pp.translate(b.take(11,quiet=.6,final=True)[0]);session.close()
   self.assertEqual(calls,['עוד נדבר מחר.'])
   screen=TranslationScreen()
   for kind,sid,value in q.queue:screen.update(kind,sid,value)
   result=next(iter(screen.groups.values()))['final']
   self.assertIn('не подтверждена',result['source_warning'])
   for suffix in ['transcript','translation']:
    text=(session.path/f'001-he-ru.{suffix}.txt').read_text()
    self.assertEqual(text.count('[1000001'),1)
    self.assertIn('не подтверждена',text)
 def test_clear_and_direction_flush_old_tail_to_old_files(self):
  from dataclasses import replace
  from hebrew_live.session import Session
  from hebrew_live.display import TranslationScreen
  with tempfile.TemporaryDirectory() as folder:
   session=Session(Path(folder),'he-ru',{});session.add(2,'ru-he')
   calls=[]
   class Engine:
    def recognize(self,a,p,**kwargs):
     self.recognition_words=words('אני לא' if self.language=='he' else 'Привет.')
     return ' '.join(w['word'] for w in self.recognition_words)
    def translate(self,text):
     calls.append((self.language,self.direction,text))
     yield ('Я не' if self.language=='he' else 'שלום.'),'stop'
   old=Settings(mode='phrases',timing=(1.5,1,0,4,.6));new=replace(old,part=2,generation=1,direction='ru-he',language='ru')
   box=Inbox();q=queue.Queue();errors=queue.Queue()
   box.put(Fragment(1,1,np.zeros(16000),0,time.monotonic(),True,old,1,.7,'silence'))
   box.put_boundary(Boundary(new,'clear'))
   box.put(Fragment(2,1,np.zeros(16000),0,time.monotonic(),True,new,1,.7,'eof'));box.finish()
   inference(box,Engine(),q,threading.Event(),errors,session)
   self.assertTrue(errors.empty());session.close()
   screen=TranslationScreen();screen.clear(1)
   for kind,sid,value in list(q.queue):
    if kind not in ('done','lag'):screen.update(kind,sid,value)
   self.assertEqual(len(screen.groups),1)
   self.assertEqual(calls,[('he','he-ru','אני לא'),('ru','ru-he','Привет.')])
   a=(session.path/'001-he-ru.transcript.txt').read_text();b=(session.path/'002-ru-he.transcript.txt').read_text()
   self.assertIn('אני לא',a);self.assertNotIn('Привет',a);self.assertIn('Привет.',b);self.assertNotIn('אני',b)
 def test_unrecognized_final_is_visible_and_saved_without_translation_call(self):
  from hebrew_live.session import Session
  with tempfile.TemporaryDirectory() as folder:
   session=Session(Path(folder),'he-ru',{});q=queue.Queue()
   e=SimpleNamespace(recognize=lambda *a,**kwargs:'',recognition_words=[],translate=lambda s:(_ for _ in ()).throw(AssertionError('Do not translate an ASR error')))
   p=PhraseProcessor(e,q,session,threading.Event());p.process(Fragment(1,1,np.zeros(16000),0,time.monotonic(),True,Settings(mode='phrases'),1,.7,'eof'));session.close()
   self.assertIn('Речь не распознана',(session.path/'001-he-ru.translation.txt').read_text())
   self.assertTrue(any(k=='group_final' for k,s,v in q.queue))
 def test_cancel_keeps_already_published_prefix_and_original(self):
  from hebrew_live.session import Session
  with tempfile.TemporaryDirectory() as folder:
   session=Session(Path(folder),'he-ru',{});cancel=threading.Event()
   class Engine:
    def translate(self,s):
     yield 'Уже ',None
     cancel.set();yield 'готово','stop'
   p=PhraseProcessor(Engine(),queue.Queue(),session,cancel);p.settings=Settings(mode='phrases');p.last=SimpleNamespace(end=time.monotonic(),offset=1);p.part=session.parts[1]
   b=PhraseBuffer();b.update(words('שלום.'),0,1,1,True);p.translate(b.take(1,quiet=.6,final=True)[0]);session.close()
   text=(session.path/'001-he-ru.translation.txt').read_text();self.assertIn('Уже',text);self.assertIn('Отменено',text)

class OfflineRuntimeTests(unittest.TestCase):
 def test_package_disables_onnx_uploader_before_runtime_import(self):
  import subprocess,sys,os
  env=dict(os.environ);env.pop('ORT_DISABLE_TELEMETRY',None)
  code="import sys, os; import hebrew_live; assert os.environ['ORT_DISABLE_TELEMETRY']=='1'; assert 'onnxruntime' not in sys.modules"
  subprocess.run([sys.executable,'-c',code],env=env,check=True)
