import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from hebrew_live.remote_engine import RemoteEngine as ProcessEngine
from hebrew_live.runtime import run_session
from hebrew_live.session import Session


class NativeEngine:
    def __init__(self,folder,log,language='he',backend='turbo',asr_path=None,translation_path=None):
        self.log=log;self.language=language;self.backend=backend;self.translation_size='milmmt'
        self.asr_path=str(asr_path);self.custom_models=True;self.translation_context=[]
        self.mx=type('Memory',(),{'get_peak_memory':lambda self:0})()
    def warmup(self):pass
    def recognize(self,*args,**kwargs):return ''
    def translate(self,*args,**kwargs):yield '','stop'
    def close(self):pass


class VAD:
    def __init__(self,*args,**kwargs):pass
    def __call__(self,*args):return 0
    def reset(self):pass


class InputStream:
    def __init__(self,**kwargs):pass
    def __enter__(self):return self
    def __exit__(self,*args):pass


class TrackingInputStream(InputStream):
    entered=threading.Event()
    def __enter__(self):
        self.entered.set()
        return self


class Browser:
    def __init__(self):
        self.state={};self.actions=0;self.prepared=False;self.detail_calls=[]
    def details(self,**values):self.state.update(values);self.detail_calls.append(values)
    def read(self):
        self.actions+=1
        return [{'cancel_pending':True}] if self.actions==1 else []
    def keys(self,*unused):return self.read()
    def draw(self,*args):pass
    def prepare_exports(self,session):
        session.close();self.prepared=True


class QuitBeforeStartBrowser(Browser):
    def read(self):
        self.actions+=1
        return ['q'] if self.actions==1 else []


class StartThenQuitBrowser(Browser):
    def read(self):
        self.actions+=1
        if self.actions==1:return [' ']
        if self.actions==2:
            TrackingInputStream.entered.wait(2)
            return ['q']
        return []


def process_engine(*args,**kwargs):
    return ProcessEngine(*args,**kwargs,engine_factory=NativeEngine,startup_timeout=3,
                         shutdown_grace=.2,cancel_grace=.1)


def args(root):
    return SimpleNamespace(models=root/'models',language=None,direction='he-en',topic='none',
                           command='listen',device=None,asr_backend='turbo',ui='browser',
                           start_paused=False,translation_mode=None)


def custom_models(*unused):
    return {'asr':Path('fake-asr'),'translation':Path('fake-translation'),'vad':Path('fake-vad')}


