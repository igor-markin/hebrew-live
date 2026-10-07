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

from hebrew_live.remote_engine import RemoteEngine,RemoteEngineInterrupted,SplitRemoteEngine


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

class SlowTranslationEngine(FakeNativeEngine):
    def translate(self,text):
        time.sleep(1.)
        yield 'hello','stop'

class EndlessStreamingEngine(FakeNativeEngine):
    def translate(self,text):
        while True:yield 'token','stop'

class SlowEndlessStreamingEngine(FakeNativeEngine):
    """About 25 ms per token, like MiLMMT decoding."""
    def translate(self,text):
        while True:
            time.sleep(.025);yield 'token',None

class BlockedTranslationEngine(FakeNativeEngine):
    """One token, then a native call that never returns to the token loop."""
    def translate(self,text):
        yield 'first',None
        time.sleep(30)

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
    def test_split_workers_allow_asr_during_mt(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Log();engine=SplitRemoteEngine(Path(folder),log,engine_factory=SlowTranslationEngine,startup_timeout=5)
            try:
                self.assertNotEqual(engine.asr._process.pid,engine.mt._process.pid)
                results=[];started=threading.Event()
                def translate():
                    started.set()
                    results.extend(engine.translate_for('שלום',type('Settings',(),dict(
                        language='he',direction='he-ru',topic='none'))()))
                thread=threading.Thread(target=translate);thread.start();self.assertTrue(started.wait(1))
                time.sleep(.1)
                began=time.monotonic()
                self.assertEqual(engine.recognize(np.ones(1600,dtype=np.float32)),'שלום')
                self.assertLess(time.monotonic()-began,.8)
                thread.join(2)
                self.assertEqual(results,[('hello','stop')])
            finally:engine.close()
            self.assertIn('split_engine_memory',[name for name,_ in log.events])
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
            engine.switch_models(dict(asr='turbo',translation='milmmt'))
            self.assertEqual(engine.backend,'turbo')
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

    def test_early_close_cancels_endless_stream_between_tokens_and_keeps_the_child(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Log()
            engine=RemoteEngine(Path(folder),log,engine_factory=SlowEndlessStreamingEngine,
                                startup_timeout=5,cancel_grace=2)
            pid=engine._process.pid
            generated=engine.translate('שלום');self.assertEqual(next(generated),('token',None))
            started=time.monotonic();generated.close();elapsed=time.monotonic()-started
            self.assertLess(elapsed,.5)
            self.assertTrue(engine.alive);self.assertEqual(engine._process.pid,pid)
            self.assertEqual(engine.recognize(np.ones(160,dtype=np.float32)),'שלום')
            cancels=[data for name,data in log.events if name=='mt_cancel']
            self.assertEqual([item['outcome'] for item in cancels],['acknowledged'])
            self.assertLess(cancels[0]['seconds'],.5)
            engine.close()

    def test_cancel_is_repeatable_on_one_child(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=RemoteEngine(Path(folder),Log(),engine_factory=SlowEndlessStreamingEngine,
                                startup_timeout=5,cancel_grace=2)
            pid=engine._process.pid
            for _ in range(3):
                generated=engine.translate('שלום');next(generated);next(generated);generated.close()
            self.assertEqual(engine._process.pid,pid);self.assertTrue(engine.alive)
            engine.close()

    def test_stale_cancel_after_completion_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=RemoteEngine(Path(folder),Log(),engine_factory=FakeNativeEngine,startup_timeout=5)
            self.assertEqual(list(engine.translate('שלום')),[('hello','stop')])
            engine._send.send((engine._request_id,'cancel',{},(),{}))
            self.assertEqual(engine.recognize(np.ones(160,dtype=np.float32)),'שלום')
            self.assertEqual(list(engine.translate('שלום')),[('hello','stop')])
            engine.close()

    def test_child_that_cannot_acknowledge_is_terminated_after_the_grace(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Log()
            engine=RemoteEngine(Path(folder),log,engine_factory=BlockedTranslationEngine,
                                startup_timeout=5,cancel_grace=.3)
            generated=engine.translate('שלום');self.assertEqual(next(generated),('first',None))
            started=time.monotonic();generated.close();self.assertLess(time.monotonic()-started,3)
            self.assertFalse(engine.alive)
            self.assertEqual([data['outcome'] for name,data in log.events if name=='mt_cancel'],['aborted'])
            with self.assertRaises(RuntimeError):engine.recognize(np.ones(160,dtype=np.float32))
            engine.close()
            replacement=RemoteEngine(Path(folder),Log(),engine_factory=FakeNativeEngine,startup_timeout=5)
            self.assertEqual(replacement.recognize(np.ones(160,dtype=np.float32)),'שלום');replacement.close()

    def test_environment_switch_restores_drain_without_cancel_message(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'HEBREW_LIVE_MT_INTERRUPT':'0'}):
            log=Log()
            engine=RemoteEngine(Path(folder),log,engine_factory=StreamingNativeEngine,startup_timeout=5)
            generated=engine.translate('שלום');self.assertEqual(next(generated),('one','stop'));generated.close()
            self.assertEqual([data['outcome'] for name,data in log.events if name=='mt_cancel'],['drained'])
            self.assertEqual(engine.recognize(np.ones(160,dtype=np.float32)),'שלום')
            engine.close()

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
