import queue,threading,time,unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from hebrew_live.cli import Fragment
from hebrew_live.stream import Settings,Control,Boundary
from collections import deque
from hebrew_live.retranslation import RetranslationProcessor,common_prefix,hold_last_word,next_mt_job
from hebrew_live.display import TranslationScreen
class LiveTests(unittest.TestCase):
 def setUp(self):
  self.events=[];self.pcm=[];self.mt=[];self.saved=[];self.results=[]
  self.e=SimpleNamespace(recognize=self.recognize,translate=self.translate)
  self.q=queue.Queue();self.cancel=threading.Event()
  part=SimpleNamespace(text=lambda kind,f,text:self.saved.append((kind,f.id,text)))
  self.log=SimpleNamespace(event=lambda name,**v:self.events.append((name,v)),parts={1:part,2:part})
  self.p=RetranslationProcessor(self.e,self.q,self.log,self.cancel)
  self.settings=Settings(publication='draft');self.audio=np.arange(1000000,dtype=np.float32)/1000000
 def recognize(self,a,*args,**kw):
  self.pcm.append((a.copy(),kw));self.text,self.target,self.e.recognition_status=self.results.pop(0);return self.text
 def translate(self,text):
  self.mt.append(text);yield self.target,'stop'
 def f(self,start,end,final=False,reason='',sid=1,rev=1,settings=None):
  return Fragment(sid,rev,self.audio[start:end].copy(),0,time.monotonic(),final,settings or self.settings,end/16000,0,reason)
 def runf(self,f,text,target,status='accepted'):
  self.results.append((text,target,status));self.p.process(f)
 def pubs(self):return [v for k,_,v in self.q.queue if k=='live_publication']
 def test_live_draft_publishes_first_and_conflicting_translation(self):
  self.settings=replace(self.settings,publication='draft')
  self.runf(self.f(0,16000),'a','Она готова')
  first=self.pubs()[-1]['current'].copy()
  self.assertEqual(first['translation'],'Она готова')
  self.runf(self.f(0,32000),'b','Еда готова, горячая')
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Еда готова, горячая')
  self.assertEqual(self.pubs()[-1]['history'],[first])
  self.runf(self.f(0,48000,True,'silence'),'b','unused')
  self.assertEqual(len(self.mt),2)
  self.assertEqual(self.pubs()[-1]['stage'],'closed')
  self.assertEqual(self.pubs()[-1]['history'],[first])
 def test_streaming_translation_is_transient_and_replaced_by_verified_result(self):
  self.results.append(('שלום','unused','accepted'))
  self.e.translate=lambda text:iter([('Первый ',None),('текст ',None),('готов.','stop')])
  with patch('hebrew_live.retranslation.STREAM_PREVIEW_INTERVAL',0):
   self.p.process(self.f(0,16000))
  updates=list(self.q.queue)
  streams=[value for kind,_,value in updates if kind=='live_stream']
  self.assertEqual([value['translation'] for value in streams],['Первый','Первый текст'])
  self.assertEqual([name for name,_ in self.events].count('mt_first_preview'),1)
  self.assertEqual(len([item for item in self.saved if item[0]=='source']),2)
  screen=TranslationScreen()
  for kind,sid,value in updates:
   screen.update(kind,sid,value)
   if kind=='live_stream':self.assertEqual(screen.groups[sid]['stream']['translation'],value['translation'])
  self.assertNotIn('stream',next(iter(screen.groups.values())))
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Первый текст готов.')
  self.assertFalse(any(value['translation'] for value in self.pubs()[-1]['history']))
 def test_failed_stream_restores_previous_translation_without_archiving_preview(self):
  self.runf(self.f(0,16000),'a','Первый')
  saved_before=len(self.saved)
  self.results.append(('b','unused','accepted'))
  self.e.translate=lambda text:iter([('Неверный ',None),('текст','repetition')])
  with patch('hebrew_live.retranslation.STREAM_PREVIEW_INTERVAL',0):
   self.p.process(self.f(0,32000))
  self.assertTrue(any(kind=='live_stream_clear' for kind,_,_ in self.q.queue))
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Первый')
  self.assertEqual(len(self.saved),saved_before)
  screen=TranslationScreen()
  for item in self.q.queue:screen.update(*item)
  self.assertNotIn('stream',next(iter(screen.groups.values())))
 def test_length_limit_keeps_the_translation_with_an_explicit_marker(self):
  self.runf(self.f(0,16000),'a','Первый')
  self.results.append(('b','unused','accepted'))
  self.e.translate=lambda text:iter([('Длинный ',None),('текст','length')])
  self.p.process(self.f(0,32000))
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Длинный текст […]')
  finished=[v for n,v in self.events if n=='mt_finished'][-1]
  self.assertEqual((finished['finish_reason'],finished['truncated'],finished['issue']),('length',True,None))
 def test_length_limit_closing_version_is_published_not_unavailable(self):
  self.results.append(('a','unused','accepted'))
  self.e.translate=lambda text:iter([('Конец ',None),('обрезан','length')])
  self.p.process(self.f(0,16000,True,'silence'))
  self.assertEqual(self.pubs()[-1]['stage'],'closed')
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Конец обрезан […]')
 def test_empty_length_limit_is_still_a_failure(self):
  self.runf(self.f(0,16000),'a','Первый')
  self.results.append(('b','unused','accepted'))
  self.e.translate=lambda text:iter([('','length')])
  self.p.process(self.f(0,32000))
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Первый')
 def test_stream_clears_if_durable_publication_fails(self):
  self.results.append(('שלום','unused','accepted'))
  self.e.translate=lambda text:iter([('Новый ',None),('текст.','stop')])
  publish=self.p.publish
  def fail_target(source,target,*args,**kwargs):
   if target:raise OSError('archive full')
   return publish(source,target,*args,**kwargs)
  self.p.publish=fail_target
  with patch('hebrew_live.retranslation.STREAM_PREVIEW_INTERVAL',0):
   with self.assertRaisesRegex(OSError,'archive full'):
    self.p.process(self.f(0,16000))
  screen=TranslationScreen()
  for item in self.q.queue:screen.update(*item)
  self.assertNotIn('stream',next(iter(screen.groups.values())))
 def test_stream_clears_if_diagnostics_write_fails(self):
  self.results.append(('שלום','unused','accepted'))
  self.e.translate=lambda text:iter([('Новый ',None),('текст.','stop')])
  event=self.log.event
  def fail_mt(name,**values):
   if name=='live_mt':raise OSError('diagnostics full')
   return event(name,**values)
  self.log.event=fail_mt
  with patch('hebrew_live.retranslation.STREAM_PREVIEW_INTERVAL',0):
   with self.assertRaisesRegex(OSError,'diagnostics full'):
    self.p.process(self.f(0,16000))
  screen=TranslationScreen()
  for item in self.q.queue:screen.update(*item)
  self.assertNotIn('stream',next(iter(screen.groups.values())))
 def test_draft_skips_word_alignment_for_partials_and_finals(self):
  self.e.backend='turbo'
  self.assertTrue(self.p.text_only_draft)
  self.runf(self.f(0,16000),'a','Один')
  self.runf(self.f(0,32000,True,'silence'),'a','unused')
  self.assertEqual([kw['align_words'] for _,kw in self.pcm],[False,False])
  self.assertEqual([v['word_alignment'] for n,v in self.events if n=='live_asr'],[False,False])
 def test_other_backends_keep_word_alignment(self):
  self.e.backend='fast'
  self.runf(self.f(0,16000),'a','Один')
  self.assertEqual([kw['align_words'] for _,kw in self.pcm],[True])
 def test_environment_restores_word_alignment(self):
  with patch.dict('os.environ',{'HEBREW_LIVE_TEXT_ONLY_DRAFT':'0'}):
   p=RetranslationProcessor(self.e,self.q,self.log,self.cancel)
  self.e.backend='turbo';self.p=p
  self.runf(self.f(0,16000),'a','Один')
  self.assertEqual([kw['align_words'] for _,kw in self.pcm],[True])
 def interruptible_translation(self,pieces,waiting,at):
  produced=[];closed=[]
  def translate(text):
   try:
    for i,piece in enumerate(pieces):
     produced.append(piece)
     if i==at:waiting[0]=True
     yield piece,'stop' if i==len(pieces)-1 else None
   finally:closed.append(True)
  return translate,produced,closed
 def test_stale_refresh_is_interrupted_when_newer_audio_waits(self):
  self.runf(self.f(0,16000),'a','Первый')
  waiting=[False]
  self.p.catchup_inbox=SimpleNamespace(newer_audio_waiting=lambda f:waiting[0],take_draft_catchup=lambda *a:(None,'none'))
  self.e.translate,produced,closed=self.interruptible_translation(['Раз ','два ','три ','четыре.'],waiting,1)
  self.results.append(('b','unused','accepted'))
  with patch('hebrew_live.retranslation.STREAM_PREVIEW_INTERVAL',0):
   self.p.process(self.f(0,32000))
  self.assertEqual(produced,['Раз ','два ']);self.assertEqual(closed,[True])
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Первый')
  interrupted=[v for n,v in self.events if n=='mt_interrupted']
  self.assertEqual([v['reason'] for v in interrupted],['newer_audio_queued'])
  self.assertEqual([v['reason'] for n,v in self.events if n=='mt_discarded'][-1],'superseded_while_generating')
  screen=TranslationScreen()
  for item in self.q.queue:screen.update(*item)
  self.assertNotIn('stream',next(iter(screen.groups.values())))
 def test_closing_and_first_translations_are_never_interrupted(self):
  waiting=[True]
  self.p.catchup_inbox=SimpleNamespace(newer_audio_waiting=lambda f:waiting[0],take_draft_catchup=lambda *a:(None,'none'))
  self.e.translate,produced,closed=self.interruptible_translation(['Один ','два.'],[False],5)
  self.runf(self.f(0,16000),'a','unused')
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Один два.')
  self.e.translate,produced,closed=self.interruptible_translation(['Конец ','фразы.'],[False],5)
  self.runf(self.f(0,32000,True,'silence'),'b','unused')
  self.assertEqual(self.pubs()[-1]['stage'],'closed')
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Конец фразы.')
  self.assertFalse([1 for n,_ in self.events if n=='mt_interrupted'])
 def test_refresh_is_not_interrupted_when_visible_text_lags_four_seconds(self):
  self.runf(self.f(0,16000),'a','Первый')
  self.p.catchup_inbox=SimpleNamespace(newer_audio_waiting=lambda f:False,take_draft_catchup=lambda *a:(None,'none'))
  waiting=[True]
  self.p.catchup_inbox.newer_audio_waiting=lambda f:waiting[0]
  self.e.translate,produced,closed=self.interruptible_translation(['Раз ','два ','три.'],[False],5)
  self.results.append(('b','unused','accepted'))
  self.p.process(self.f(0,96000))
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Раз два три.')
  self.assertFalse([1 for n,_ in self.events if n=='mt_interrupted'])
 def test_environment_switch_lets_stale_refresh_finish(self):
  with patch.dict('os.environ',{'HEBREW_LIVE_MT_INTERRUPT':'0'}):
   self.p=RetranslationProcessor(self.e,self.q,self.log,self.cancel)
  self.runf(self.f(0,16000),'a','Первый')
  waiting=[False]
  self.p.catchup_inbox=SimpleNamespace(newer_audio_waiting=lambda f:waiting[0],take_draft_catchup=lambda *a:(None,'none'))
  self.e.translate,produced,closed=self.interruptible_translation(['Раз ','два ','три.'],waiting,0)
  self.results.append(('b','unused','accepted'))
  self.p.process(self.f(0,32000))
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Раз два три.')
 def test_hold_last_word_helper(self):
  self.assertEqual(hold_last_word('אני רוצה תור'),'אני רוצה')
  self.assertEqual(hold_last_word('שלום'),'שלום')
  self.assertEqual(hold_last_word('הלכתי הביתה.'),'הלכתי הביתה.')
  self.assertEqual(hold_last_word(''),'')
 def test_hold_last_word_applies_to_snapshots_but_not_finals_and_is_off_by_default(self):
  self.assertFalse(self.p.hold_last_word)
  with patch.dict('os.environ',{'HEBREW_LIVE_HOLD_LAST_WORD':'1'}):
   self.p=RetranslationProcessor(self.e,self.q,self.log,self.cancel)
  self.runf(self.f(0,16000),'אני רוצה תור','One')
  self.assertEqual(self.pubs()[-1]['current']['source'],'אני רוצה')
  self.runf(self.f(0,32000,True,'silence'),'אני רוצה תור לרופא','Two')
  self.assertEqual(self.pubs()[-1]['current']['source'],'אני רוצה תור לרופא')
 def test_live_draft_rejected_or_empty_does_not_erase(self):
  self.settings=replace(self.settings,publication='draft')
  self.runf(self.f(0,16000),'a','Первый черновик')
  visible=self.pubs()[-1]['current'].copy()
  self.runf(self.f(0,32000),'bad','','rejected')
  self.assertEqual(self.pubs()[-1]['current'],visible)
  self.runf(self.f(0,48000,True,'silence'),'','','empty')
  self.assertEqual(self.pubs()[-1]['current'],visible)
  self.assertEqual(self.pubs()[-1]['stage'],'unavailable')
 def test_live_draft_failed_mt_retains_previous(self):
  self.settings=replace(self.settings,publication='draft')
  self.runf(self.f(0,16000),'a','Первый черновик')
  self.runf(self.f(0,32000),'b','')
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Первый черновик')
 def test_window_overlap(self):
  self.runf(self.f(0,160000,True,'window'),'a','Мне нужно')
  self.runf(self.f(32000,192000,sid=2),'b','Мне нужен врач')
  np.testing.assert_array_equal(self.pcm[1][0],self.audio[:192000]);self.assertFalse(self.p.closed)
  self.assertEqual(self.pubs()[-1]['current']['translation'],'Мне нужен врач')
 def test_conflicting_final_replaces_atomic_pair(self):
  self.runf(self.f(0,16000),'a','Что');self.runf(self.f(0,32000),'b','Что будет')
  early=self.pubs()[-1]['current'].copy()
  self.runf(self.f(0,48000,True,'silence',rev=3),'c','Отлично. На завтра.')
  final=self.pubs()[-1];self.assertEqual(final['current']['translation'],'Отлично. На завтра.')
  self.assertEqual(final['history'],[early]);self.assertEqual(final['current']['source'],'c')
  self.p.flush();self.assertEqual(self.pubs()[-1],final)
 def test_cache_not_confirmation(self):
  self.runf(self.f(0,16000),'a','Привет');self.runf(self.f(0,32000),'a','unused')
  self.assertEqual(self.mt,['a']);self.assertEqual(self.pubs()[-1]['current']['translation'],'Привет')
  self.runf(self.f(0,48000,True,'silence'),'a','unused')
  self.assertEqual(self.mt,['a']);self.assertEqual(self.pubs()[-1]['current']['translation'],'Привет')
 def test_rejected_final(self):
  self.runf(self.f(0,16000),'a','Мне нужен врач');self.runf(self.f(0,32000),'b','Мне нужен врач завтра')
  early=self.pubs()[-1]['current'].copy();self.runf(self.f(0,48000,True,'silence'),'bad','','rejected')
  self.assertEqual(self.pubs()[-1]['stage'],'unavailable');self.assertEqual(self.pubs()[-1]['current'],early);self.assertEqual(len(self.mt),2)
  self.assertEqual(self.pubs()[-1]['issue'],'Завершённая версия недоступна; ранний текст не подтверждён')
  self.assertNotIn('unrecognized_audio',[name for name,_ in self.events])
 def test_group_without_any_early_text_reports_missing_speech(self):
  for index,status in enumerate(('rejected','empty')):
   with self.subTest(status=status):
    self.events.clear();self.e.recognition_issue=None
    self.runf(self.f(16000*index,16000*(index+1),True,'silence'),'','',status)
    last=self.pubs()[-1]
    self.assertEqual((last['stage'],last['issue']),('unavailable','Речь не распознана'))
    self.assertEqual(last['current']['source'],'')
    self.assertEqual([v['segment'] for name,v in self.events if name=='unrecognized_audio'],[self.p.sid])
    self.p.flush()
 def test_missing_speech_is_not_counted_twice_after_a_repetition_event(self):
  for index,issue in enumerate(('repeated recognition','early repeated recognition')):
   with self.subTest(issue=issue):
    self.events.clear();self.e.recognition_issue=issue
    self.runf(self.f(16000*index,16000*(index+1),True,'silence'),'','','rejected')
    self.assertEqual(self.pubs()[-1]['issue'],'Речь не распознана')
    self.assertNotIn('unrecognized_audio',[name for name,_ in self.events])
    self.p.flush()
 def test_non_hebrew_transcript_keeps_its_own_message(self):
  self.e.recognition_issue='non-Hebrew transcript'
  self.runf(self.f(0,16000,True,'silence'),'','','rejected')
  self.assertEqual(self.pubs()[-1]['issue'],'Распознан текст на другом языке; перевод пропущен')
  self.assertNotIn('unrecognized_audio',[name for name,_ in self.events])
 def test_control_not_evidence(self):
  self.runf(self.f(0,16000),'a','Скрытый черновик');self.p.flush('pause')
  self.assertEqual(self.pubs()[-1]['stage'],'unavailable');self.assertEqual(self.pubs()[-1]['current']['translation'],'Скрытый черновик')
 def test_repeat_after_pause(self):
  self.runf(self.f(0,16000,True,'silence'),'да','Да');self.runf(self.f(15000,32000,True,'silence',sid=2),'да','Да')
  self.assertEqual(len(self.mt),2);self.assertEqual(len(self.pcm[1][0]),16000)
 def test_technical_limit_retains_remainder(self):
  self.settings=replace(self.settings,draft_max_audio_seconds=2.);self.results=[('a','Один','accepted'),('b','Два','accepted')]
  self.p.process(self.f(0,48000,True,'silence',settings=self.settings))
  self.assertEqual([len(x[0]) for x in self.pcm],[32000,16000])
  np.testing.assert_array_equal(np.concatenate([x[0] for x in self.pcm]),self.audio[:48000])
  self.assertEqual([x['stage'] for x in self.pubs() if x['stage']!='open'],['technical','closed'])
  self.assertTrue(all(not x[1]['preliminary'] for x in self.pcm))
 def test_direction_coordinates(self):
  self.runf(self.f(0,16000,True,'silence'),'a','Один');self.p.flush('direction')
  self.runf(self.f(0,16000,True,'silence',settings=replace(self.settings,part=2,direction='ru-he',language='ru')),'b','שתיים')
  self.assertEqual(len(self.mt),2)
 def test_bad_overlap_fails(self):
  self.runf(self.f(0,16000),'a','Один');bad=self.f(0,32000);bad.audio[0]=123
  with self.assertRaisesRegex(ValueError,'overlap'):self.p.process(bad)
 def test_exports_paired_unique(self):
  self.runf(self.f(0,16000),'a','Один');self.runf(self.f(0,32000,True,'silence'),'b','Два')
  a=[i for k,i,_ in self.saved if k=='source'];b=[i for k,i,_ in self.saved if k=='target']
  self.assertEqual(a,b);self.assertEqual(len(set(a)),len(a))
 def test_clear_drops_late_events(self):
  self.runf(self.f(0,16000,True,'silence'),'a','Один');screen=TranslationScreen();screen.clear(1)
  for item in self.q.queue:screen.update(*item)
  self.assertFalse(screen.groups)
 def test_screen_replacement(self):
  self.runf(self.f(0,16000),'a','Что');self.runf(self.f(0,32000),'b','Что будет');self.runf(self.f(0,48000,True,'silence'),'c','Отлично')
  screen=TranslationScreen()
  for item in self.q.queue:screen.update(*item)
  self.assertEqual(next(iter(screen.groups.values()))['live']['current']['translation'],'Отлично')
 def test_switch_ordered_pause(self):
  c=Control(Settings(),threading.Event());c.switch_publication('draft');b=c.queue.get_nowait()
  self.assertIsInstance(b,Boundary);self.assertEqual(b.reason,'publication');self.assertTrue(c.paused)
  self.assertFalse(c.accept(np.zeros(10),time.monotonic()))
 def test_cancel(self):
  self.cancel.set();self.p.process(self.f(0,16000));self.assertFalse(self.events)
 def test_exact_prefix(self):
  self.assertEqual(common_prefix('Хорошо?','Хорошо, завтра'),'');self.assertEqual(common_prefix('Я не приду','Я приду'),'Я')
 def test_worker_retry_is_isolated_and_preserves_failed_group(self):
  from hebrew_live.feed import RetryRequest,inference
  box=__import__('hebrew_live.cli',fromlist=['Inbox']).Inbox();updates=queue.Queue();errors=queue.Queue()
  failed=self.f(0,16000,True,'silence');retry=self.f(0,16000,True,'retry',sid=9)
  self.results=[('','','rejected'),('שלום','Привет','accepted')]
  box.put(failed);box.put_retry(RetryRequest(retry,'0:3000001'));box.finish()
  inference(box,self.e,updates,threading.Event(),errors,self.log,self.cancel)
  self.assertTrue(errors.empty(),list(errors.queue))
  publications=[(sid,value) for kind,sid,value in updates.queue if kind=='live_publication']
  self.assertEqual(publications[0][1]['stage'],'unavailable')
  self.assertEqual(publications[0][1]['issue'],'Речь не распознана')
  self.assertNotEqual(publications[0][0],publications[-1][0])
  self.assertEqual(publications[-1][1]['current']['translation'],'Привет')
  self.assertIn(('retry_done',0,'0:3000001'),list(updates.queue))
 def test_failed_retry_then_success_and_live_keep_monotonic_groups_and_records(self):
  from hebrew_live.feed import RetryRequest,inference
  box=__import__('hebrew_live.cli',fromlist=['Inbox']).Inbox();updates=queue.Queue();errors=queue.Queue()
  failed=self.f(0,16000,True,'silence');retry1=self.f(0,16000,True,'retry',sid=9);retry2=self.f(0,16000,True,'retry',sid=10)
  ordinary=self.f(16000,32000,True,'silence',sid=11)
  self.results=[('','','rejected'),('retry-fail','unused','accepted'),('retry-success','Привет','accepted'),('ordinary','Дальше','accepted')]
  def translate(text):
   if text=='retry-fail':raise RuntimeError('mt failed')
   yield self.target,'stop'
  self.e.translate=translate
  box.put(failed);box.put_retry(RetryRequest(retry1,'0:3000001'));box.put_retry(RetryRequest(retry2,'0:3000001'));box.put(ordinary);box.finish()
  inference(box,self.e,updates,threading.Event(),errors,self.log,self.cancel)
  self.assertTrue(errors.empty(),list(errors.queue))
  publications=[(sid,value) for kind,sid,value in updates.queue if kind=='live_publication']
  self.assertEqual(publications[0][1]['stage'],'unavailable')
  self.assertEqual(publications[0][1]['issue'],'Речь не распознана')
  self.assertEqual(len({sid for sid,_ in publications}),4)
  self.assertIn('Привет',[value['current']['translation'] for _,value in publications])
  self.assertEqual(publications[-1][1]['current']['translation'],'Дальше')
  source_ids=[item for kind,item,_ in self.saved if kind=='source'];target_ids=[item for kind,item,_ in self.saved if kind=='target']
  self.assertEqual(source_ids,target_ids);self.assertEqual(len(source_ids),len(set(source_ids)))
  self.assertIn(('retry_failed',0,dict(group='0:3000001',error='Повторная обработка не удалась.')),list(updates.queue))
  self.assertIn(('retry_done',0,'0:3000001'),list(updates.queue))
