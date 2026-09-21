"""Production Engine + early decode rejection + real reuse, with a fake model."""
import importlib
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
from hebrew_live.whisper_repetition import reject_repeated_decode


class RepetitionTests(unittest.TestCase):
    def setUp(self):
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
