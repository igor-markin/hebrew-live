import os
import sys
import types
import unittest
from unittest.mock import patch

from hebrew_live.cli import Engine

PIECES = ('раз два три ', 'раз два три ', 'раз два три ', 'unused')


def make_engine():
    events = []
    engine = object.__new__(Engine)
    engine.model = object()
    engine.tokenizer = types.SimpleNamespace(encode=lambda text, add_special_tokens=False: [1, 2, 3])
    engine.log = types.SimpleNamespace(event=lambda name, **values: events.append((name, values)))
    engine.direction = 'he-ru'
    engine.topic = 'none'
    engine.translation_context = []
    return engine, events


class TranslationRepetitionTests(unittest.TestCase):
    def check(self, engine, events, consumed):
        with patch('hebrew_live.translation.prompt', return_value=[1]):
            result = list(engine.translate('שלום'))
        self.assertEqual(consumed, ['раз два три '] * 3)
        self.assertEqual(result[-1], ('', 'repetition'))
        self.assertEqual(len(result), 3)
        report = [values for name, values in events if name == 'mt_generation']
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]['finish_reason'], 'repetition')
        self.assertTrue(report[0]['completed'])

    def test_repeated_output_stops_inside_engine_before_next_token(self):
        consumed = []

        def generate(*_args, **_kwargs):
            for text in PIECES:
                consumed.append(text)
                yield text, None

        sample_utils = types.ModuleType('mlx_lm.sample_utils')
        sample_utils.make_sampler = lambda **_kwargs: object()
        engine, events = make_engine()
        with patch.dict(sys.modules, {'mlx_lm.sample_utils': sample_utils}), \
             patch('hebrew_live.mt_generate.generate', generate):
            self.check(engine, events, consumed)

    def test_stock_rollback_path_stops_the_same_way(self):
        consumed = []

        def stream_generate(*_args, **_kwargs):
            for text in PIECES:
                consumed.append(text)
                yield types.SimpleNamespace(text=text, finish_reason=None, generation_tokens=len(consumed))

        mlx_lm = types.ModuleType('mlx_lm')
        mlx_lm.stream_generate = stream_generate
        sample_utils = types.ModuleType('mlx_lm.sample_utils')
        sample_utils.make_sampler = lambda **_kwargs: object()
        engine, events = make_engine()
        with patch.dict(sys.modules, {'mlx_lm': mlx_lm, 'mlx_lm.sample_utils': sample_utils}), \
             patch.dict(os.environ, {'HEBREW_LIVE_MT_GENERATE': 'stock'}):
            self.check(engine, events, consumed)

    def test_hint_selects_the_speculative_step_only_in_fast_mode(self):
        seen = []

        def generate(*_args, step=None, **_kwargs):
            seen.append(step)
            yield 'ok', 'stop'

        sample_utils = types.ModuleType('mlx_lm.sample_utils')
        sample_utils.make_sampler = lambda **_kwargs: object()
        engine, events = make_engine()
        with patch.dict(sys.modules, {'mlx_lm.sample_utils': sample_utils}), \
             patch('hebrew_live.mt_generate.generate', generate), \
             patch('hebrew_live.translation.prompt', return_value=[1]):
            list(engine.translate('שלום'))
            list(engine.translate('שלום', hint='раз два'))                       # off by default
            with patch.dict(os.environ, {'HEBREW_LIVE_MT_SPECULATE': '1'}):
                list(engine.translate('שלום', hint='раз два'))
                list(engine.translate('שלום'))
        self.assertEqual([step is not None for step in seen], [False, False, True, False])


if __name__ == '__main__':
    unittest.main()
