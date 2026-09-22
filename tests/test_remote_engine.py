import multiprocessing
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from hebrew_live.remote_engine import RemoteEngine,RemoteEngineInterrupted


class FakeNativeEngine:
    def __init__(self,folder,log,language='he',backend='turbo',asr_path=None,translation_path=None):
        self.log=log;self.language=language;self.backend=backend;self.translation_size='milmmt'
        self.asr_path=str(asr_path or Path(folder)/'asr');self.custom_models=False
        self.direction='he-en';self.topic='none';self.translation_context=[]
        self.mx=type('Memory',(),{'get_peak_memory':lambda self:7})()
    def warmup(self):self.log.event('fake_warmup')
    def recognize(self,audio,*args,**kwargs):
        self.recognition_status='accepted';self.recognition_issue=None
        self.recognition_words=[dict(word='שלום',start=0,end=len(audio)/16000)]
        self.raw_recognition='שלום';self.log.event('fake_asr',samples=len(audio));return 'שלום'
    def translate(self,text):
        yield 'hello','stop'
    def switch_models(self,selection):self.backend=selection['asr']
    def close(self):self.log.event('fake_close')


class HangingNativeEngine(FakeNativeEngine):
    def recognize(self,*args,**kwargs):
        while True:time.sleep(1)

class HangingCloseEngine(FakeNativeEngine):
    def close(self):
        while True:time.sleep(1)

class CrashingNativeEngine(FakeNativeEngine):
    def recognize(self,*args,**kwargs):os._exit(17)

class StreamingNativeEngine(FakeNativeEngine):
    def translate(self,text):
        for piece in ('one','two','three'):
            time.sleep(.02);yield piece,'stop'

class TranslationFailureEngine(FakeNativeEngine):
    def translate(self,text):raise RuntimeError('fake MT failure');yield

class EndlessStreamingEngine(FakeNativeEngine):
    def translate(self,text):
        while True:yield 'token','stop'

class PrivacyEngine(FakeNativeEngine):
    def warmup(self):
        if os.environ.get('HF_HUB_OFFLINE')!='1':raise RuntimeError('offline environment missing')
        logging.getLogger('fake.native').warning('private value: %s','do not persist')

class WarmupFailureEngine(FakeNativeEngine):
    def warmup(self):
        raise ModuleNotFoundError("No module named 'fake_dynamic_module'",name='fake_dynamic_module')

def nonreading_worker(receive,send,config,engine_factory):
    send.send(('ready',dict(backend='turbo',translation_size='milmmt',asr_path='fake',custom_models=False)))
    time.sleep(30)

def silent_startup_worker(receive,send,config,engine_factory):time.sleep(30)


class Log:
    def __init__(self):self.events=[]
    def event(self,event,**data):self.events.append((event,data))


