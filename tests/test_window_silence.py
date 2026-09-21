import queue,threading,time,unittest
from types import SimpleNamespace
import numpy as np
from hebrew_live.cli import segment
from hebrew_live.stream import AudioBlock,Settings
from hebrew_live.retranslation import RetranslationProcessor

class WindowSilenceTests(unittest.TestCase):
 def fragments(self,speech_frames=306,quiet_frames=40):
  data=np.repeat(np.r_[np.ones(speech_frames),np.zeros(quiet_frames)].astype(np.float32),512)
  raw=queue.Queue();raw.put(AudioBlock(data,time.monotonic(),len(data)/16000,Settings(timing=(1.5,1,0,4,.6),publication='revisable')));raw.put(None)
  result=[];errors=queue.Queue()
  box=SimpleNamespace(put=result.append,finish=lambda:None)
  log=SimpleNamespace(event=lambda *a,**kw:None,error=lambda *a:None)
  segment(raw,box,lambda a:float(a.max()),threading.Event(),log,errors)
  self.assertTrue(errors.empty())
  return result
 def test_window_inside_short_pause_still_emits_real_silence(self):
  finals=[f for f in self.fragments() if f.final]
  self.assertEqual([f.reason for f in finals],['window','silence'])
  self.assertAlmostEqual(finals[-1].quiet,.608)
  self.assertAlmostEqual(finals[-1].offset,(306+19)*.032)
 def test_window_does_not_zero_acoustic_pause_counter(self):
  for speech in (300,306,312):
   with self.subTest(speech=speech):
    finals=[f for f in self.fragments(speech) if f.final]
    self.assertEqual(finals[-1].reason,'silence')
    self.assertAlmostEqual(finals[-1].offset,(speech+19)*.032)
 def test_no_silence_is_invented_for_continuous_audio(self):
  finals=[f for f in self.fragments(330,0) if f.final]
  self.assertEqual([f.reason for f in finals],['window','eof'])
 def test_actual_segmenter_closes_conflicting_retranslation(self):
  q=queue.Queue();log=SimpleNamespace(event=lambda *a,**kw:None)
  e=SimpleNamespace(recognition_status='accepted',recognition_issue=None)
  e.recognize=lambda audio,*a,**kw:'ранний' if len(audio)<160000 else 'полный'
  e.translate=lambda text:iter([('Привет, как дела?' if text=='ранний' else 'Здравствуйте. Я у входа.','stop')])
  p=RetranslationProcessor(e,q,log,threading.Event())
  for f in self.fragments():p.process(f)
  result=[v for kind,_,v in q.queue if kind=='live_publication']
  self.assertEqual(result[-1]['stage'],'closed')
  self.assertEqual(result[-1]['reason'],'silence')
  self.assertEqual(result[-1]['current']['translation'],'Здравствуйте. Я у входа.')
  self.assertFalse(any(v['stage']=='unavailable' for v in result))
