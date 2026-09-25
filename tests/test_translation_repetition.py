import sys
import types
import unittest
from unittest.mock import patch

from hebrew_live.cli import Engine


class TranslationRepetitionTests(unittest.TestCase):
    def test_repeated_output_stops_inside_engine_before_next_token(self):
        consumed = []

        def stream_generate(*_args, **_kwargs):
            for text in ('раз два три ', 'раз два три ', 'раз два три ', 'unused'):
                consumed.append(text)
                yield types.SimpleNamespace(text=text, finish_reason=None)

        mlx_lm = types.ModuleType('mlx_lm')
        mlx_lm.stream_generate = stream_generate
        sample_utils = types.ModuleType('mlx_lm.sample_utils')
        sample_utils.make_sampler = lambda **_kwargs: object()
        engine = object.__new__(Engine)
        engine.model = object()
        engine.tokenizer = object()
        engine.direction = 'he-ru'
        engine.topic = 'none'
        engine.translation_context = []

        with patch.dict(sys.modules, {'mlx_lm': mlx_lm, 'mlx_lm.sample_utils': sample_utils}), \
             patch('hebrew_live.translation.prompt', return_value=[1]):
            result = list(engine.translate('שלום'))

        self.assertEqual(consumed, ['раз два три '] * 3)
        self.assertEqual(result[-1], ('', 'repetition'))
        self.assertEqual(len(result), 3)


if __name__ == '__main__':
    unittest.main()