class RemoteEngineTests(unittest.TestCase):
    def test_startup_failure_preserves_child_diagnostic(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Log()
            with self.assertRaisesRegex(RuntimeError,'ModuleNotFoundError'):
                RemoteEngine(Path(folder),log,engine_factory=WarmupFailureEngine,startup_timeout=5)
            errors=[data for event,data in log.events if event=='engine_error']
            self.assertEqual(errors[0]['type'],'ModuleNotFoundError')
            self.assertEqual(errors[0]['stack'][-1]['function'],'warmup')

    def test_attributes_streaming_events_and_graceful_close(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Log();engine=RemoteEngine(Path(folder),log,engine_factory=FakeNativeEngine,startup_timeout=5)
            engine.direction='he-ru';engine.topic='medical';engine.translation_context=['prior']
            self.assertEqual(engine.recognize(np.ones(1600,dtype=np.float32)),'שלום')
            self.assertEqual(engine.recognition_status,'accepted')
            self.assertEqual(engine.recognition_words[0]['word'],'שלום')
            self.assertEqual(list(engine.translate('שלום')),[('hello','stop')])
            engine.switch_models(dict(asr='multilingual',translation='milmmt'))
            self.assertEqual(engine.backend,'multilingual')
            engine.close();self.assertFalse(engine.alive)
            self.assertIn('fake_asr',[name for name,_ in log.events])

    def test_hung_native_call_is_killed_and_next_engine_works(self):
        with tempfile.TemporaryDirectory() as folder:
            stop=threading.Event();engine=RemoteEngine(Path(folder),Log(),stop=stop,
                engine_factory=HangingNativeEngine,startup_timeout=5,shutdown_grace=.15)
            pid=engine._process.pid;stop.set();started=time.monotonic()
            with self.assertRaises(RemoteEngineInterrupted):
                engine.recognize(np.ones(1600,dtype=np.float32))
            self.assertLess(time.monotonic()-started,2)
            self.assertFalse(engine._process.is_alive());engine.close()
            self.assertNotIn(pid,[child.pid for child in multiprocessing.active_children()])
            next_engine=RemoteEngine(Path(folder),Log(),engine_factory=FakeNativeEngine,startup_timeout=5)
            self.assertEqual(next_engine.recognize(np.ones(1600,dtype=np.float32)),'שלום')
            next_engine.close()

    def test_early_generator_close_drains_before_followup(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=RemoteEngine(Path(folder),Log(),engine_factory=StreamingNativeEngine,startup_timeout=5)
            generated=engine.translate('שלום');self.assertEqual(next(generated),('one','stop'));generated.close()
            self.assertEqual(engine.recognize(np.ones(160,dtype=np.float32)),'שלום')
            engine.close()

    def test_early_close_of_endless_fast_stream_aborts_before_next_rpc(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=RemoteEngine(Path(folder),Log(),engine_factory=EndlessStreamingEngine,
                                startup_timeout=5,cancel_grace=.1)
            generated=engine.translate('שלום');self.assertEqual(next(generated),('token','stop'))
            started=time.monotonic();generated.close();self.assertLess(time.monotonic()-started,2)
            self.assertFalse(engine.alive)
            with self.assertRaises(RuntimeError):engine.recognize(np.ones(160,dtype=np.float32))
            engine.close()
            replacement=RemoteEngine(Path(folder),Log(),engine_factory=FakeNativeEngine,startup_timeout=5)
            self.assertEqual(replacement.recognize(np.ones(160,dtype=np.float32)),'שלום');replacement.close()

    def test_mt_failure_finishes_rpc_and_engine_remains_usable(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=RemoteEngine(Path(folder),Log(),engine_factory=TranslationFailureEngine,startup_timeout=5)
            with self.assertRaisesRegex(RuntimeError,'fake MT failure'):list(engine.translate('שלום'))
            self.assertEqual(engine.recognize(np.ones(160,dtype=np.float32)),'שלום')
            engine.close()

    def test_nonreading_transport_startup_crash_and_close_are_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=RemoteEngine(Path(folder),Log(),worker_target=nonreading_worker,startup_timeout=1)
            started=time.monotonic()
            with self.assertRaises(RemoteEngineInterrupted):engine.recognize(np.ones(3_000_000,dtype=np.float32))
            self.assertLess(time.monotonic()-started,7);engine.close()
            started=time.monotonic()
            with self.assertRaises((RemoteEngineInterrupted,RuntimeError)):
                RemoteEngine(Path(folder),Log(),worker_target=silent_startup_worker,startup_timeout=.15)
            self.assertLess(time.monotonic()-started,2)
            crash=RemoteEngine(Path(folder),Log(),engine_factory=CrashingNativeEngine,startup_timeout=5)
            started=time.monotonic()
            with self.assertRaises(RuntimeError):crash.recognize(np.ones(160,dtype=np.float32))
            self.assertLess(time.monotonic()-started,2);crash.close()
            close_hang=RemoteEngine(Path(folder),Log(),engine_factory=HangingCloseEngine,startup_timeout=5)
            started=time.monotonic();close_hang.close();self.assertLess(time.monotonic()-started,5)

    def test_stop_with_no_active_rpc_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            stop=threading.Event();engine=RemoteEngine(Path(folder),Log(),stop=stop,engine_factory=FakeNativeEngine,startup_timeout=5)
            stop.set();started=time.monotonic();engine.close();self.assertLess(time.monotonic()-started,3)

    def test_child_inherits_offline_environment_and_sanitizes_library_logs(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'HF_HUB_OFFLINE':'1'}):
            log=Log();engine=RemoteEngine(Path(folder),log,engine_factory=PrivacyEngine,startup_timeout=5)
            engine.close()
            library=[data for name,data in log.events if name=='library']
            self.assertEqual(len(library),1)
            self.assertEqual(library[0]['logger'],'fake.native')
            self.assertIsNone(library[0]['detail'])
            self.assertNotIn('do not persist',str(library[0]))


if __name__=='__main__':unittest.main()
