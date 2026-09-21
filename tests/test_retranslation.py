import queue,threading,time,unittest
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
from hebrew_live.cli import Fragment
from hebrew_live.stream import Settings,Control,Boundary
from hebrew_live.retranslation import RetranslationProcessor,common_prefix
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
  self.assertEqual(len({sid for sid,_ in publications}),4)
  self.assertIn('Привет',[value['current']['translation'] for _,value in publications])
  self.assertEqual(publications[-1][1]['current']['translation'],'Дальше')
  source_ids=[item for kind,item,_ in self.saved if kind=='source'];target_ids=[item for kind,item,_ in self.saved if kind=='target']
  self.assertEqual(source_ids,target_ids);self.assertEqual(len(source_ids),len(set(source_ids)))
  self.assertIn(('retry_failed',0,dict(group='0:3000001',error='Повторная обработка не удалась.')),list(updates.queue))
  self.assertIn(('retry_done',0,'0:3000001'),list(updates.queue))
if __name__=='__main__':unittest.main()

class LiveTransportTests(unittest.TestCase):
 def test_assets_and_publication_action(self):
  import json,urllib.request,urllib.error,tempfile
  from pathlib import Path
  from hebrew_live.browser_ui import BrowserUI
  with tempfile.TemporaryDirectory() as folder, BrowserUI(open_browser=False) as ui:
   ui.live_root=Path(folder)
   (ui.live_root/'live.html').write_text('<script src="./assets/test.js"></script>')
   with urllib.request.urlopen(ui.url+'live/') as response:
    self.assertIn(b'./assets/',response.read());self.assertIn("font-src 'self'",response.headers['Content-Security-Policy'])
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
