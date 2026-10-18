"""Production Engine + early decode rejection + real reuse, with a fake model."""
import importlib
import os
from pathlib import Path
from types import SimpleNamespace
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf
from hebrew_live.cli import Engine, Fragment, Inbox
from hebrew_live.phrase_inference import PhraseProcessor
from hebrew_live.stream import Settings, Boundary
from hebrew_live import whisper_reuse
from hebrew_live.whisper_repetition import reject_repeated_decode, RepeatedDecode


class RepetitionTests(unittest.TestCase):
    def setUp(self):
        fused = patch.dict(os.environ, {'HEBREW_LIVE_FUSED_ENCODER': '0'})  # warmup would patch the fake model's encoder
        fused.start()
        self.addCleanup(fused.stop)
        self.events = []
        self.mel = np.ones((4, 3), np.float16)

        class Model:
            dims = SimpleNamespace(n_audio_ctx=2, n_audio_state=4)
            text = 'ה' * 30
            error = None
            encoders = 0
            decodes = 0
            alignments = 0

            def encoder(model, mel):
                model.encoders += 1
                return np.full((2, 4), float(mel.mean()), np.float16)

            def decode(model, mel):
                model.decodes += 1
                if model.error:
                    raise model.error
                return SimpleNamespace(text=model.text, tokens=[1, 2],
                                       audio_features=model.encoder(mel))

            def decoder(model, tokens, features):
                model.aligned_value = float(features.sum())
                return model.aligned_value, None, features

            def forward_with_cross_qk(model, mel, tokens):
                a, _, b = model.decoder(tokens, model.encoder(mel))
                return a, b

        self.Model = Model
        self.model = Model()
        self.trans = SimpleNamespace()

        def align(**kw):
            self.model.alignments += 1
            return kw['model'].forward_with_cross_qk(kw['mel'][None, :], None)

        self.trans.add_word_timestamps = align

        def transcribe(audio, **kw):
            result = self.model.decode(self.mel)
            self.trans.add_word_timestamps(model=self.model, mel=self.mel)
            return dict(segments=[dict(words=[dict(word=result.text, start=0, end=.3)])])

        self.trans.transcribe = transcribe
        self.originals = (Model.decode, Model.forward_with_cross_qk, align)
        original_import = importlib.import_module

        def modules(name, *args, **kwargs):
            if name == 'mlx_whisper.whisper':
                return SimpleNamespace(Whisper=Model)
            if name == 'mlx_whisper.transcribe':
                return self.trans
            return original_import(name, *args, **kwargs)

        qualifier = patch.object(whisper_reuse, 'compatible', return_value=True)
        self.qualifier = qualifier.start()
        self.addCleanup(qualifier.stop)
        importer = patch.object(importlib, 'import_module', side_effect=modules)
        importer.start()
        self.addCleanup(importer.stop)
        e = Engine.__new__(Engine)
        e.backend = 'turbo'; e.language = 'he'; e.direction = 'he-ru'
        e.early_reject = True; e.encoder_reuse = True
        e.language_check = 'off'; e.asr_path = 'fake'; e.asr = self.trans
        e.log = SimpleNamespace(event=lambda k, **v: self.events.append((k, v)))
        e.translate = lambda s: iter([('Привет.', 'stop')])
        self.engine = e

    def recognize(self, **kwargs):
        return self.engine.recognize(np.zeros(16000), preliminary=True, mode='phrases', **kwargs)

    def restored(self):
        self.assertEqual(self.originals, (self.Model.decode, self.Model.forward_with_cross_qk,
                                        self.trans.add_word_timestamps))
        self.assertIsNone(whisper_reuse._OWNER)

    def test_reject_before_alignment_then_normal_uses_fresh_features(self):
        self.engine.recognition_words = ['stale']
        self.assertEqual(self.recognize(), '')
        self.assertEqual(self.model.alignments, 0)
        self.assertEqual(self.model.decodes, 1)
        self.assertEqual(self.engine.recognition_status, 'rejected')
        self.assertEqual(self.engine.recognition_words, [])
        self.assertEqual(self.engine.raw_recognition, 'ה' * 30)
        self.assertTrue(any(k == 'recognition_early_repetition' for k, _ in self.events))
        self.restored()
        self.model.text = 'שלום.'; self.mel *= 2
        self.assertEqual(self.recognize(), 'שלום.')
        self.assertEqual(self.model.aligned_value, 16)
        self.assertEqual(self.model.encoders, 2)  # one per decode, no second encoder in alignment
        self.restored()

    def test_safe_defaults_and_every_unqualified_scope_keep_late_path(self):
        scopes = [dict(), dict(mode='phrases'), dict(preliminary=True),
                  dict(preliminary=True, mode='both'), dict(preliminary=True, mode='blocks'),
                  dict(preliminary=True, mode='full'), dict(preliminary=True, mode='pauses')]
        for kwargs in scopes:
            before = self.model.alignments
            self.engine.recognize(np.zeros(16000), **kwargs)
            self.assertEqual(self.model.alignments, before + 1)
            self.assertEqual(self.engine.recognition_issue, 'repeated recognition')
            self.restored()
        for name, value in [('backend', 'multilingual'), ('backend', 'large'),
                            ('backend', 'unknown'), ('language', 'ru'), ('language', 'auto'),
                            ('direction', 'ru-he'), ('early_reject', False)]:
            with patch.object(self.engine, name, value):
                before = self.model.alignments
                self.recognize()
                self.assertEqual(self.model.alignments, before + 1)
                self.assertNotEqual(self.engine.recognition_issue, 'early repeated recognition')
                self.restored()

    def test_loop_stop_extends_early_reject_to_finals_only_inside_the_scope(self):
        self.engine.loop_stop = True
        for kwargs in (dict(mode='phrases'), dict(preliminary=True, mode='phrases')):
            before = self.model.alignments
            self.engine.recognize(np.zeros(16000), **kwargs)
            self.assertEqual(self.model.alignments, before)
            self.assertEqual(self.engine.recognition_status, 'rejected')
            self.assertEqual(self.engine.recognition_issue, 'early repeated recognition')
            self.restored()
        for kwargs in (dict(), dict(preliminary=True), dict(mode='both'), dict(mode='blocks'),
                       dict(mode='full'), dict(mode='pauses')):
            before = self.model.alignments
            self.engine.recognize(np.zeros(16000), **kwargs)
            self.assertEqual(self.model.alignments, before + 1)
            self.assertEqual(self.engine.recognition_issue, 'repeated recognition')
            self.restored()
        self.engine.loop_stop = False  # HEBREW_LIVE_LOOP_STOP=0: finals take the late path again
        before = self.model.alignments
        self.engine.recognize(np.zeros(16000), mode='phrases')
        self.assertEqual(self.model.alignments, before + 1)
        self.assertEqual(self.engine.recognition_issue, 'repeated recognition')

    def test_warmup_is_not_intercepted(self):
        self.engine.mx = SimpleNamespace(get_peak_memory=lambda: 0)
        self.engine.warmup()
        self.assertEqual(self.model.alignments, 1)
        self.restored()

    def test_incompatible_library_falls_back_with_diagnostic(self):
        self.qualifier.return_value = False
        self.model.text = 'שלום.'
        self.assertEqual(self.recognize(), 'שלום.')
        self.assertTrue(any(k == 'whisper_early_reject_disabled' for k, _ in self.events))
        self.assertEqual(self.model.alignments, 1)
        self.model.text = 'ה' * 30
        self.assertEqual(self.recognize(), '')
        self.assertEqual(self.engine.recognition_issue, 'repeated recognition')
        self.restored()

    def test_native_failures_propagate_and_next_request_recovers(self):
        for error in (MemoryError('GPU memory'), RuntimeError('GPU failure')):
            self.model.error = error
            with self.assertRaises(type(error)):
                self.recognize()
            self.assertNotEqual(self.engine.recognition_issue, 'early repeated recognition')
            self.restored()
            self.model.error = None; self.model.text = 'שלום.'
            self.assertEqual(self.recognize(), 'שלום.')
        with patch.object(self.model, 'decoder', side_effect=MemoryError('alignment GPU')):
            with self.assertRaises(MemoryError):
                self.recognize()
        self.restored()
        self.assertEqual(self.recognize(), 'שלום.')

    def test_a_loop_rejects_the_whole_window_unless_trimming_is_on(self):
        self.model.text = 'שלום לכולם ' + 'ה' * 30
        self.assertEqual(self.recognize(), '')
        self.assertEqual(self.engine.recognition_status, 'rejected')
        self.restored()

    @patch.dict(os.environ, {'HEBREW_LIVE_LOOP_TRIM': '1'})
    def test_words_before_a_loop_are_kept(self):
        self.model.text = 'שלום לכולם ' + 'ה' * 30
        self.assertEqual(self.recognize(), 'שלום לכולם')
        self.assertEqual(self.engine.recognition_status, 'accepted')
        self.assertTrue(any(k == 'recognition_loop_trimmed' for k, _ in self.events))
        self.restored()
        self.model.text = 'ה' * 30
        self.assertEqual(self.recognize(), '')
        self.assertEqual(self.engine.recognition_status, 'rejected')
        self.restored()

    @patch.dict(os.environ, {'HEBREW_LIVE_LOOP_TRIM': '1'})
    def test_closing_loop_gets_one_sampled_retry(self):
        from hebrew_live.whisper_repetition import RepeatedDecode
        temperatures = []
        def transcribe(audio, temperature, **kwargs):
            temperatures.append(temperature)
            if temperature == 0:
                raise RepeatedDecode('שלום ' + 'ה' * 12, [])
            return {'segments': [{'text': 'שלום לכולם, מה נשמע?'}]}
        self.engine.asr = SimpleNamespace(transcribe=transcribe)
        text = self.engine.recognize(np.zeros(16000), mode='phrases', align_words=False)
        self.assertEqual(text, 'שלום לכולם, מה נשמע?')
        self.assertEqual(temperatures, [0.0, 0.3])
        self.assertEqual(self.engine.recognition_status, 'accepted')
        self.assertIsNone(self.engine.recognition_issue)
        temperatures.clear()
        self.engine.recognize(np.zeros(16000), preliminary=True, mode='phrases', align_words=False)
        self.assertEqual(temperatures, [0.0])  # drafts never pay for a retry

    def test_ordinary_repetitions_are_preserved(self):
        for text in ['כן כן כן, אני מבין.', 'לאט לאט אנחנו עולים.']:
            self.model.text = text
            self.assertEqual(self.recognize(), text)
            self.assertEqual(self.engine.recognition_status, 'accepted')

    def test_other_thread_does_not_inherit_guard(self):
        result = []
        with reject_repeated_decode(True, self.engine.log.event):
            t = threading.Thread(target=lambda: result.append(self.model.decode(self.mel).text))
            t.start(); t.join(2)
            self.assertFalse(t.is_alive())
        self.assertEqual(result, ['ה' * 30])
        self.restored()

    def test_rejection_does_not_confirm_existing_pending_words(self):
        pp = PhraseProcessor(self.engine, queue.Queue(), self.engine.log, threading.Event())
        f = Fragment(1, 1, np.zeros(32000), 0, time.monotonic(), False,
                     Settings(mode='phrases'), 2)
        self.model.text = 'שלום.'; pp.process(f, defer=True)
        self.assertFalse(pp.jobs)
        self.model.text = 'ה' * 30; pp.process(f, defer=True)
        self.assertFalse(pp.jobs)
        self.assertFalse(any(w['word_stable'] for w in pp.buffer.pending))
        self.assertEqual(self.model.decodes, 2)

    def test_worker_rejection_normal_final_and_clear_preserve_audio_and_files(self):
        from hebrew_live.feed import inference
        from hebrew_live.session import Session
        from hebrew_live.display import TranslationScreen
        for clear in (False, True):
            with self.subTest(clear=clear), tempfile.TemporaryDirectory() as tmp:
                session = Session(Path(tmp), 'he-ru', {})
                self.engine.log = session
                settings = Settings(mode='phrases', generation=int(clear))
                old = Settings(mode='phrases')
                audio = np.linspace(-.2, .2, 48000, dtype=np.float32)
                session.parts[1].write_audio(audio, 16000)
                box = Inbox(); calls = []; base = self.trans.transcribe
                frames = [Fragment(1, i, audio[:i*16000], 0, time.monotonic(), i == 3,
                                   settings if i > 1 else old, i, .6 if i == 3 else 0,
                                   'eof' if i == 3 else '') for i in (1, 2, 3)]

                def transcribe(a, **kwargs):
                    calls.append(len(a))
                    n = len(calls)
                    self.model.text = 'ה' * 30 if n == 1 else 'שלום.'
                    if n < 3:
                        if n == 1 and clear:
                            box.put_boundary(Boundary(settings, 'clear'))
                        box.put(frames[n])
                    else:
                        box.finish()
                    return base(a, **kwargs)

                updates = queue.Queue(); errors = queue.Queue(); stop = threading.Event()
                box.put(frames[0])
                with patch.object(self.trans, 'transcribe', transcribe):
                    inference(box, self.engine, updates, stop, errors, session)
                session.close()
                self.assertTrue(errors.empty(), list(errors.queue))
                self.assertEqual(calls, [16000, 32000, 48000])
                self.assertEqual(self.engine.recognition_status, 'accepted')
                self.restored()
                saved, rate = sf.read(session.path/'001-he-ru.audio.wav', dtype='float32')
                np.testing.assert_array_equal(saved, audio)
                self.assertEqual(rate, 16000)
                self.assertEqual(len(list(session.path.iterdir())), 5)
                self.assertTrue((session.path/'session.json').is_file())
                self.assertIn('שלום.', (session.path/'001-he-ru.transcript.txt').read_text())
                self.assertNotIn('ה' * 30, (session.path/'001-he-ru.transcript.txt').read_text())
                self.assertEqual((session.path/'001-he-ru.translation.txt').read_text().count('Привет.'), 1)
                screen = TranslationScreen()
                if clear:
                    screen.clear(1)
                for kind, sid, value in updates.queue:
                    screen.update(kind, sid, value)
                self.assertEqual(len(screen.groups), 1)
                group = next(iter(screen.groups.values()))
                self.assertTrue(group['id'].startswith(f'{int(clear)}:'))
                self.assertEqual(group['final']['source'], 'שלום.')


