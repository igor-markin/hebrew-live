import queue,threading,time,unittest
import numpy as np
from hebrew_live.cli import Fragment,Inbox,segment
from hebrew_live.feed import inference
from hebrew_live.stream import Settings,AudioBlock,Boundary
from hebrew_live.display import TranslationScreen
class Log:
 def event(self,*a,**k):pass
 def error(self,*a):pass
class ContextStreamTests(unittest.TestCase):
 def test_stream_screen_preserves_prefix_on_failure_and_clear(self):
  s=TranslationScreen();s.update('context',1,Settings())
  s.update('group_progress',1,dict(source='מקור',translation='Первое'))
  s.update('group_progress',1,dict(source='מקור',translation='Первое слово'))
  s.update('group_final',1,dict(source='מקור',translation='[Translation cancelled]'))
  self.assertEqual(s.groups[1]['final']['translation'],'Первое слово')
  self.assertIn('cancelled',s.groups[1]['final']['issue'])
  s.update('context',2,Settings());s.clear(1)
  s.update('group_progress',2,dict(source='ישן',translation='Старое'))
  s.update('group_final',2,dict(source='ישן',translation='Старое'))
  self.assertFalse(s.groups)
 def test_continuous_audio_context_ownership_and_boundary_reset(self):
  raw=queue.Queue();items=[];errors=queue.Queue();n=0
  settings=Settings(mode='phrases',timing=(1,1,0,3,1))
  for i in range(1020):
   x=np.arange(n,n+512,dtype=np.float32);n+=512
   raw.put(AudioBlock(x,time.monotonic(),n/16000,settings))
  raw.put(Boundary(settings,'pause'))
  raw.put(AudioBlock(np.ones(512),time.monotonic(),n/16000+.032,settings));raw.put(None)
  class Box:
   def put(self,x):items.append(x)
   def finish(self):pass
   def put_boundary(self,b):pass
  segment(raw,Box(),lambda _:1,threading.Event(),Log(),errors)
  self.assertTrue(errors.empty(),list(errors.queue))
  finals=[f for f in items if f.final]
  owned=np.concatenate([f.audio[round(f.prefix*16000):] for f in finals[:-1]])
  np.testing.assert_array_equal(owned,np.arange(n,dtype=np.float32))
  self.assertGreater(finals[2].prefix,5)
  self.assertEqual(finals[-1].prefix,0)
  self.assertTrue(all(len(f.audio)/16000-f.prefix<=10.032 for f in finals))
