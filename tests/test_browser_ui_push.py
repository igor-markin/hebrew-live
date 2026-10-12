import json,os,socket,threading,time,unittest,urllib.error,urllib.request
from unittest.mock import patch
from hebrew_live import browser_ui
from hebrew_live.browser_ui import BrowserUI,_State
from hebrew_live.display import TranslationScreen
from hebrew_live.stream import Control,Settings

EOF=object()

class EventClient:
    """Minimal raw-socket SSE reader; a read timeout leaves the connection usable."""
    def __init__(self,ui,route='events',host=None):
        self.sock=socket.create_connection(('127.0.0.1',int(ui.host.rsplit(':',1)[1])),timeout=3)
        self.sock.sendall(f'GET /{ui.token}/{route} HTTP/1.1\r\nHost: {host or ui.host}\r\nAccept: text/event-stream\r\n\r\n'.encode())
        self.buffer=b''
        head=self.read_until(b'\r\n\r\n',3.)
        lines=head.decode().split('\r\n')
        self.status=int(lines[0].split()[1])
        self.headers={line.split(':',1)[0].lower():line.split(':',1)[1].strip() for line in lines[1:] if ':' in line}
    def read_until(self,marker,timeout):
        deadline=time.monotonic()+timeout
        while marker not in self.buffer:
            left=deadline-time.monotonic()
            if left<=0:return None
            self.sock.settimeout(left)
            try:chunk=self.sock.recv(65536)
            except socket.timeout:return None
            if not chunk:return EOF
            self.buffer+=chunk
        raw,self.buffer=self.buffer.split(marker,1)
        return raw
    def next(self,timeout=2.):
        """Parsed JSON for a data event, the text of a comment, None on timeout, EOF at close."""
        raw=self.read_until(b'\n\n',timeout)
        if raw is None or raw is EOF:return raw
        text=raw.decode()
        return json.loads(text[6:]) if text.startswith('data: ') else text
    def until(self,predicate,timeout=3.):
        """Collect events until one satisfies predicate; returns (events, matching event)."""
        deadline=time.monotonic()+timeout;events=[]
        while True:
            event=self.next(max(.01,deadline-time.monotonic()))
            if event is None or event is EOF:return events,None
            events.append(event)
            if isinstance(event,dict) and predicate(event):return events,event
    def close(self):self.sock.close()

def quiet(ui):
    ui.finished_seen.set()  # Do not make __exit__ wait for a page that never comes.

class StateCounterTests(unittest.TestCase):
    def test_update_bumps_only_on_real_changes_and_separates_meters(self):
        state=_State({'a':1,'level':0,'groups':[{'id':'x'}]})
        self.assertEqual((state.version,state.meter_version),(0,0))
        state.update(a=1,groups=[{'id':'x'}]);state['a']=1
        self.assertEqual((state.version,state.meter_version),(0,0))
        state['a']=2;self.assertEqual((state.version,state.meter_version),(1,0))
        state.update(level=.5);self.assertEqual((state.version,state.meter_version),(1,1))
        state.update(level=.5,lag=1.);self.assertEqual((state.version,state.meter_version),(1,2))
        state.update(level=.6,a=3);self.assertEqual((state.version,state.meter_version),(2,3))
        state.update(new=True);self.assertEqual(state.version,3)
        self.assertEqual(state['groups'],[{'id':'x'}])

    def test_every_other_mutation_path_bumps(self):
        for name,call in {'pop':lambda s:s.pop('a'),'del':lambda s:s.__delitem__('a'),'setdefault':lambda s:s.setdefault('b',1),
                          'popitem':lambda s:s.popitem(),'clear':lambda s:s.clear(),'ior':lambda s:s.__ior__({'c':1})}.items():
            with self.subTest(name):
                state=_State({'a':1});call(state);self.assertEqual(state.version,1)

