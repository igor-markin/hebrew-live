import unittest,queue,threading,json,urllib.request,urllib.error
import numpy as np
from hebrew_live.tuning import validate,as_dict,DEFAULTS
from hebrew_live.stream import Settings,AudioBlock
from hebrew_live.cli import segment
from hebrew_live.browser_ui import BrowserUI
class TuningTests(unittest.TestCase):
 def test_invalid_settings(self):
  for key,value in [('first_seconds',float('nan')),('preview_limit',1.5),('fragment_seconds',0),('silence_seconds',True)]:
   with self.assertRaises(ValueError):validate(dict(as_dict(DEFAULTS),**{key:value}))
 def test_unrestricted_positive_values_and_disabled_preview(self):
  self.assertEqual(validate(dict(as_dict(DEFAULTS),first_seconds=.1,interval_seconds=.01,preview_limit=0,fragment_seconds=120,silence_seconds=10)),(.1,.01,0,120,10))
 def test_fragment_freezes_settings(self):
  old=(4.,4.5,2,6.,1.28);new=(2.,2.,1,4.,.5)
  raw=queue.Queue();items=[];errors=queue.Queue()
  for i in range(400):raw.put(AudioBlock(np.ones(512,dtype=np.float32),i*.032,(i+1)*.032,Settings(timing=old if i<50 else new,mode='phrases')))
  raw.put(None)
  class Box:
   def put(self,x):items.append(x)
   def finish(self):pass
  class Log:
   def event(self,*a,**kw):pass
   def error(self,*a):pass
  segment(raw,Box(),lambda f:1,threading.Event(),Log(),errors)
  self.assertTrue(errors.empty(),list(errors.queue))
  finals=[x for x in items if x.final]
  self.assertEqual(finals[0].settings.timing,old)
  self.assertAlmostEqual(len(finals[0].audio)/16000,10.,delta=.032)
  self.assertEqual(finals[1].settings.timing,new)
  self.assertEqual(finals[0].settings.mode,'phrases');self.assertEqual(finals[1].settings.mode,'phrases')
  self.assertAlmostEqual(len(finals[1].audio)/16000-finals[1].prefix,2.784,delta=.032)
  self.assertTrue(all(x.settings.timing==old for x in items if x.id==1))
 def test_settings_endpoint(self):
  with BrowserUI(open_browser=False) as ui:
   try:
    def post(values):return urllib.request.urlopen(urllib.request.Request(ui.url+'action',data=json.dumps(dict(action='settings',values=values)).encode(),headers={'Content-Type':'application/json','Origin':'http://'+ui.host}))
    with post(as_dict(DEFAULTS)) as r:self.assertEqual(r.status,200)
    self.assertEqual(ui.actions.get_nowait(),as_dict(DEFAULTS))
    with self.assertRaises(urllib.error.HTTPError) as e:post(dict(as_dict(DEFAULTS),preview_limit=-1))
    self.assertEqual(e.exception.code,400)
    self.assertTrue(ui.actions.empty())
   finally:ui.finished_seen.set()
