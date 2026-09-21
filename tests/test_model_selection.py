import unittest,tempfile,threading,queue,time
from pathlib import Path
from unittest.mock import patch
import numpy as np
from hebrew_live.preferences import read,save
from hebrew_live.tuning import as_dict,DEFAULTS
from hebrew_live.stream import Control,Settings,Boundary
from hebrew_live.model_selection import ModelChange
from hebrew_live.cli import Inbox,Fragment
from hebrew_live.feed import inference
class ModelSelectionTests(unittest.TestCase):
 def test_preferences_survive_reload_and_failed_write(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'preferences.json'
   path.write_text(__import__('json').dumps(dict(schema_version=3,timing=as_dict(DEFAULTS),mode='phrases',models=dict(asr='multilingual',translation='7b'))))
   original=path.read_bytes();before=read(tmp);self.assertEqual(before['mode'],'phrases');self.assertEqual(before['timing'],as_dict(DEFAULTS))
   self.assertEqual(before['models'],dict(asr='multilingual',translation='milmmt'))
   self.assertIn('no longer supported',before['preference_notices'][0]);self.assertEqual(path.read_bytes(),original)
   with patch('hebrew_live.preferences.os.replace',side_effect=OSError('disk')):
    with self.assertRaises(OSError):save(tmp,models=dict(asr='turbo',translation='milmmt'))
   self.assertEqual(read(tmp),before);self.assertEqual(path.read_bytes(),original)
   save(tmp,models=dict(asr='multilingual',translation='milmmt'))
   self.assertNotIn('preference_notices',read(tmp))
   self.assertEqual((Path(tmp)/'preferences.json').stat().st_mode & 0o777,0o600)
 def test_switch_pauses_admission_and_preserves_direction(self):
  c=Control(Settings(direction='ru-he',language='ru'),threading.Event());a=np.ones(512)
  c.accept(a,time.monotonic());c.switch_models(dict(asr='turbo',translation='milmmt'))
  self.assertTrue(c.paused);self.assertFalse(c.accept(a,time.monotonic()))
  old=c.queue.get();boundary=c.queue.get();self.assertIsNone(old.settings.models)
  self.assertIsInstance(boundary,Boundary);self.assertEqual(boundary.settings.language,'ru')
 def test_model_command_runs_after_old_final_before_new_final(self):
  calls=[]
  class Engine:
   mx=type('MX',(),{'get_peak_memory':staticmethod(lambda:0)})
   def recognize(self,*a,**kw):calls.append('asr');self.recognition_words=[dict(word='שלום.',start=0,end=.03)];return 'שלום.'
   def translate(self,*a):calls.append('translation');yield 'Привет','stop'
   def switch_models(self,s):calls.append('switch')
  class Log:
   def event(self,*a,**kw):pass
   def error(self,*a):pass
  box=Inbox();box.put(Fragment(1,1,np.ones(512),0,time.monotonic(),True,Settings(),.032));box.put_model_change(ModelChange(dict(asr='turbo',translation='milmmt')));box.put(Fragment(2,1,np.ones(512),0,time.monotonic(),True,Settings(part=2),.032));box.finish()
  errors=queue.Queue();inference(box,Engine(),queue.Queue(),threading.Event(),errors,Log())
  self.assertTrue(errors.empty(),list(errors.queue));self.assertEqual(calls,['asr','translation','switch','asr','translation'])

 def test_boundary_flushes_before_switch_marker(self):
  from hebrew_live.cli import segment
  from hebrew_live.stream import AudioBlock
  raw=queue.Queue();box=Inbox();errors=queue.Queue()
  old=Settings();new=Settings(models=('multilingual','milmmt'))
  raw.put(AudioBlock(np.ones(16000,dtype=np.float32),time.monotonic(),1.,old))
  raw.put(Boundary(new,'models'));raw.put(None)
  class Log:
   def event(self,*a,**kw):pass
   def error(self,*a):pass
  segment(raw,box,lambda a:1,threading.Event(),Log(),errors)
  self.assertTrue(errors.empty(),list(errors.queue))
  f=box.get();self.assertTrue(f.final);self.assertEqual(len(f.audio),16000)
  self.assertIsNone(f.settings.models);self.assertIsInstance(box.get(),Boundary);self.assertIsInstance(box.get(),ModelChange)
  self.assertIsNone(box.get())
