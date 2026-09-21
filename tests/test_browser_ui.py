import json,unittest,urllib.request,urllib.error
from hebrew_live.browser_ui import BrowserUI
from hebrew_live.display import TranslationScreen
from hebrew_live.stream import Control,Settings
import threading

class BrowserTests(unittest.TestCase):
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
