import json
import logging
import queue
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from hebrew_live.browser_ui import BrowserUI
from hebrew_live.session import Session, LibraryHandler

class SessionBrowserTests(unittest.TestCase):
    def test_retry_fragment_requires_paused_failed_group_and_queues_exact_range(self):
        with BrowserUI(open_browser=False) as ui:
            def post(value):
                request=urllib.request.Request(ui.url+'action',data=json.dumps(dict(action='retry_fragment',value=value)).encode(),headers={'Content-Type':'application/json','Origin':'http://'+ui.host})
                return urllib.request.urlopen(request)
            try:
                ui.details(paused=True,groups=[dict(id='0:3000001',part=1,direction='he-ru',complete=True,
                    live=dict(current=dict(source='',translation=''),history=[],stage='unavailable',issue='Ошибка',start=1.25,end=2.5))])
                with post('0:3000001') as response:self.assertEqual(response.status,202)
                with self.assertRaises(urllib.error.HTTPError) as duplicate:post('0:3000001')
                self.assertEqual(duplicate.exception.code,409)
                self.assertEqual(ui.actions.get_nowait(),{'retry_fragment':dict(group='0:3000001',start=1.25,end=2.5,part=1,direction='he-ru',session=None,generation=0)})
                self.assertEqual(ui.state['retrying_group'],'0:3000001')
                ui.details(paused=False,retrying_group=None)
                with self.assertRaises(urllib.error.HTTPError) as error:post('0:3000001')
                self.assertEqual(error.exception.code,409)
                with self.assertRaises(urllib.error.HTTPError):post('../audio.wav')
            finally:ui.finished_seen.set()

    def test_begin_session_clears_retry_state_and_stale_retry_action(self):
        with tempfile.TemporaryDirectory() as tmp, BrowserUI(open_browser=False) as ui:
            ui.details(retrying_group='old',retry_error='old error')
            ui.actions.put_nowait({'retry_fragment':{'group':'old'}})
            session=SimpleNamespace(path=Path(tmp)/'20260919-120000-11111111')
            ui.begin_session(session)
            self.assertIsNone(ui.state['retrying_group']);self.assertIsNone(ui.state['retry_error'])
            self.assertTrue(ui.actions.empty())

    def test_stop_is_idempotent_and_cancellation_is_explicit(self):
        with BrowserUI(open_browser=False) as ui:
            def post(action):
                request=urllib.request.Request(ui.url+'action',data=json.dumps(dict(action=action)).encode(),headers={'Content-Type':'application/json','Origin':'http://'+ui.host})
                with urllib.request.urlopen(request) as response:return json.load(response)
            try:
                self.assertEqual(post('stop'),{'ok':True})
                self.assertTrue(post('stop')['already_stopping'])
                self.assertEqual(ui.actions.get_nowait(),'q')
                with self.assertRaises(queue.Empty):ui.actions.get_nowait()
                self.assertEqual(post('cancel_processing'),{'ok':True})
                self.assertTrue(post('cancel_processing')['already_cancelling'])
                self.assertEqual(ui.actions.get_nowait(),{'cancel_pending':True})
                with self.assertRaises(queue.Empty):ui.actions.get_nowait()
            finally:ui.finished_seen.set()

    def test_history_routes_and_single_restart_admission(self):
        with tempfile.TemporaryDirectory() as tmp, BrowserUI(open_browser=False) as ui:
            folder=Path(tmp)/'20260910-210902-35bb9f4c';folder.mkdir()
            (folder/'001-he-ru.diagnostics.jsonl').write_text(json.dumps(dict(event='live_publication',segment=1,current=dict(source='שלום',translation='Привет'),history=[],stage='closed'))+'\n')
            ui.begin_session(SimpleNamespace(path=folder))
            with urllib.request.urlopen(ui.url+'sessions') as response:
                self.assertEqual(json.load(response)[0]['id'],folder.name)
            with urllib.request.urlopen(ui.url+'session-'+folder.name) as response:
                self.assertEqual(json.load(response)['groups'][0]['live']['current']['translation'],'Привет')
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(ui.url+'session-not-a-folder')
            ui.details(finished=True,can_start_new=True,phase='finished')
            def post(action):
                return urllib.request.urlopen(urllib.request.Request(ui.url+'action',data=json.dumps(dict(action=action)).encode(),headers={'Content-Type':'application/json','Origin':'http://'+ui.host}))
            with post('start_session') as response:self.assertEqual(response.status,200)
            with self.assertRaises(urllib.error.HTTPError):post('start_session')
            with self.assertRaises(urllib.error.HTTPError):post('exports_ready')
            self.assertTrue(ui.next_session.is_set())
            ui.begin_session(SimpleNamespace(path=folder))
            self.assertFalse(ui.state['finished']);self.assertEqual(ui.state['phase'],'loading')
            self.assertEqual(ui.state['groups'],[]);self.assertFalse(ui.next_session.is_set())
            ui.finished_seen.set()

    def test_delete_http_requires_confirmation_and_protects_current(self):
        with tempfile.TemporaryDirectory() as tmp, BrowserUI(open_browser=False) as ui:
            current=Path(tmp)/'20260910-210902-35bb9f4c';current.mkdir()
            old=Path(tmp)/'20260910-195531-f80c667f';old.mkdir()
            (old/'log').write_text('saved')
            ui.begin_session(SimpleNamespace(path=current))
            def post(payload,origin=None):
                return urllib.request.urlopen(urllib.request.Request(ui.url+'action',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':origin or 'http://'+ui.host}))
            try:
                for payload,origin,code in [({'action':'delete_session','id':old.name},None,400),({'action':'delete_session','id':current.name,'confirmed':True},None,409),({'action':'delete_session','id':old.name,'confirmed':True},'http://evil.invalid',403)]:
                    with self.assertRaises(urllib.error.HTTPError) as error:post(payload,origin)
                    self.assertEqual(error.exception.code,code)
                    self.assertTrue((old/'log').exists())
                with post({'action':'delete_session','id':old.name,'confirmed':True}) as response:self.assertEqual(response.status,200)
                self.assertFalse(old.exists());self.assertTrue(current.exists())
            finally:ui.finished_seen.set()

    def test_open_archive_folder_during_loading_uses_selected_id(self):
        with tempfile.TemporaryDirectory() as tmp, BrowserUI(open_browser=False) as ui:
            current=Path(tmp)/'20260910-210902-35bb9f4c';current.mkdir()
            old=Path(tmp)/'20260910-195531-f80c667f';old.mkdir()
            ui.begin_session(SimpleNamespace(path=current))
            def post(value,origin=None):
                return urllib.request.urlopen(urllib.request.Request(ui.url+'action',data=json.dumps(dict(action='open_archive_folder',value=value)).encode(),headers={'Content-Type':'application/json','Origin':origin or 'http://'+ui.host}))
            try:
                with patch('subprocess.run') as opener:
                    for value,origin in [('../'+old.name,None),(old.name,'http://evil.invalid')]:
                        with self.assertRaises(urllib.error.HTTPError):post(value,origin)
                    opener.assert_not_called()
                    with post(old.name) as response:self.assertEqual(response.status,200)
                    self.assertEqual(opener.call_args.args[0],['/usr/bin/open',str(old)])
                self.assertEqual(ui.state['session'],str(current))
                self.assertEqual(ui.session_history.read(old.name)['session_path'],str(old.resolve()))
            finally:ui.finished_seen.set()

    def test_two_runs_use_fresh_session_and_log_handler(self):
        from hebrew_live.cli import run
        with tempfile.TemporaryDirectory() as tmp:
            original=Session(Path(tmp),'he-ru',{})
            handler=LibraryHandler(original);logging.getLogger().addHandler(handler)
            args=SimpleNamespace(ui='browser',publication='draft',no_open_browser=True,asr_backend='turbo',translation_size='milmmt',direction='he-ru',topic='none',command='listen',log_dir=Path(tmp))
            class FakeBrowser:
                def __init__(self,**kwargs):self.turn=0
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def details(self,**kwargs):pass
                def begin_session(self,session):pass
                def wait_for_next_session(self,enabled):
                    self.turn+=1
                    return self.turn==1
            seen=[]
            def fake_run(args,session,browser_ui):
                self.assertIs(handler.log,session)
                seen.append(session.path)
                session.event('fake_finished')
            try:
                with patch('hebrew_live.browser_ui.BrowserUI',FakeBrowser),patch('hebrew_live.runtime.run_session',fake_run):run(args,original)
                self.assertEqual(len(set(seen)),2)
                self.assertTrue(all((p/'001-he-ru.diagnostics.jsonl').is_file() for p in seen))
                self.assertTrue(handler.log.parts[1].log.closed)
            finally:
                logging.getLogger().removeHandler(handler);handler.close();original.close()
