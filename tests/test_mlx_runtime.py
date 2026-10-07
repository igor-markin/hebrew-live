import importlib.metadata
import unittest
from unittest.mock import patch

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


if __name__=='__main__':unittest.main()