class RuntimeLifecycleTests(unittest.TestCase):
    def test_start_paused_does_not_open_microphone_before_quit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session=Session(root/'logs','he-en',{},save_audio=False)
            browser=QuitBeforeStartBrowser();options=args(root);options.start_paused=True
            TrackingInputStream.entered.clear()
            with patch('hebrew_live.cli.validate_custom_models',custom_models), \
                 patch('hebrew_live.remote_engine.RemoteEngine',side_effect=process_engine), \
                 patch('hebrew_live.cli.VAD',VAD), \
                 patch('sounddevice.query_devices',return_value={'default_samplerate':16000,'name':'fake'}), \
                 patch('sounddevice.InputStream',TrackingInputStream):
                run_session(options,session,browser)
            self.assertFalse(TrackingInputStream.entered.is_set())

    def test_start_paused_opens_microphone_after_start_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session=Session(root/'logs','he-en',{},save_audio=False)
            browser=StartThenQuitBrowser();options=args(root);options.start_paused=True
            TrackingInputStream.entered.clear()
            with patch('hebrew_live.cli.validate_custom_models',custom_models), \
                 patch('hebrew_live.remote_engine.RemoteEngine',side_effect=process_engine), \
                 patch('hebrew_live.cli.VAD',VAD), \
                 patch('sounddevice.query_devices',return_value={'default_samplerate':16000,'name':'fake'}), \
                 patch('sounddevice.InputStream',TrackingInputStream):
                run_session(options,session,browser)
            self.assertTrue(TrackingInputStream.entered.is_set())

    def test_vad_startup_failure_reaps_started_native_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session=Session(root/'logs','he-en',{})
            before={child.pid for child in multiprocessing.active_children()}
            with patch('hebrew_live.cli.validate_custom_models',custom_models), \
                 patch('hebrew_live.remote_engine.RemoteEngine',side_effect=process_engine), \
                 patch('hebrew_live.cli.VAD',side_effect=RuntimeError('fake VAD startup failure')):
                with self.assertRaisesRegex(RuntimeError,'fake VAD startup failure'):
                    run_session(args(root),session)
            self.assertEqual({child.pid for child in multiprocessing.active_children()}-before,set())
            session.close()

    def test_explicit_cancel_wakes_idle_pipeline_and_archives_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session=Session(root/'logs','he-en',{},save_audio=False);browser=Browser()
            started=time.monotonic()
            with patch('hebrew_live.cli.validate_custom_models',custom_models), \
                 patch('hebrew_live.remote_engine.RemoteEngine',side_effect=process_engine), \
                 patch('hebrew_live.cli.VAD',VAD), \
                 patch('sounddevice.query_devices',return_value={'default_samplerate':16000,'name':'fake'}), \
                 patch('sounddevice.InputStream',InputStream), \
                 patch('hebrew_live.runtime.SHUTDOWN_GRACE',.2), \
                 patch('hebrew_live.runtime.CANCEL_GRACE',.1):
                run_session(args(root),session,browser)
            self.assertLess(time.monotonic()-started,2)
            self.assertTrue(browser.prepared)
            manifest=json.loads((session.path/'session.json').read_text())
            self.assertFalse(manifest['audio_saved'])
            self.assertTrue(any(json.loads(line).get('event')=='finished'
                                for path in session.path.glob('*.jsonl') for line in path.read_text().splitlines()))

    def test_unstoppable_python_worker_requires_restart_and_keeps_partial_manifest(self):
        release=threading.Event()
        def stuck_inference(*unused):release.wait(30)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session=Session(root/'logs','he-en',{},save_audio=False);browser=Browser()
            started=time.monotonic()
            try:
                with patch('hebrew_live.cli.validate_custom_models',custom_models), \
                     patch('hebrew_live.remote_engine.RemoteEngine',side_effect=process_engine), \
                     patch('hebrew_live.cli.VAD',VAD),patch('hebrew_live.feed.inference',stuck_inference), \
                     patch('sounddevice.query_devices',return_value={'default_samplerate':16000,'name':'fake'}), \
                     patch('sounddevice.InputStream',InputStream), \
                     patch('hebrew_live.runtime.SHUTDOWN_GRACE',.2), \
                     patch('hebrew_live.runtime.CANCEL_GRACE',.1), \
                     patch('hebrew_live.runtime.WORKER_JOIN_GRACE',.1):
                    run_session(args(root),session,browser)
                self.assertLess(time.monotonic()-started,2)
                self.assertFalse(session.restart_safe);self.assertFalse(browser.prepared)
                self.assertFalse(browser.state['can_start_new'])
                self.assertEqual(browser.state['status_code'],'restart_required')
                manifest=json.loads((session.path/'session.json').read_text())
                self.assertTrue(manifest['partial'])
                self.assertIn('python_worker_shutdown_timeout',
                              {item['reason'] for item in manifest['known_unprocessed']})
                session.close()  # Must not wait on or close handles under the live worker.
            finally:
                release.set();time.sleep(.05)
                session.restart_safe=True;session.close()

    def test_stalled_recording_worker_holding_session_lock_is_tracked_and_not_closed(self):
        release=threading.Event();entered=threading.Event()
        def stuck_transfer(control,raw,session,*unused):
            with session.lock:
                entered.set();release.wait(30)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session=Session(root/'logs','he-en',{},save_audio=False);browser=Browser()
            started=time.monotonic()
            try:
                with patch('hebrew_live.cli.validate_custom_models',custom_models), \
                     patch('hebrew_live.remote_engine.RemoteEngine',side_effect=process_engine), \
                     patch('hebrew_live.cli.VAD',VAD),patch('hebrew_live.runtime.transfer',stuck_transfer), \
                     patch('sounddevice.query_devices',return_value={'default_samplerate':16000,'name':'fake'}), \
                     patch('sounddevice.InputStream',InputStream), \
                     patch('hebrew_live.runtime.SHUTDOWN_GRACE',.2), \
                     patch('hebrew_live.runtime.CANCEL_GRACE',.1), \
                     patch('hebrew_live.runtime.RECORDING_JOIN_GRACE',.1), \
                     patch('hebrew_live.runtime.WORKER_JOIN_GRACE',.1):
                    run_session(args(root),session,browser)
                self.assertTrue(entered.is_set());self.assertLess(time.monotonic()-started,2)
                self.assertFalse(session.restart_safe);self.assertFalse(browser.prepared)
                self.assertEqual(browser.state['status_code'],'restart_required')
                manifest=json.loads((session.path/'session.json').read_text())
                reasons={item['reason'] for item in manifest['known_unprocessed']}
                self.assertIn('python_worker_shutdown_timeout',reasons)
                self.assertFalse(session.parts[1].source.closed)
            finally:
                release.set();time.sleep(.05)
                session.restart_safe=True;session.close()

    def test_runtime_publishes_low_space_partial_state_before_archive_finalization(self):
        from hebrew_live.session import LowStorageError
        def failed_transfer(control,raw,session,*unused):
            session.note_unprocessed(1,None,None,'low_storage','unknown')
            unused[-2].put(LowStorageError('fake full volume'));control.stop.set();raw.put(None)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);session=Session(root/'logs','he-en',{},save_audio=False);browser=Browser()
            with patch('hebrew_live.cli.validate_custom_models',custom_models), \
                 patch('hebrew_live.remote_engine.RemoteEngine',side_effect=process_engine), \
                 patch('hebrew_live.cli.VAD',VAD),patch('hebrew_live.runtime.transfer',failed_transfer), \
                 patch('sounddevice.query_devices',return_value={'default_samplerate':16000,'name':'fake'}), \
                 patch('sounddevice.InputStream',InputStream),patch('hebrew_live.runtime.SHUTDOWN_GRACE',.2):
                run_session(args(root),session,browser)
            partial=[call for call in browser.detail_calls if call.get('status_code')=='partial_processing']
            self.assertTrue(partial);self.assertTrue(partial[0]['partial'])
            self.assertEqual(partial[0]['phase'],'stopping')
            self.assertEqual(partial[0]['partial_details'][0]['reason'],'low_storage')


if __name__=='__main__':unittest.main()