if __name__=='__main__':unittest.main()

class IndependentMTTests(unittest.TestCase):
 def setUp(self):
  self.started=threading.Event();self.release=threading.Event()
  self.seen=[];self.translated=[];self.events=[];self.saved=[];self.unprocessed=[]
  self.updates=queue.Queue();self.cancel=threading.Event()
  owner=self
  class Engine:
   independent_mt=True
   backend='turbo';asr_path='test-asr';translation_size='milmmt'
   direction='he-ru';language='he';topic='none'
   recognition_status='accepted'
   def recognize(self,audio,*args,**kwargs):
    text=owner.seen.pop(0)
    owner.events.append(('asr_returned',dict(text=text)))
    return text
   def translate_for(self,text,settings):
    owner.translated.append((text,settings.direction))
    if text=='first':owner.started.set();owner.release.wait(3)
    yield 'Перевод '+text,'stop'
  self.engine=Engine()
  part=SimpleNamespace(text=lambda kind,f,text:self.saved.append((kind,f.id,text)))
  self.log=SimpleNamespace(event=lambda name,**v:self.events.append((name,v)),parts={1:part},
   note_unprocessed=lambda *args:self.unprocessed.append(args))
  self.p=RetranslationProcessor(self.engine,self.updates,self.log,self.cancel)
  self.settings=Settings(publication='draft',direction='he-ru')
  self.audio=np.ones(100000,dtype=np.float32)
 def tearDown(self):
  self.release.set()
  try:self.p.drain_mt()
  except RuntimeError:pass
  self.p.shutdown_mt()
 def f(self,start,end,final=False):
  return Fragment(1,1,self.audio[start:end].copy(),0,time.monotonic(),final,
                  self.settings,end/16000,0,'silence' if final else '')
 def pubs(self):
  return [(sid,value) for kind,sid,value in self.updates.queue if kind=='live_publication']
 def test_asr_continues_while_first_mt_runs_and_closed_groups_complete(self):
  self.seen=['first','closing','next']
  self.p.process(self.f(0,16000))
  self.assertTrue(self.started.wait(1))
  self.p.process(self.f(0,32000,True))
  self.p.process(self.f(32000,48000,True))
  self.assertEqual([v['text'] for n,v in self.events if n=='asr_returned'],['first','closing','next'])
  self.assertEqual(len(self.translated),1)
  self.release.set();self.p.flush()
  final=[v for _,v in self.pubs() if v['stage']=='closed']
  self.assertEqual([v['current']['translation'] for v in final],['Перевод closing','Перевод next'])
  self.assertEqual(len({sid for sid,_ in self.pubs()}),2)
  group=self.pubs()[0][0]
  self.assertEqual([v['current']['source'] for sid,v in self.pubs() if sid==group],
                   ['first','first','closing'])
 def test_superseded_queued_refresh_is_removed_but_closing_is_kept(self):
  self.seen=['first','old','new','closing']
  self.p.process(self.f(0,16000));self.assertTrue(self.started.wait(1))
  self.p.process(self.f(0,32000))
  self.p.process(self.f(0,48000))
  self.p.process(self.f(0,64000,True))
  self.release.set();self.p.flush()
  self.assertEqual([text for text,_ in self.translated],['first','closing'])
  self.assertEqual(self.pubs()[-1][1]['current']['translation'],'Перевод closing')
 def test_mt_worker_failure_surfaces_to_inference_thread(self):
  self.seen=['failure','closing']
  def fail(text,settings):
   self.started.set();self.release.wait(3)
   raise RuntimeError('translation failed');yield
  self.engine.translate_for=fail
  self.p.process(self.f(0,16000))
  self.assertTrue(self.started.wait(1))
  self.p.process(self.f(0,32000,True))
  self.release.set()
  with self.assertRaisesRegex(RuntimeError,'translation failed'):
   self.p.drain_mt()
  self.assertEqual(len(self.unprocessed),2)

 def test_running_refresh_is_interrupted_when_a_newer_job_for_the_group_is_queued(self):
  self.seen=['first','r1','r2']
  closed=[]
  def translate_for(text,settings):
   self.translated.append((text,settings.direction))
   try:
    if text=='r1':
     yield 'начало ',None
     self.started.set();self.release.wait(3)
     yield 'продолжение','stop'
    else:yield 'Перевод '+text,'stop'
   finally:
    if text=='r1':closed.append(True)
  self.engine.translate_for=translate_for
  self.p.process(self.f(0,16000))
  self.p.process(self.f(0,32000))
  self.assertTrue(self.started.wait(2))
  self.p.process(self.f(0,48000))
  self.release.set();self.p.flush()
  self.assertEqual(closed,[True])
  self.assertEqual([v['reason'] for n,v in self.events if n=='mt_interrupted'],['newer_mt_queued'])
  texts=[v['current']['translation'] for _,v in self.pubs()]
  self.assertNotIn('начало продолжение',texts)
  self.assertEqual(texts[-1],'Перевод r2')

