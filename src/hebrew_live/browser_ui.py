"""Loopback-only browser captions; no external assets or model requests."""
import json
import os
import queue
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .display import TerminalKeys
from .paths import data_root

class BrowserUI:
    def __init__(self,open_browser=True,live=False):
        self.live=live
        self.desktop_mode=os.environ.get('HEBREW_LIVE_DESKTOP_MANAGED')=='1'
        self.live_root=Path(__file__).with_name('web')
        if live and not (self.live_root/'live.html').is_file():
            raise RuntimeError('Installed package is missing the bundled browser UI')
        self.open_browser=open_browser
        self.token=secrets.token_urlsafe(32)
        self.actions=queue.Queue(maxsize=32)
        self.lock=threading.Lock()
        self.state={'groups':[],'phase':'loading','generation':0,'status':'Загрузка локальных моделей…',
                    'status_code':'loading_models','direction':'he-en','target_language':'en',
                    'target_languages':[],'target_error':None,'target_error_code':None,
                    'ui_locale':'en','paused':False,'finished':False,
                    'lag':0,'level':0,'retry_supported':True,'save_raw_audio':True,
                    'save_raw_audio_locked':False,'audio_saved':True,'partial':False,'integrity_warning':None,
                    'recording_started':False,'capture_active':False}
        self.state['desktop_mode']=self.desktop_mode
        self.exports={}
        self.session_folder=None
        self.preference_folder=None
        from .session_history import SessionHistory
        self.session_history=SessionHistory(data_root()/'logs')
        self.finished_seen=threading.Event()
        self.next_session=threading.Event()
        self.stop_requested=False
        self.cancel_requested=False
        self.quit_requested=False

    def __enter__(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass  # Never log the private URL or captions.
            def valid(self):return self.headers.get('Host')==owner.host and self.path.startswith('/'+owner.token+'/')
            def reply(self,status,data,kind='application/json; charset=utf-8'):
                self.send_response(status)
                self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
                self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                try:self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):pass
            def do_GET(self):
                if not self.valid():return self.reply(404,b'{}')
                relative=self.path[len('/'+owner.token+'/'):]
                if relative.startswith('live/'):
                    import mimetypes
                    name=relative[5:] or 'live.html'
                    # Exact local build members only. Never resolve user paths.
                    assets={str(p.relative_to(owner.live_root)):p for p in owner.live_root.rglob('*') if p.is_file() and not p.is_symlink()}
                    path=assets.get(name)
                    if path is None:return self.reply(404,b'{}')
                    kind=mimetypes.guess_type(name)[0] or 'application/octet-stream'
                    data=path.read_bytes()
                    # Hide the retired selector in previously built local UI too.
                    if name.endswith('.css'):data+=b'\n.live-mode{display:none!important}\n'
                    return self.reply(200,data,kind)
                route=self.path.rsplit('/',1)[-1]
                if route=='state':
                    with owner.lock:
                        data=json.dumps(owner.state,ensure_ascii=False).encode()
                        finished=owner.state['finished']
                    self.reply(200,data)
                    if finished and not owner.exports and owner.session_folder is None:owner.finished_seen.set()
                elif route=='sessions':
                    try:self.reply(200,json.dumps(owner.session_history.list(),ensure_ascii=False).encode())
                    except OSError:self.reply(500,b'{}')
                elif route.startswith('session-'):
                    try:self.reply(200,json.dumps(owner.session_history.read(route[8:]),ensure_ascii=False).encode())
                    except FileNotFoundError:self.reply(404,b'{}')
                    except (OSError,ValueError):self.reply(500,b'{}')
                elif route.startswith('export-'):
                    item=owner.exports.get(route[7:])
                    if item is None:return self.reply(404,b'{}')
                    path,kind=item
                    try:self.reply(200,path.read_bytes(),kind)
                    except OSError:self.reply(500,b'{}')
                elif route in ('','app.js','style.css'):
                    name={'':'browser.html','app.js':'browser.js','style.css':'browser.css'}[route]
                    kind={'':'text/html','app.js':'text/javascript','style.css':'text/css'}[route]
                    self.reply(200,(Path(__file__).parent/name).read_bytes(),kind+'; charset=utf-8')
                else:self.reply(404,b'{}')
            def do_POST(self):
                if not self.valid() or not self.path.endswith('/action'):return self.reply(404,b'{}')
                if self.headers.get('Origin')!='http://'+owner.host:return self.reply(403,b'{}')
                if self.headers.get_content_type()!='application/json':return self.reply(415,b'{}')
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=1024:return self.reply(400,b'{}')
                    payload=json.loads(self.rfile.read(size));action=payload.get('action')
                    if action=='delete_session':
                        if payload.get('confirmed') is not True:return self.reply(400,b'{}')
                        try:
                            with owner.lock:
                                owner.session_history.delete(payload.get('id'),owner.state.get('session'))
                        except FileNotFoundError:return self.reply(404,b'{}')
                        except PermissionError:return self.reply(409,b'{}')
                        except OSError:return self.reply(500,b'{}')
                        return self.reply(200,b'{"ok":true}')
                    if action=='start_session':
                        with owner.lock:
                            if not owner.state['finished'] or not owner.state.get('can_start_new') or owner.finished_seen.is_set():return self.reply(409,b'{}')
                            owner.state.update(can_start_new=False,phase='loading',status='Подготовка новой сессии…',status_code='preparing_session')
                            owner.next_session.set()
                        return self.reply(200,b'{"ok":true}')
                    if action=='retry_fragment':
                        identity=payload.get('value')
                        if not isinstance(identity,str) or len(identity)>128:return self.reply(400,b'{}')
                        with owner.lock:
                            if owner.state['finished'] or owner.state.get('stopping') or owner.state.get('model_switching') or not owner.state.get('paused') or not owner.state.get('retry_supported',True):
                                return self.reply(409,b'{}')
                            if owner.state.get('retrying_group') is not None:
                                return self.reply(409,b'{}')
                            group=next((item for item in owner.state.get('groups',[]) if item.get('id')==identity),None)
                            live=group.get('live') if isinstance(group,dict) else None
                            if not group or not group.get('complete') or not isinstance(live,dict) or not live.get('issue'):
                                return self.reply(409,b'{}')
                            start,end=live.get('start'),live.get('end');part=group.get('part')
                            if not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or not 0<=start<end or not isinstance(part,int) or part<1:
                                return self.reply(409,b'{}')
                            owner.actions.put_nowait({'retry_fragment':dict(group=identity,start=start,end=end,part=part,direction=group.get('direction'),session=owner.state.get('session'),generation=owner.state.get('generation'))})
                            owner.state.update(retrying_group=identity,retry_error=None)
                        return self.reply(202,b'{"ok":true}')
                    if action in ('open_folder','open_archive_folder'):
                        folder=owner.session_folder
                        if action=='open_archive_folder':
                            identity=payload.get('value')
                            if not isinstance(identity,str):return self.reply(400,b'{}')
                            folder=owner.session_history.folders().get(identity)
                            if folder is None:return self.reply(404,b'{}')
                        if folder is None:return self.reply(409,b'{}')
                        import subprocess
                        try:subprocess.run(['/usr/bin/open',str(folder)],check=True,timeout=5)
                        except (OSError,subprocess.SubprocessError):return self.reply(500,b'{}')
                        return self.reply(200,b'{"ok":true}')
                    if action=='publication':
                        return self.reply(400,b'{"error":"Only draft publication is supported"}')
                    if action=='models':
                        from .model_selection import validate
                        selection=validate(payload.get('values'))
                        with owner.lock:
                            if owner.state['finished'] or owner.state.get('model_switching'):return self.reply(409,b'{}')
                        owner.actions.put_nowait({'model_selection':selection})
                        return self.reply(200,b'{"ok":true}')
                    if action=='settings':
                        from .tuning import validate,as_dict
                        values=as_dict(validate(payload.get('values')))
                        with owner.lock:
                            if owner.state['finished']:return self.reply(409,b'{}')
                        mode=payload.get('mode')
                        if mode is not None and mode!='phrases':return self.reply(400,b'{}')
                        owner.actions.put_nowait({'timing_values':values,'mode':mode} if mode is not None else values)
                        return self.reply(200,b'{"ok":true}')
                    if action=='ui_locale':
                        locale=payload.get('value')
                        if locale not in ('en','ru','he'):return self.reply(400,b'{}')
                        if owner.preference_folder is None:return self.reply(409,b'{}')
                        from .preferences import save
                        try:save(owner.preference_folder,ui_locale=locale)
                        except OSError:return self.reply(500,b'{}')
                        with owner.lock:owner.state['ui_locale']=locale
                        return self.reply(200,b'{"ok":true}')
                    if action=='save_raw_audio':
                        value=payload.get('value')
                        if type(value) is not bool or owner.preference_folder is None:return self.reply(400,b'{}')
                        if owner.state.get('save_raw_audio_locked'):return self.reply(409,b'{"error":"CLI audio retention override is active"}')
                        from .preferences import save
                        try:save(owner.preference_folder,save_raw_audio=value)
                        except (OSError,ValueError):return self.reply(500,b'{}')
                        with owner.lock:owner.state['save_raw_audio']=value
                        return self.reply(200,b'{"ok":true}')
                    if action=='target_language':
                        target=payload.get('value')
                        with owner.lock:
                            supported={item.get('code') for item in owner.state.get('target_languages',[])
                                       if isinstance(item,dict)}
                            if (owner.state['finished'] or owner.state.get('stopping') or
                                    owner.state.get('model_switching') or target not in supported):
                                return self.reply(409,b'{}')
                        owner.actions.put_nowait({'target_language':target})
                        return self.reply(202,b'{"ok":true}')
                    if action=='exports_ready':
                        with owner.lock:
                            if not owner.state['finished'] or owner.next_session.is_set():return self.reply(409,b'{}')
                            owner.state.update(can_start_new=False,phase='exited',status='Приложение закрыто',status_code='app_closed')
                            owner.finished_seen.set();return self.reply(200,b'{"ok":true}')
                    if action=='quit':
                        with owner.lock:
                            owner.quit_requested=True
                            if owner.state['finished']:
                                owner.state.update(can_start_new=False,phase='exited',status='Приложение закрыто',status_code='app_closed')
                                owner.finished_seen.set()
                                return self.reply(200,b'{"ok":true}')
                            if not owner.stop_requested:
                                owner.actions.put_nowait('q')
                                owner.stop_requested=True
                            owner.state.update(stopping=True,phase='stopping',status='Завершаю обработку…',status_code='finishing')
                        return self.reply(202,b'{"ok":true}')
                    if action=='stop':
                        # Stop is idempotent. A second HTTP request must never turn
                        # into cancellation of translation that was already accepted.
                        with owner.lock:
                            if owner.state['finished']:return self.reply(409,b'{}')
                            if owner.stop_requested:return self.reply(200,b'{"ok":true,"already_stopping":true}')
                            owner.actions.put_nowait('q')
                            owner.stop_requested=True
                            owner.state.update(stopping=True,phase='stopping',status='Завершаю обработку…',status_code='finishing')
                        return self.reply(200,b'{"ok":true}')
                    if action=='cancel_processing':
                        with owner.lock:
                            if owner.state['finished'] or not owner.stop_requested:return self.reply(409,b'{}')
                            if owner.cancel_requested:return self.reply(200,b'{"ok":true,"already_cancelling":true}')
                            owner.actions.put_nowait({'cancel_pending':True})
                            owner.cancel_requested=True
                            owner.state.update(cancelling=True,status='Отменяю оставшуюся обработку…',status_code='cancelling')
                        return self.reply(200,b'{"ok":true}')
                    key={'pause':' ','clear':'\x0c','direction':'\x14'}.get(action)
                    if key is None:return self.reply(400,b'{}')
                    with owner.lock:
                        if owner.state['finished']:return self.reply(409,b'{}')
                    owner.actions.put_nowait(key)
                    self.reply(200,b'{"ok":true}')
                except (ValueError,AttributeError,queue.Full):self.reply(400,b'{}')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=True
        self.host='127.0.0.1:'+str(self.server.server_port)
        self.url='http://'+self.host+'/'+self.token+'/'
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.keyboard=TerminalKeys();self.keyboard.__enter__()
        if self.desktop_mode:
            descriptor=os.environ.get('HEBREW_LIVE_DESKTOP_EVENT_FD')
            if descriptor:
                event={'v':1,'event':'backend_ready','url':self.url+('live/' if self.live else '')}
                os.write(int(descriptor),(json.dumps(event,separators=(',',':'))+'\n').encode('utf8'))
        else:
            print('Локальный экран: '+self.url,file=sys.stderr,flush=True)
        if self.open_browser:webbrowser.open(self.url+('live/' if self.live else ''))
        return self

    def begin_session(self, session):
        save_audio=getattr(session,'save_audio',True)
        with self.lock:
            self.next_session.clear()
            self.finished_seen.clear()
            self.session_folder=None
            self.exports={}
            self.stop_requested=False
            self.cancel_requested=False
            self.quit_requested=False
            self.state.update(groups=[],generation=0,phase='loading',status='Загрузка локальных моделей…',status_code='loading_models',
                              finished=False,paused=False,stopping=False,cancelling=False,model_switching=False,
                              can_start_new=False,exports=[],retrying_group=None,retry_error=None,
                              target_error=None,target_error_code=None,session=str(session.path),
                              recording_started=False,capture_active=False,
                              retry_supported=save_audio,save_raw_audio=save_audio,
                              audio_saved=save_audio,partial=False,partial_kind=None,
                              partial_ranges=[],partial_details=[],capture_discontinuity=False,
                              integrity_warning=None)
        self.session_history.root=session.path.parent
        while not self.actions.empty():
            try:self.actions.get_nowait()
            except queue.Empty:break

    def wait_for_next_session(self, enabled):
        with self.lock:
            self.state.update(finished=True,paused=True,stopping=False,cancelling=False,phase='finished',
                              status='Сессия завершена · модели выгружены',status_code='session_finished',can_start_new=enabled)
            if self.quit_requested:
                self.state.update(can_start_new=False,phase='exited',status='Приложение закрыто',status_code='app_closed')
                self.finished_seen.set()
        while not self.finished_seen.wait(.1):
            if self.next_session.is_set():return True
            if any(key in ('q','Q','\x03') for key in self.keyboard.read()):
                self.finished_seen.set();return False
        return False

    def details(self,**values):
        if values.get("session"):
            self.session_history.root=Path(values["session"]).parent
        with self.lock:self.state.update(values)

    def prepare_exports(self,session):
        entries=[]
        from .languages import LANGUAGES,split_direction
        session.close()  # Finalize WAV headers and the integrity manifest first.
        for number,part in session.parts.items():
            # Workers have stopped. Flush original files before exposing read-only
            # download IDs; no paths supplied by a browser are ever opened.
            # libsndfile rewrites WAV headers on close, not just flush.
            source,target=split_direction(part.direction)
            base=f'{number:03d}-{part.direction}'
            candidates=[('transcript.txt','Original ('+LANGUAGES[source].english_name+')','text/plain; charset=utf-8'),('translation.txt','Translation ('+LANGUAGES[target].english_name+')','text/plain; charset=utf-8')]
            if part.audio_path.is_file():candidates.insert(0,('audio.wav','Source recording','audio/wav'))
            for suffix,label,kind in candidates:
                id=str(len(entries)+1);path=session.path/(base+'.'+suffix)
                self.exports[id]=(path,kind)
                entries.append(dict(id=id,name=path.name,label=label))
        if self.live:
            self.session_folder=session.path.resolve()
            self.exports={};entries=[]
        integrity=session.integrity_view()
        warning=('Session capture or processing is incomplete.' if integrity['partial'] else None)
        with self.lock:self.state.update(exports=entries,session=str(session.path),
                                         integrity_warning=warning,
                                         retry_supported=session.save_audio,**integrity)

    def keys(self,screen):
        keys=list(self.keyboard.read())
        while not self.actions.empty():keys.append(self.actions.get_nowait())
        return keys

    def draw(self,screen,control,stopping):
        labels={'Listening':('Слушаю','listening'),'Playing recording':('Воспроизведение записи','playing_recording'),
                'Finishing accepted audio…':('Завершаю перевод…','finishing_translation'),
                'Opening audio…':('Открываю аудио…','opening_audio')}
        is_stopping=bool(stopping) or self.stop_requested
        if is_stopping:
            status=stopping or self.state.get('status') or 'Завершаю обработку…'
            status_code='cancelling' if self.cancel_requested else 'finishing'
        elif control.paused:
            if self.desktop_mode and not screen.groups:
                status,status_code='Готово к началу','ready_to_start'
            else:
                status,status_code='Пауза','paused'
        else:
            status,status_code=labels.get(screen.status,(screen.status,'runtime_status'))
        from .tuning import DEFAULTS,as_dict
        defaults=DEFAULTS
        with self.lock:
            self.state.update(mode=control.settings.mode,publication=control.settings.publication,
                              phase='stopping' if is_stopping else 'paused' if control.paused else 'listening' if screen.status in ('Listening','Playing recording') else 'opening')
            current=control.settings.timing or defaults
            self.state.update(timing=as_dict(current),timing_defaults=as_dict(defaults))
            from .languages import split_direction
            _,target=split_direction(control.settings.direction)
            self.state.update(groups=json.loads(json.dumps(list(screen.groups.values()),ensure_ascii=False)),generation=screen.generation,first_text_delay=getattr(screen,'first_text_delay',None),status=status,status_code=status_code,direction=control.settings.direction,target_language=target,
                              paused=control.paused,lag=screen.lag,level=screen.level,stopping=is_stopping,cancelling=self.cancel_requested)

    def __exit__(self,exc_type,exc,tb):
        with self.lock:
            self.state.update(finished=True,level=0,phase='error' if exc else self.state.get('phase','finished'),status='Сессия завершена' if not exc else 'Сессия остановлена из-за ошибки; подробности в терминале')
        # Let an open page receive the final snapshot before closing the local server.
        try:
            self.finished_seen.wait(None if self.session_folder is not None else (30 if self.exports else 1.5))
        finally:
            self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
            self.keyboard.__exit__(exc_type,exc,tb)
