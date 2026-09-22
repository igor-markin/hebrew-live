import io,json,os,unittest,urllib.request,urllib.error
from unittest.mock import patch
from hebrew_live.browser_ui import BrowserUI
from hebrew_live.display import TranslationScreen
from hebrew_live.stream import Control,Settings
import threading

class BrowserTests(unittest.TestCase):
    def test_desktop_mode_publishes_private_url_on_dedicated_fd_and_starts_ready(self):
        read_fd,write_fd=os.pipe()
        errors=io.StringIO()
        try:
            with patch.dict(os.environ,{'HEBREW_LIVE_DESKTOP_MANAGED':'1','HEBREW_LIVE_DESKTOP_EVENT_FD':str(write_fd)}),patch('sys.stderr',errors),BrowserUI(open_browser=False,live=True) as ui:
                event=json.loads(os.read(read_fd,4096))
                self.assertEqual(event,{'v':1,'event':'backend_ready','url':ui.url+'live/'})
                self.assertNotIn(ui.token,errors.getvalue())
                screen=TranslationScreen();control=Control(Settings(),threading.Event());control.paused=True
                ui.draw(screen,control,'')
                self.assertTrue(ui.state['desktop_mode'])
                self.assertEqual(ui.state['status_code'],'ready_to_start')
                ui.finished_seen.set()
        finally:
            os.close(read_fd);os.close(write_fd)

    def test_private_loopback_state_actions_and_rtl_assets(self):
        with BrowserUI(open_browser=False) as ui:
            self.assertEqual(ui.server.server_address[0],'127.0.0.1')
            s=TranslationScreen();s.update('block_source',1,dict(id='1:1',source='שלום 30'));s.update('block_translation',1,dict(id='1:1',translation='Привет 30',complete=True));s.update('group_final',1,dict(source='שלום 30',translation='Привет всем.'))
            c=Control(Settings(),threading.Event());ui.draw(s,c,'')
            ui.details(device='Test microphone',rate=48000,models={'ASR':'local'})
            with urllib.request.urlopen(ui.url+'state') as r:
                state=json.load(r);self.assertEqual(r.headers['Cache-Control'],'no-store')
            self.assertEqual(state['groups'][0]['blocks'][0]['source'],'שלום 30')
            self.assertEqual(state['groups'][0]['blocks'][0]['translation'],'Привет 30')
            self.assertEqual(state['groups'][0]['correction']['translation'],'Привет всем.')
            self.assertEqual(state['device'],'Test microphone')
            with urllib.request.urlopen(ui.url) as r:self.assertIn(b'app.js',r.read())
            for url,headers,code in [(ui.url.replace(ui.token,'wrong')+'state',{},404),(ui.url+'state',{'Host':'evil.invalid'},404)]:
                with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(urllib.request.Request(url,headers=headers))
                self.assertEqual(err.exception.code,code)
            payload=json.dumps({'action':'pause'}).encode()
            for origin,code in [('http://evil.invalid',403),('http://'+ui.host,200)]:
                request=urllib.request.Request(ui.url+'action',data=payload,headers={'Content-Type':'application/json','Origin':origin})
                if code==200:
                    with urllib.request.urlopen(request) as r:self.assertEqual(r.status,code)
                else:
                    with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(request)
                    self.assertEqual(err.exception.code,code)
            self.assertEqual(ui.keys(s),[' '])
            ui.finished_seen.set()

    def test_export_ids_final_wave_and_ack(self):
        import tempfile
        from pathlib import Path
        import numpy as np
        from hebrew_live.session import Session
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{})
            session.parts[1].write_audio(np.ones(1600,dtype=np.float32)*.1,16000)
            with BrowserUI(open_browser=False) as ui:
                ui.prepare_exports(session)
                with urllib.request.urlopen(ui.url+'export-1') as r:
                    audio=r.read();self.assertEqual(r.headers.get_content_type(),'audio/wav')
                self.assertTrue(session.parts[1].audio.closed)
                for route in ['export-99','export-../../etc/passwd']:
                    with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(ui.url+route)
                    self.assertEqual(err.exception.code,404)
                session.close()
                self.assertEqual(audio,(session.path/'001-he-ru.audio.wav').read_bytes())
                self.assertEqual(len(ui.state['exports']),3)
                ui.details(finished=True)
                request=urllib.request.Request(ui.url+'action',data=b'{"action":"exports_ready"}',headers={'Content-Type':'application/json','Origin':'http://'+ui.host})
                with urllib.request.urlopen(request) as r:self.assertEqual(r.status,200)
                self.assertTrue(ui.finished_seen.is_set())

    def test_quit_requests_stop_and_exits_after_session_finishes(self):
        with BrowserUI(open_browser=False) as ui:
            request=urllib.request.Request(ui.url+'action',data=b'{"action":"quit"}',
                headers={'Content-Type':'application/json','Origin':'http://'+ui.host})
            with urllib.request.urlopen(request) as response:self.assertEqual(response.status,202)
            self.assertTrue(ui.quit_requested);self.assertTrue(ui.stop_requested)
            self.assertEqual(ui.keys(None),['q'])
            self.assertFalse(ui.finished_seen.is_set())
            ui.state['finished']=True
            with urllib.request.urlopen(request) as response:self.assertEqual(response.status,200)
            self.assertTrue(ui.finished_seen.is_set())
            self.assertEqual(ui.state['status_code'],'app_closed')

    def test_no_audio_exports_only_text_and_disables_retry(self):
        import tempfile
        from pathlib import Path
        from hebrew_live.session import Session
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{},save_audio=False)
            with BrowserUI(open_browser=False) as ui:
                ui.begin_session(session);ui.prepare_exports(session)
                self.assertEqual([item['name'] for item in ui.state['exports']],
                                 ['001-he-ru.transcript.txt','001-he-ru.translation.txt'])
                self.assertFalse(ui.state['retry_supported']);self.assertFalse(ui.state['audio_saved'])
                self.assertFalse(any(session.path.glob('*.wav')))
                ui.finished_seen.set()

    def test_cli_audio_retention_override_locks_browser_preference(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, BrowserUI(open_browser=False) as ui:
            ui.preference_folder=Path(tmp);ui.details(save_raw_audio=False,save_raw_audio_locked=True)
            request=urllib.request.Request(ui.url+'action',data=json.dumps({'action':'save_raw_audio','value':True}).encode(),
                headers={'Content-Type':'application/json','Origin':'http://'+ui.host})
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,409);self.assertFalse(ui.state['save_raw_audio'])
            self.assertFalse((Path(tmp)/'preferences.json').exists())
            ui.finished_seen.set()