class JobPriorityTests(unittest.TestCase):
 def job(self,name,group,kind):return SimpleNamespace(name=name,group=group,kind=kind)
 def drain(self,jobs,prioritize=True):
  pending=deque(jobs);order=[]
  while pending:
   job,jumped=next_mt_job(pending,prioritize);order.append((job.name,jumped))
  return order
 def test_closing_before_first_before_refresh_across_groups(self):
  jobs=[self.job('r1',1,'refresh'),self.job('f2',2,'first'),self.job('c3',3,'closing')]
  self.assertEqual(self.drain(jobs),[('c3',2),('f2',1),('r1',0)])
 def test_order_inside_a_group_is_kept(self):
  jobs=[self.job('r1',1,'refresh'),self.job('c1',1,'closing'),self.job('r2',2,'refresh')]
  self.assertEqual(self.drain(jobs),[('r1',0),('c1',0),('r2',0)])
  jobs=[self.job('f1',1,'first'),self.job('c1',1,'closing'),self.job('c2',2,'closing')]
  self.assertEqual(self.drain(jobs),[('c2',2),('f1',0),('c1',0)])
 def test_ties_keep_arrival_order(self):
  jobs=[self.job('a',1,'refresh'),self.job('b',2,'refresh'),self.job('c',3,'refresh')]
  self.assertEqual(self.drain(jobs),[('a',0),('b',0),('c',0)])
 def test_disabled_priority_is_fifo(self):
  jobs=[self.job('r1',1,'refresh'),self.job('c2',2,'closing')]
  self.assertEqual(self.drain(jobs,False),[('r1',0),('c2',0)])

