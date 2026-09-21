import unittest,types,threading
from unittest.mock import patch
import numpy as np
from hebrew_live.whisper_reuse import _alignment_context,reuse_alignment

class ReuseTests(unittest.TestCase):
 def setUp(self):
  class Model:
   dims=types.SimpleNamespace(n_audio_ctx=2,n_audio_state=4)
   def __init__(self):self.calls=0
   def encoder(self,mel):self.calls+=1;return np.full((2,4),float(mel.mean()),np.float16)
   def decoder(self,tokens,features):return float(features.sum()),None,features
   def decode(self,mel):return types.SimpleNamespace(audio_features=self.encoder(mel))
   def forward_with_cross_qk(self,mel,tokens):
    a,_,b=self.decoder(tokens,self.encoder(mel));return a,b
  self.Model=Model;self.model=Model();self.mel=np.ones((4,3),np.float16)
  self.trans=types.SimpleNamespace(add_word_timestamps=lambda **kw:kw['model'].forward_with_cross_qk(kw['mel'][None,:],None)[0])
 def test_same_window_and_next_window(self):
  with _alignment_context(self.Model,self.trans) as c:
   for n in (1,2):
    mel=self.mel*n;self.model.decode(mel)
    self.assertEqual(self.trans.add_word_timestamps(model=self.model,mel=mel),8*n)
   self.assertEqual(c['reuses'],2);self.assertEqual(self.model.calls,2)
 def test_wrong_or_missing_features_fall_back_and_clear(self):
  with _alignment_context(self.Model,self.trans) as c:
   self.model.decode(self.mel)
   self.assertEqual(self.trans.add_word_timestamps(model=self.model,mel=self.mel*2),16)
   self.assertEqual(self.trans.add_word_timestamps(model=self.model,mel=self.mel),8)
   self.assertEqual(c['fallbacks'],2)
 def test_batch_decode_passthrough_and_fallback(self):
  with patch.object(self.Model,'decode',return_value=[object()]):
   with _alignment_context(self.Model,self.trans):
    self.assertIsInstance(self.model.decode(self.mel[None,:]),list)
    self.assertEqual(self.trans.add_word_timestamps(model=self.model,mel=self.mel),8)
 def test_retry_failure_discards_prior_features(self):
  decode=self.Model.decode
  def retry(model,mel):
   if mel is None:raise ValueError('decode failed')
   return decode(model,mel)
  with patch.object(self.Model,'decode',retry):
   with _alignment_context(self.Model,self.trans) as c:
    self.model.decode(self.mel)
    with self.assertRaises(ValueError):self.model.decode(None)
    self.trans.add_word_timestamps(model=self.model,mel=self.mel)
    other=self.mel*2;self.model.decode(other)
    self.assertEqual(self.trans.add_word_timestamps(model=self.model,mel=other),16)
    self.assertEqual(c['fallbacks'],1);self.assertEqual(c['reuses'],1)
 def test_exception_restores_and_is_not_retried(self):
  before=self.Model.decode,self.trans.add_word_timestamps,self.Model.forward_with_cross_qk
  with self.assertRaises(ValueError):
   with _alignment_context(self.Model,self.trans):
    self.model.decode(self.mel)
    with patch.object(self.model,'decoder',side_effect=ValueError('GPU')) as f:
     self.trans.add_word_timestamps(model=self.model,mel=self.mel)
  self.assertEqual(f.call_count,1)
  self.assertEqual(before,(self.Model.decode,self.trans.add_word_timestamps,self.Model.forward_with_cross_qk))
 def test_nested_rejected_and_other_thread_uses_original(self):
  with _alignment_context(self.Model,self.trans) as c:
   self.model.decode(self.mel)
   with self.assertRaises(RuntimeError):
    with _alignment_context(self.Model,self.trans):pass
   out=[]
   def other():
    mel=self.mel*2;self.model.decode(mel);out.append(self.trans.add_word_timestamps(model=self.model,mel=mel))
   t=threading.Thread(target=other);t.start();t.join(2);self.assertFalse(t.is_alive());self.assertEqual(out,[16])
   self.assertEqual(self.trans.add_word_timestamps(model=self.model,mel=self.mel),8);self.assertEqual(c['reuses'],1)
 def test_disabled_and_unqualified_do_not_patch(self):
  with patch('hebrew_live.whisper_reuse.compatible',return_value=False),patch('hebrew_live.whisper_reuse.importlib.import_module',side_effect=AssertionError):
   for enabled in (False,True):
    with reuse_alignment(enabled):pass