class LoopStopTests(unittest.TestCase):
    """Real GreedyDecoder.update on tiny arrays, driven by a minimal DecodingTask."""
    EOT, VOCAB = 1000, 1010

    def setUp(self):
        import mlx.core as mx
        self.mx = mx
        self.decoding = importlib.import_module('mlx_whisper.decoding')
        self.events = []
        test = self
        self.steps = 0

        class Tokenizer:
            def decode(self, ids):
                return ''.join(chr(0x5d0 + i % 27) for i in ids)

        class Task:
            def __init__(task, script, temperature=0):
                task.script = script
                task.decoder = test.decoding.GreedyDecoder(temperature, test.EOT)
                task.tokenizer = Tokenizer()

            def _main_loop(task, audio_features, tokens):
                logprobs = mx.zeros(1)
                for i in range(224):
                    test.steps += 1
                    hot = np.zeros((1, test.VOCAB), np.float32)
                    hot[0, task.script(i)] = 10
                    tokens, completed, logprobs = task.decoder.update(tokens, mx.array(hot), logprobs)
                    if completed:
                        break
                return tokens, logprobs

        self.Task = Task
        self.original_main_loop = Task.__dict__['_main_loop']
        for patcher in (patch.object(whisper_reuse, 'compatible', return_value=True),
                        patch.object(self.decoding, 'DecodingTask', Task)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.prompt = self.mx.array([[1001, 1002]])

    def run_loop(self, script, stop=True, task=None):
        task = task or self.Task(script)
        with reject_repeated_decode(True, lambda k, **v: self.events.append((k, v)), stop):
            return task, self.decoding.DecodingTask._main_loop(task, None, self.prompt)

    def test_same_token_stops_within_24_text_tokens(self):
        with self.assertRaises(RepeatedDecode) as caught:
            self.run_loop(lambda i: 105)
        self.assertLessEqual(len(caught.exception.tokens), 24)
        self.assertEqual(caught.exception.tokens, [105] * len(caught.exception.tokens))
        self.assertLess(self.steps, 24)
        self.assertEqual(caught.exception.text, chr(0x5d0 + 105 % 27) * len(caught.exception.tokens))
        self.assertIs(self.Task.__dict__['_main_loop'], self.original_main_loop)

    def test_other_tokens_decode_exactly_as_without_the_guard(self):
        script = lambda i: 100 + i % 40 if i < 60 else self.EOT
        _, (guarded, guarded_lp) = self.run_loop(script)
        steps = self.steps
        self.steps = 0
        _, (plain, plain_lp) = self.run_loop(script, stop=False)
        self.assertEqual(guarded.tolist(), plain.tolist())
        self.assertEqual(guarded_lp.tolist(), plain_lp.tolist())
        self.assertEqual(steps, self.steps)
        self.assertEqual(plain.shape[-1], 2 + 61)

    def test_loop_after_ordinary_words_is_stopped_late_but_unfinished_word_is_kept(self):
        words = [100, 101, 102]
        script = lambda i: words[i] if i < 3 else 110 if i < 8 else 120
        with self.assertRaises(RepeatedDecode):
            self.run_loop(script)
        self.assertLessEqual(self.steps, 24)

    def test_without_stop_in_loop_nothing_is_patched(self):
        task, _ = self.run_loop(lambda i: 105 if i < 30 else self.EOT, stop=False)
        self.assertEqual(self.steps, 31)

    def test_other_thread_and_cleanup(self):
        result = []
        decoder_class = self.decoding.GreedyDecoder
        with reject_repeated_decode(True, lambda *a, **k: None, True):
            task = self.Task(lambda i: 105 if i < 30 else self.EOT)
            t = threading.Thread(target=lambda: result.append(
                self.decoding.DecodingTask._main_loop(task, None, self.prompt)[0].shape[-1]))
            t.start(); t.join(5)
            self.assertFalse(t.is_alive())
        self.assertEqual(result, [2 + 31])
        self.assertNotIn('update', vars(task.decoder))
        self.assertIs(self.decoding.GreedyDecoder, decoder_class)
        self.assertIsNone(whisper_reuse._OWNER)

    def test_instance_update_is_removed_after_stop(self):
        task = self.Task(lambda i: 105)
        with self.assertRaises(RepeatedDecode):
            self.run_loop(None, task=task)
        self.assertNotIn('update', vars(task.decoder))

    def test_incompatible_library_does_not_patch(self):
        with patch.object(whisper_reuse, 'compatible', return_value=False):
            task, (tokens, _) = self.run_loop(lambda i: 105 if i < 30 else self.EOT)
        self.assertEqual(tokens.shape[-1], 2 + 31)
        self.assertTrue(any(k == 'whisper_early_reject_disabled' for k, _ in self.events))

    def test_unknown_decoder_types_are_left_alone(self):
        task = self.Task(lambda i: 105)
        calls = []

        class Other:
            eot = self.EOT

            def update(other, tokens, logits, sum_logprobs):
                calls.append(1)
                return tokens, self.mx.array(True), sum_logprobs

        task.decoder = Other()
        self.run_loop(None, task=task)
        self.assertEqual(calls, [1])
        self.assertNotIn('update', vars(task.decoder))


class TrimLoopTests(unittest.TestCase):
    def test_keeps_text_before_letter_and_phrase_loops(self):
        from hebrew_live.cli import trim_loop
        self.assertEqual(trim_loop('ובביתם התגלו וואוווווווווווו'), 'ובביתם התגלו')
        self.assertEqual(trim_loop('אתה רוצה לסיים לו? אההההההההההההה'), 'אתה רוצה לסיים לו?')
        self.assertEqual(trim_loop('שלום א ב ג א ב ג א ב ג ד'), 'שלום א ב ג')
        self.assertEqual(trim_loop('ה' * 30), '')
        self.assertEqual(trim_loop('כן כן כן, אני מבין.'), 'כן כן כן, אני מבין.')


class RepetitionLoopPartialTests(unittest.TestCase):
    def test_partial_ignores_last_word_only(self):
        from hebrew_live.cli import repetition_loop
        triple = 'א ב ג א ב ג א ב ג'
        self.assertTrue(repetition_loop(triple))
        self.assertFalse(repetition_loop(triple, partial=True))
        self.assertTrue(repetition_loop(triple + ' ד', partial=True))
        self.assertTrue(repetition_loop('ה' * 12, partial=True))
        self.assertFalse(repetition_loop('כן כן כן', partial=True))

    def test_partial_true_implies_full_for_every_continuation(self):
        from hebrew_live.cli import repetition_loop
        text = 'שלום א ב ג א ב ג א ב ג ד'
        for end in range(1, len(text) + 1):
            if repetition_loop(text[:end], partial=True):
                for tail in ('', 'x', ' y', 'ה' * 3):
                    self.assertTrue(repetition_loop(text[:end] + tail))


class TranslationLoopTests(unittest.TestCase):
    # Real closing translations cut as "Повтор генерации" on 2026-10-18.
    SOURCE = 'בן אדם קצת מצליח, כולם פותחים עליו עיניים. זה הבעיה, זה הבעיה, זה הבעיה. הרבה כסף.'

    def test_a_phrase_the_speaker_repeated_is_not_a_loop(self):
        from hebrew_live.cli import translation_loop
        for text in ('Человек немного преуспевает. Вот в этом проблема, вот в этом проблема, вот в этом проблема',
                     'Вот в этом и заключается проблема, вот в этом и заключается проблема, вот в этом и заключается проблема.'):
            self.assertFalse(translation_loop(text, self.SOURCE))

    def test_more_copies_than_the_source_is_a_loop(self):
        from hebrew_live.cli import translation_loop
        text = 'Вот в этом проблема, ' * 4
        self.assertTrue(translation_loop(text, self.SOURCE))
        self.assertTrue(translation_loop('Он сказал, что он сказал, что он сказал, что', 'הוא אמר'))
        self.assertTrue(translation_loop('Ааааааааааааа', self.SOURCE))
        self.assertFalse(translation_loop('Да, да, да.', 'כן כן כן'))
