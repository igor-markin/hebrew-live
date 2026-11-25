import importlib.metadata
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hebrew_live import mlx_runtime


class FakeDistribution:
    def __init__(self,text):self.text=text
    def read_text(self,name):return self.text if name=='WHEEL' else None


class MlxRuntimeTests(unittest.TestCase):
    def test_wheel_tags_parse_every_tag_line(self):
        text='Wheel-Version: 1.0\nTag: cp312-cp312-macosx_26_0_arm64\nTag: cp312-cp312-macosx_26_0_x86_64\n'
        with patch.object(importlib.metadata,'distribution',return_value=FakeDistribution(text)):
            tags=mlx_runtime.wheel_tags(('mlx',))
        self.assertEqual(tags,{'mlx':['cp312-cp312-macosx_26_0_arm64','cp312-cp312-macosx_26_0_x86_64']})
    def test_missing_distribution_or_metadata_is_unknown_not_an_error(self):
        with patch.object(importlib.metadata,'distribution',side_effect=importlib.metadata.PackageNotFoundError):
            self.assertEqual(mlx_runtime.wheel_tags(('mlx',)),{'mlx':None})
        with patch.object(importlib.metadata,'distribution',return_value=FakeDistribution(None)):
            self.assertEqual(mlx_runtime.wheel_tags(('mlx',)),{'mlx':None})
        self.assertIsNone(mlx_runtime.accelerator_wheel({'mlx':None}))
        self.assertIsNone(mlx_runtime.accelerator_wheel({}))
    def test_accelerator_wheel_requires_every_distribution(self):
        self.assertTrue(mlx_runtime.accelerator_wheel({'mlx':['a-macosx_26_0_arm64'],'mlx-metal':['b-macosx_26_0_arm64']}))
        self.assertFalse(mlx_runtime.accelerator_wheel({'mlx':['a-macosx_26_0_arm64'],'mlx-metal':['b-macosx_15_0_arm64']}))
    def test_device_info_keeps_only_hardware_fields_and_survives_old_mlx(self):
        class Mx:
            @staticmethod
            def device_info():return dict(device_name='Apple M5',architecture='applegpu_g17g',memory_size=16,
                                          max_recommended_working_set_size=12,resource_limit=1,max_buffer_length=2)
        self.assertEqual(set(mlx_runtime.device_info(Mx)),
                         {'device_name','architecture','memory_size','max_recommended_working_set_size'})
        self.assertEqual(mlx_runtime.device_info(object()),{})
        info=mlx_runtime.describe(Mx)
        self.assertIn('wheel_tags',info);self.assertIn('neural_accelerator_wheel',info)

    def test_freed_buffers_are_limited_to_256_mb(self):
        mx=Mock();self.assertEqual(mlx_runtime.limit_cache(mx),256*1024*1024)
        mx.set_cache_limit.assert_called_once_with(256*1024*1024)


class EngineCacheLimitTests(unittest.TestCase):
    def engine(self,role):
        from hebrew_live.cli import Engine
        order=[];core=Mock();core.set_cache_limit.side_effect=lambda n:order.append(('limit',n))
        core.device_info.return_value={}
        load=lambda path:order.append(('load',path)) or (Mock(),Mock())
        modules={'mlx':types.SimpleNamespace(core=core),'mlx.core':core,'mlx_lm':types.SimpleNamespace(load=load),
                 'transformers':Mock(),'transformers.utils':types.SimpleNamespace(logging=Mock())}
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules,modules), \
             patch('hebrew_live.translation.configure'):
            Engine(Path(folder),Mock(),translation_path=Path(folder),role=role)
        return [name for name,_ in order],[value for name,value in order if name=='limit']
    def test_the_translation_worker_sets_the_limit_before_the_model_loads(self):
        for role in ('mt','both'):
            with self.subTest(role):self.assertEqual(self.engine(role),(['limit','load'],[256*1024*1024]))
    def test_the_recognition_worker_leaves_mlx_alone(self):
        self.assertEqual(self.engine('asr'),([],[]))


if __name__=='__main__':unittest.main()
