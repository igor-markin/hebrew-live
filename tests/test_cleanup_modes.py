"""Only phrases remains; old preferences migrate without losing user values."""
import json,queue,threading,tempfile,unittest,urllib.request,urllib.error,subprocess,sys,os
from pathlib import Path
from hebrew_live.preferences import read,save
from hebrew_live.stream import Settings
from hebrew_live.tuning import DEFAULTS,as_dict
from hebrew_live.browser_ui import BrowserUI
from hebrew_live.cli import Fragment,Inbox
from hebrew_live.feed import inference

class CleanupTests(unittest.TestCase):
 def test_old_preferences_read_without_write_or_timing_model_changes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'preferences.json'
   for mode in ('both','full','blocks','pauses'):
    data=dict(schema_version=2,mode=mode,timing=as_dict(DEFAULTS),models=dict(asr='multilingual',translation='7b'))
    p.write_text(json.dumps(data));before=p.read_bytes();m=read(d)
    self.assertEqual(m['mode'],'phrases');self.assertEqual(m['timing'],data['timing']);self.assertEqual(m['models'],dict(asr='multilingual',translation='milmmt'));self.assertIn('no longer supported',m['preference_notices'][0]);self.assertEqual(p.read_bytes(),before)
    with self.assertRaises(ValueError):save(d,mode=mode)
    self.assertEqual(p.read_bytes(),before)
    save(d,mode='phrases');self.assertEqual(read(d)['models'],dict(asr='multilingual',translation='milmmt'));self.assertNotIn('preference_notices',read(d))
 def test_browser_rejects_retired_modes_and_has_no_mode_selector(self):
  with BrowserUI(open_browser=False) as ui:
   try:
    with urllib.request.urlopen(ui.url) as r:html=r.read().decode()
    self.assertNotIn('id="translation-mode"',html);self.assertIn('Режим: Связные фразы',html)
    for mode in ('both','full','blocks','pauses','phrases'):
     request=urllib.request.Request(ui.url+'action',data=json.dumps(dict(action='settings',values=as_dict(DEFAULTS),mode=mode)).encode(),headers={'Content-Type':'application/json','Origin':'http://'+ui.host})
     if mode=='phrases':
      with urllib.request.urlopen(request) as r:self.assertEqual(r.status,200)
     else:
      with self.assertRaises(urllib.error.HTTPError) as c:urllib.request.urlopen(request)
      self.assertEqual(c.exception.code,400);self.assertTrue(ui.actions.empty())
   finally:ui.finished_seen.set()
 def test_worker_refuses_retired_path_before_asr(self):
  class Log:
   def error(self,*a):pass
   def event(self,*a,**k):pass
  for mode in ('both','full','blocks','pauses'):
   box=Inbox();box.put(Fragment(1,1,None,0,0,True,Settings(mode=mode)));box.finish();errors=queue.Queue();updates=queue.Queue()
   inference(box,object(),updates,threading.Event(),errors,Log())
   self.assertIsInstance(errors.get_nowait(),ValueError);self.assertEqual(updates.get_nowait()[0],'done')
 def test_cli_rejects_retired_flags_before_loading_models(self):
  for flags in (['--translation-mode','full'],['--processing','stable'],['--language-check','always'],['--translation-size','7b']):
   p=subprocess.run([sys.executable,'-B','-m','hebrew_live.cli','listen',*flags],text=True,capture_output=True)
   self.assertEqual(p.returncode,2,p.stderr)
   self.assertNotIn('Loading and warming',p.stderr)
  p=subprocess.run([sys.executable,'-B','-m','hebrew_live.cli','setup','--include-optional-7b'],text=True,capture_output=True)
  self.assertEqual(p.returncode,2,p.stderr);self.assertIn('unrecognized arguments',p.stderr)