class LiveTransportTests(unittest.TestCase):
 def test_ui_preview_acknowledges_current_rendered_preview_only(self):
  import json,urllib.request,tempfile
  from hebrew_live.browser_ui import BrowserUI
  received=[]
  with tempfile.TemporaryDirectory() as folder, BrowserUI(open_browser=False) as ui:
   ui.on_preview_seen=lambda event,**data:received.append((event,data))
   ui.state['groups']=[dict(id='0:3000001',part=1,stream=dict(
    preview_id='7:1',preview_emitted_at=time.monotonic()-.05))]
   def send(identity):
    request=urllib.request.Request(ui.url+'action',
     data=json.dumps(dict(action='ui_preview_seen',group='0:3000001',preview_id=identity)).encode(),
     headers={'Origin':'http://'+ui.host,'Content-Type':'application/json'})
    return urllib.request.urlopen(request)
   with send('7:1') as response:self.assertEqual(response.status,200)
   with send('7:1') as response:self.assertEqual(response.status,200)
   self.assertEqual(len(received),1)
   self.assertGreaterEqual(received[0][1]['backend_to_dom_ack'],.05)
   with self.assertRaises(__import__('urllib.error',fromlist=['HTTPError']).HTTPError):send('7:2')
   ui.finished_seen.set()
 def test_assets_and_publication_action(self):
  import json,urllib.request,urllib.error,tempfile
  from pathlib import Path
  from hebrew_live.browser_ui import BrowserUI
  with tempfile.TemporaryDirectory() as folder, BrowserUI(open_browser=False) as ui:
   ui.live_root=Path(folder)
   (ui.live_root/'live.html').write_text('<script src="./assets/test.js"></script>')
   with urllib.request.urlopen(ui.url+'live/') as response:
    self.assertIn(b'./assets/',response.read())
    policy=response.headers['Content-Security-Policy']
    self.assertIn("script-src 'self'",policy);self.assertNotIn("script-src 'self' 'unsafe-inline'",policy)
    self.assertIn("style-src 'self' 'unsafe-inline'",policy)
    self.assertIn("font-src 'self'",policy)
   for suffix in ['live/../.local-settings/preferences.json','live/%2e%2e/package.json','live/assets/missing.js']:
    with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(ui.url+suffix)
   payload=json.dumps({'action':'publication','value':'revisable'}).encode()
   request=urllib.request.Request(ui.url+'action',data=payload,headers={'Origin':'http://'+ui.host,'Content-Type':'application/json'})
   with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
   self.assertEqual(error.exception.code,400);self.assertTrue(ui.actions.empty())
   ui.finished_seen.set()
 def test_preferences_roundtrip_does_not_drop_other_settings(self):
  import tempfile
  from hebrew_live.preferences import read,save
  from hebrew_live.tuning import DEFAULTS,as_dict
  with tempfile.TemporaryDirectory() as folder:
   save(folder,timing=as_dict(DEFAULTS),models={'asr':'turbo','translation':'milmmt'})
   save(folder,publication='draft');saved=read(folder)
   self.assertEqual(saved['publication'],'draft');self.assertEqual(saved['timing'],as_dict(DEFAULTS))
   save(folder,publication='draft');self.assertEqual(read(folder)['models'],saved['models'])
 def test_control_queue_full_does_not_change_mode(self):
  c=Control(Settings(),threading.Event());c.queue=queue.Queue(maxsize=1);c.queue.put(None)
  with self.assertRaises(queue.Full):c.switch_publication('revisable')
  self.assertEqual(c.settings.publication,'phrases');self.assertFalse(c.paused)

class LiveStartupTests(unittest.TestCase):
 def test_saved_publication_selects_matching_browser_unless_cli_overrides(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import patch
  from hebrew_live.preferences import save
  from hebrew_live.cli import run
  with tempfile.TemporaryDirectory() as folder:
   models=Path(folder)/'models';settings=Path(folder)/'.local-settings';settings.mkdir();(settings/'preferences.json').write_text('{"publication":"revisable"}')
   args=SimpleNamespace(models=models,publication=None,ui='browser',command='listen',direction='he-ru',asr_backend='turbo',translation_size='milmmt',topic='none')
   calls=[]
   class Browser:
    def __init__(self,**values):calls.append(values)
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def details(self,**values):pass
    def begin_session(self,session):pass
    def wait_for_next_session(self,enabled):return False
   log=SimpleNamespace(path=folder,metadata={},close=lambda:None,error=lambda *args:None)
   with patch('hebrew_live.browser_ui.BrowserUI',Browser),patch('hebrew_live.runtime.run_session'):
    self.assertIsNone(run(args,log));self.assertTrue(calls[-1]['live'])
    args.publication='draft';run(args,log);self.assertTrue(calls[-1]['live'])
