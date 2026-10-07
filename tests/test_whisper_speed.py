import os
import types
import unittest
from unittest.mock import patch

from hebrew_live import whisper_speed


def model_with_blocks(count=2):
    return types.SimpleNamespace(encoder=types.SimpleNamespace(
        blocks=[types.SimpleNamespace(attn=types.SimpleNamespace(qkv_attention='stock')) for _ in range(count)]))


class FusedEncoderTests(unittest.TestCase):
    def test_off_by_default(self):
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop('HEBREW_LIVE_FUSED_ENCODER',None)
            self.assertFalse(whisper_speed.enabled())
            model=model_with_blocks()
            self.assertEqual(whisper_speed.prepare(model),{'fused_encoder':False})
            self.assertEqual(model.encoder.blocks[0].attn.qkv_attention,'stock')
    def test_enabled_patches_every_encoder_block_for_a_qualified_library(self):
        events=[]
        with patch.dict(os.environ,{'HEBREW_LIVE_FUSED_ENCODER':'1'}),patch.object(whisper_speed,'compatible',return_value=True):
            model=model_with_blocks(3)
            applied=whisper_speed.prepare(model,lambda name,**values:events.append((name,values)))
        self.assertEqual(applied,{'fused_encoder':True})
        for block in model.encoder.blocks:self.assertNotEqual(block.attn.qkv_attention,'stock')
        self.assertEqual(events,[('whisper_speed',{'fused_encoder':True})])
    def test_fails_closed_for_unqualified_library(self):
        events=[]
        with patch.dict(os.environ,{'HEBREW_LIVE_FUSED_ENCODER':'1'}),patch.object(whisper_speed,'compatible',return_value=False):
            model=model_with_blocks()
            applied=whisper_speed.prepare(model,lambda name,**values:events.append((name,values)))
        self.assertEqual(applied,{'fused_encoder':False})
        self.assertEqual(model.encoder.blocks[0].attn.qkv_attention,'stock')
        self.assertEqual(events[0][0],'whisper_speed_disabled')


if __name__=='__main__':unittest.main()