class DrawTickTests(unittest.TestCase):
    def test_redrawing_unchanged_screen_is_silent_and_meters_are_separate(self):
        with BrowserUI(open_browser=False) as ui:
            quiet(ui)
            screen=TranslationScreen();control=Control(Settings(),threading.Event())
            screen.update('block_source',1,dict(id='1:1',source='שלום'));ui.draw(screen,control,'')
            version=ui.state.version;ui.draw(screen,control,'');ui.draw(screen,control,'')
            self.assertEqual(ui.state.version,version)  # The 30 ms tick must not wake the stream when nothing changed.
            screen.level=.2;ui.draw(screen,control,'')
            self.assertEqual((ui.state.version,ui.state.meter_version>0),(version,True))
            screen.update('block_translation',1,dict(id='1:1',translation='Привет',complete=True));ui.draw(screen,control,'')
            self.assertGreater(ui.state.version,version)

class EventStreamTests(unittest.TestCase):
    def test_initial_state_then_change_are_pushed(self):
        with BrowserUI(open_browser=False) as ui:
            quiet(ui)
            client=EventClient(ui)
            try:
                self.assertEqual(client.status,200)
                self.assertEqual(client.headers['content-type'],'text/event-stream; charset=utf-8')
                self.assertEqual(client.headers['cache-control'],'no-store')
                self.assertIn("connect-src 'self'",client.headers['content-security-policy'])
                first=client.next()
                self.assertEqual(first,json.loads(json.dumps(ui.state,ensure_ascii=False)))
                with urllib.request.urlopen(ui.url+'state') as response:polled=json.load(response)
                self.assertEqual(polled,first)
                started=time.monotonic()
                ui.details(status='Привет · שלום',device='mic')
                events,event=client.until(lambda item:item.get('status')=='Привет · שלום')
                self.assertIsNotNone(event);self.assertEqual(event['device'],'mic')
                self.assertLess(time.monotonic()-started,.5)
            finally:client.close()

    def test_direct_state_mutations_outside_details_are_pushed(self):
        with BrowserUI(open_browser=False) as ui:
            quiet(ui)
            client=EventClient(ui)
            try:
                client.next()
                with ui.lock:ui.state.update(retrying_group='g1')
                self.assertIsNotNone(client.until(lambda item:item.get('retrying_group')=='g1')[1])
                ui.state['paused']=True
                self.assertIsNotNone(client.until(lambda item:item.get('paused') is True)[1])
                request=urllib.request.Request(ui.url+'action',data=b'{"action":"stop"}',headers={'Content-Type':'application/json','Origin':'http://'+ui.host})
                with urllib.request.urlopen(request) as response:self.assertEqual(response.status,200)
                self.assertIsNotNone(client.until(lambda item:item.get('stopping') is True)[1])
            finally:client.close()

    def test_bursts_are_coalesced_and_noops_are_silent(self):
        with BrowserUI(open_browser=False) as ui:
            quiet(ui)
            client=EventClient(ui)
            try:
                client.next()
                for index in range(50):ui.details(status=f's{index}')
                events,last=client.until(lambda item:item['status']=='s49')
                self.assertIsNotNone(last);self.assertLessEqual(len(events),5)
                started=time.monotonic();levels=30
                for index in range(levels):
                    ui.details(level=.001*(index+1));time.sleep(.01)
                events,last=client.until(lambda item:item['level']==.001*levels)
                elapsed=time.monotonic()-started
                self.assertIsNotNone(last)
                self.assertLessEqual(len(events),elapsed/browser_ui.METER_INTERVAL+2)
                ui.details(status='s49',level=.001*levels)  # Same values: nothing to push.
                self.assertIsNone(client.next(.3))
            finally:client.close()

    def test_keepalive_comment_when_idle(self):
        with patch.object(browser_ui,'KEEPALIVE_INTERVAL',.1),BrowserUI(open_browser=False) as ui:
            quiet(ui)
            client=EventClient(ui)
            try:
                client.next()
                self.assertEqual(client.next(1.),': keepalive')
                ui.details(status='after keepalive')
                self.assertIsNotNone(client.until(lambda item:item['status']=='after keepalive')[1])
            finally:client.close()

    def test_wrong_token_and_host_are_not_found(self):
        with BrowserUI(open_browser=False) as ui:
            quiet(ui)
            for url,headers in [(ui.url.replace(ui.token,'wrong')+'events',{}),(ui.url+'events',{'Host':'evil.invalid'})]:
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(urllib.request.Request(url,headers=headers))
                self.assertEqual(error.exception.code,404)
            client=EventClient(ui,host='evil.invalid')
            try:self.assertEqual(client.status,404)
            finally:client.close()

    def test_environment_switch_turns_the_route_off_but_not_polling(self):
        with patch.dict(os.environ,{'HEBREW_LIVE_UI_PUSH':'0'}),BrowserUI(open_browser=False) as ui:
            quiet(ui)
            self.assertFalse(ui.push_enabled)
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(ui.url+'events')
            self.assertEqual(error.exception.code,404)
            with urllib.request.urlopen(ui.url+'state') as response:self.assertEqual(json.load(response)['phase'],'loading')
        with patch.dict(os.environ,{'HEBREW_LIVE_UI_PUSH':'1'}),BrowserUI(open_browser=False) as ui:
            quiet(ui);self.assertTrue(ui.push_enabled)
        with patch.dict(os.environ):
            os.environ.pop('HEBREW_LIVE_UI_PUSH',None)
            with BrowserUI(open_browser=False) as ui:
                quiet(ui);self.assertTrue(ui.push_enabled)

    def test_polling_and_actions_work_while_streams_are_open(self):
        with BrowserUI(open_browser=False) as ui:
            quiet(ui)
            clients=[EventClient(ui) for _ in range(3)]
            try:
                for client in clients:client.next()
                for _ in range(5):
                    with urllib.request.urlopen(ui.url+'state',timeout=2) as response:self.assertEqual(response.status,200)
                request=urllib.request.Request(ui.url+'action',data=b'{"action":"pause"}',headers={'Content-Type':'application/json','Origin':'http://'+ui.host})
                with urllib.request.urlopen(request,timeout=2) as response:self.assertEqual(response.status,200)
                self.assertEqual(ui.keys(None),[' '])
                ui.details(status='fan-out')
                for client in clients:self.assertIsNotNone(client.until(lambda item:item['status']=='fan-out')[1])
            finally:
                for client in clients:client.close()

    def test_finished_snapshot_on_the_stream_releases_shutdown_like_polling(self):
        with BrowserUI(open_browser=False) as ui:
            client=EventClient(ui)
            try:
                client.next();self.assertFalse(ui.finished_seen.is_set())
                ui.details(finished=True)
                self.assertIsNotNone(client.until(lambda item:item['finished'] is True)[1])
                deadline=time.monotonic()+1
                while not ui.finished_seen.is_set() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(ui.finished_seen.is_set())
            finally:client.close()

    def test_finished_snapshot_with_exports_waits_for_the_page_ack(self):
        with BrowserUI(open_browser=False) as ui:
            ui.exports={'1':(None,'text/plain')}
            client=EventClient(ui)
            try:
                client.next();ui.details(finished=True)
                self.assertIsNotNone(client.until(lambda item:item['finished'] is True)[1])
                time.sleep(.1);self.assertFalse(ui.finished_seen.is_set())
            finally:
                client.close();ui.finished_seen.set()

    def test_shutdown_closes_open_streams_promptly(self):
        ui=BrowserUI(open_browser=False);ui.__enter__()
        clients=[EventClient(ui),EventClient(ui)]
        try:
            for client in clients:client.next()
            quiet(ui)
            started=time.monotonic();ui.__exit__(None,None,None)
            self.assertLess(time.monotonic()-started,1.5)
            for client in clients:
                for _ in range(5):
                    event=client.next(1.)
                    if event is EOF:break
                self.assertIs(event,EOF)
        finally:
            for client in clients:client.close()

    def test_stalled_reader_blocks_neither_state_updates_nor_shutdown(self):
        ui=BrowserUI(open_browser=False);ui.__enter__()
        client=EventClient(ui)
        try:
            client.next()  # Then never read again, so the server's socket buffer fills up.
            slowest=0.
            for index in range(8):
                started=time.monotonic();ui.details(blob=chr(97+index)*2_000_000);slowest=max(slowest,time.monotonic()-started)
                time.sleep(.05)
            self.assertLess(slowest,.5)
            with urllib.request.urlopen(ui.url+'state',timeout=3) as response:self.assertEqual(response.status,200)
            quiet(ui)
            started=time.monotonic();ui.__exit__(None,None,None)
            self.assertLess(time.monotonic()-started,1.5)
        finally:client.close()

if __name__=='__main__':unittest.main()
