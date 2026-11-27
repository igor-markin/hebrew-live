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

PUSH_INTERVAL=.025    # Coalesce bursts of real changes into one push per this many seconds.
METER_INTERVAL=.15    # Audio level and lag change on almost every tick; keep the old polling cadence.
KEEPALIVE_INTERVAL=15.

class _State(dict):
    """Session state that counts real changes, so the push channel never diffs JSON or polls."""
    METERS=frozenset(('level','lag'))
    def __init__(self,*args,**kwargs):
        self.changed=threading.Condition();self.version=self.meter_version=0
        super().__init__(*args,**kwargs)
    def bump(self,significant,meter=False):
        with self.changed:
            if significant:self.version+=1
            if meter:self.meter_version+=1
            self.changed.notify_all()
    def update(self,*args,**kwargs):
        significant=meter=False
        for key,value in dict(*args,**kwargs).items():
            if key not in self or self[key]!=value:
                if key in self.METERS:meter=True
                else:significant=True
            super().__setitem__(key,value)
        if significant or meter:self.bump(significant,meter)
    def __setitem__(self,key,value):self.update({key:value})
def _bumping(name):
    method=getattr(dict,name)
    def wrapper(self,*args,**kwargs):
        try:return method(self,*args,**kwargs)
        finally:self.bump(True)
    return wrapper
for _name in ('__delitem__','pop','popitem','clear','setdefault','__ior__'):setattr(_State,_name,_bumping(_name))

CONTROL_ACTIONS=('pause','stop','start_session')   # shared with the phone's copy (phone_view.py)
UI_LOG_BYTES=262144
UI_LOG_ITEMS=400
# a whole vocabulary from a file: 500 entries of 60 + 120 + 120 letters, each up to six bytes as a
# JSON \u escape (about 0.9 MB)
VOCABULARY_IMPORT_BYTES=1048576
UI_TEXT_LIMIT=4000
UI_LOG_KINDS=('render','click','scroll','key','visibility','resize','follow','settings')

def _number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and value==value else None

def _text(value,limit=UI_TEXT_LIMIT):
    return value[:limit] if isinstance(value,str) else None

def ui_log_entry(item,received,parts):
    """(event name, fields) for one record of the window's log, or None for a malformed one.

    `render` is one version of a bubble as the window drew it: the text on screen, when, and,
    from the publication time the window echoes back, how long after the speech it got there
    (`screen_lag` = the engine's audio lag at publication + publication to drawn). The other
    kinds are the reader's own actions: clicks, scrolling, keys, window focus and size."""
    if not isinstance(item,dict) or item.get('type') not in UI_LOG_KINDS:return None
    kind=item['type'];age=_number(item.get('age_ms'))
    age=max(0.,age/1000) if age is not None else 0.
    if kind=='render':
        group=_text(item.get('group'),128)
        if group is None:return None
        fields=dict(group=group,part=parts.get(group),revision=_number(item.get('revision')),
                    shown=item.get('shown') if item.get('shown') in ('live','stream','none') else 'none',
                    complete=bool(item.get('complete')),source=_text(item.get('source')) or '',
                    translation=_text(item.get('translation')) or '',
                    source_changed=bool(item.get('source_changed')),translation_changed=bool(item.get('translation_changed')),
                    view=_text(item.get('view'),16) or 'cards')
        for key in ('erased_source','erased_translation','frozen_lines'):
            value=_number(item.get(key))
            if value is not None:fields[key]=value
        emitted=_number(item.get('emitted_at'));lag=_number(item.get('audio_lag'))
        if emitted is not None and emitted<=received:
            fields['publish_to_screen']=round(received-age-emitted,4)
            if lag is not None:fields['screen_lag']=round(lag+fields['publish_to_screen'],4)
        return 'ui_render',fields
    fields={}
    for key in ('target','label','key','state','view'):
        value=_text(item.get(key),80)
        if value is not None:fields[key]=value
    for key in ('top','height','client_height','width','following','visible'):
        value=item.get(key)
        if isinstance(value,bool) or _number(value) is not None:fields[key]=value
    fields['age']=round(age,4)
    return 'ui_'+kind,fields

VOCABULARY_LIMIT=500
VOCABULARY_LENGTH={'he':60,'ru':120,'en':120}

def vocabulary_entry(value):
    """(Entry, None) for a valid window entry, else (None, error code). Hebrew must hold a Hebrew
    letter, at least one translation is needed, and every field has a length limit."""
    from . import vocabulary
    if not isinstance(value,dict) or set(value)-set(VOCABULARY_LENGTH):return None,'invalid'
    fields={key:value.get(key,'') for key in VOCABULARY_LENGTH}
    if not all(isinstance(item,str) for item in fields.values()):return None,'invalid'
    fields={key:vocabulary.clean(item) for key,item in fields.items()}
    if not fields['he']:return None,'empty_hebrew'
    if not any('\u05d0'<=letter<='\u05ea' for letter in fields['he']):return None,'not_hebrew'
    if not fields['ru'] and not fields['en']:return None,'no_translation'
    if any(len(fields[key])>limit for key,limit in VOCABULARY_LENGTH.items()):return None,'too_long'
    return vocabulary.Entry(**fields),None

DARK_BACKGROUND='#151d1e'    # --background of :root[data-theme="dark"] in the window's styles.css


def themed_page(data,dark):
    """live.html with the theme on <html> before any script runs: without it the page painted
    light until its state arrived, a white flash on every dark launch (27.11.2026)."""
    data=data.replace(b'<html ',b'<html data-theme="'+(b'dark' if dark else b'light')+b'" ',1)
    if dark:data=data.replace(b'<meta name="theme-color" content="#f6f6f2"/>',
                              b'<meta name="theme-color" content="'+DARK_BACKGROUND.encode()+b'"/>',1)
    return data


class BrowserUI:
    def __init__(self,open_browser=True,live=False,dark_theme=False):
        """`dark_theme`: the saved theme, known before the window first loads (the session's
        preferences arrive later), so the page is served dark from its first frame."""
        self.live=live
        self.desktop_mode=os.environ.get('HEBREW_LIVE_DESKTOP_MANAGED')=='1'
        self.live_root=Path(__file__).with_name('web')
        if live and not (self.live_root/'live.html').is_file():
            raise RuntimeError('Installed package is missing the bundled browser UI')
        self.open_browser=open_browser
        self.token=secrets.token_urlsafe(32)
        self.actions=queue.Queue(maxsize=32)
        self.lock=threading.Lock()
        self.state=_State({'groups':[],'phase':'loading','generation':0,'status':'Загрузка локальных моделей…',
                    'status_code':'loading_models','direction':'he-ru','target_language':'ru',
                    'target_languages':[],'target_error':None,'target_error_code':None,
                    'ui_locale':'en','text_size':'normal','menu_hidden':False,'sessions_hidden':False,'dark_theme':dark_theme is True,'paused':False,'finished':False,
                    'lag':0,'level':0,'retry_supported':True,'save_raw_audio':True,
                    'save_raw_audio_locked':False,'audio_saved':True,'partial':False,'integrity_warning':None,
                    'recording_started':False,'capture_active':False,
                    'input_source':'microphone','input_source_locked':False,'phone_status':None,'input_error':None,
                    'phone_view':False,'phone_view_status':'off','phone_view_url':None})
        self.state['desktop_mode']=self.desktop_mode
        # HEBREW_LIVE_CALM_DRAFTS keeps a shown translation until a refresh is complete; on by
        # default since 23.11.2026 (fewer erased words, measured), =0 rolls it back.
        # Live display experiments, off by default: sentence splits merge into one bubble.
        # HEBREW_LIVE_SENTENCE_CONTEXT=1 freezes closed sentences: one card per speaker turn,
        # a line per sentence, the open part grey, and visible text never shrinks.
        # HEBREW_LIVE_TICKER=1 builds on frozen sentences: closed sentences flow as plain paragraphs
        # that never change, and only the sentence still being spoken is a grey line updated in place.
        ticker=os.environ.get('HEBREW_LIVE_TICKER','0')=='1'
        frozen=ticker or os.environ.get('HEBREW_LIVE_SENTENCE_CONTEXT','0')=='1'
        self.state['calm_drafts']=frozen or os.environ.get('HEBREW_LIVE_CALM_DRAFTS','1')!='0'
        self.state['merge_sentences']=frozen or os.environ.get('HEBREW_LIVE_SENTENCE_SPLIT','0')=='1'
        self.state['frozen_sentences']=frozen
        self.state['ticker_view']=ticker
        # HEBREW_LIVE_APPEND=1: shown text is final, so an open translation is not greyed.
        self.state['append_view']=os.environ.get('HEBREW_LIVE_APPEND','0')=='1'
        # HEBREW_LIVE_UI_PUSH=0 rolls the pages back to polling `state` (the events route answers 404).
        self.push_enabled=os.environ.get('HEBREW_LIVE_UI_PUSH')!='0'
        self.closing=False
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
        self.preview_seen=set()
        self.on_preview_seen=None
        self.phone_check=0
        self.vocabulary_lock=threading.Lock()
        self.phone_probe=None   # Injectable for tests; phone_audio.status otherwise.
        # The read-only copy of the window for the owner's phone (phone_view.py), and the choice
        # it was last asked for: only the latest one is carried out.
        self.phone_view=None
        self.phone_view_ticket=0
        self.phone_view_lock=threading.Lock()
        self.tailscale_probe=None   # Injectable for tests; phone_view.tailscale_address otherwise.

    def __enter__(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass  # Never log the private URL or captions.
            def valid(self):return self.headers.get('Host')==owner.host and self.path.startswith('/'+owner.token+'/')
            def security_headers(self):owner.security_headers(self)
            def reply(self,status,data,kind='application/json; charset=utf-8'):
                self.send_response(status)
                self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
                self.security_headers()
                self.end_headers()
                try:self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):pass
            def stream_state(self):
                """Server-Sent Events: the same JSON as `state`, pushed when it really changes."""
                def pushed(finished):
                    if finished and not owner.exports and owner.session_folder is None:owner.finished_seen.set()
                owner.push_state(self,lambda:owner.state,pushed)
            def do_GET(self):
                if not self.valid():return self.reply(404,b'{}')
                relative=self.path[len('/'+owner.token+'/'):]
                if relative.startswith('live/'):
                    asset=owner.live_asset(relative[5:] or 'live.html')
                    return self.reply(200,*asset) if asset else self.reply(404,b'{}')
                route=self.path.rsplit('/',1)[-1]
                if route=='events' and owner.push_enabled:self.stream_state()
                elif route=='state':
                    with owner.lock:
                        data=json.dumps(owner.state,ensure_ascii=False).encode()
                        finished=owner.state['finished']
                    self.reply(200,data)
                    if finished and not owner.exports and owner.session_folder is None:owner.finished_seen.set()
                elif route=='vocabulary':
                    with owner.vocabulary_lock:self.reply(200,owner.vocabulary_json())
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
                    # A ticker report carries one sentence; a window log batch up to UI_LOG_BYTES;
                    # a vocabulary file up to VOCABULARY_IMPORT_BYTES.
                    if not 0<size<=max(UI_LOG_BYTES,VOCABULARY_IMPORT_BYTES):return self.reply(400,b'{}')
                    payload=json.loads(self.rfile.read(size));action=payload.get('action')
                    limit={'ui_log':UI_LOG_BYTES,'vocabulary_import':VOCABULARY_IMPORT_BYTES}.get(action,8192)
                    if size>limit:return self.reply(400,b'{}')
                    if action=='ui_log':
                        received=time.monotonic()
                        items=payload.get('items')
                        if not isinstance(items,list) or len(items)>UI_LOG_ITEMS:return self.reply(400,b'{}')
                        with owner.lock:
                            event=owner.on_preview_seen
                            parts={item.get('id'):item.get('part') for item in owner.state.get('groups',[]) if isinstance(item,dict)}
                        if event is None:return self.reply(200,b'{"ok":true}')
                        for item in items:
                            entry=ui_log_entry(item,received,parts)
                            if entry is not None:event(entry[0],**entry[1])
                        return self.reply(200,b'{"ok":true}')
                    if action=='ui_preview_seen':
                        identity=payload.get('group');preview_id=payload.get('preview_id')
                        if not isinstance(identity,str) or len(identity)>128 or not isinstance(preview_id,str) or len(preview_id)>64:
                            return self.reply(400,b'{}')
                        with owner.lock:
                            group=next((item for item in owner.state.get('groups',[]) if item.get('id')==identity),None)
                            stream=group.get('stream') if isinstance(group,dict) else None
                            key=(owner.state.get('session'),identity,preview_id)
                            if (not isinstance(stream,dict) or stream.get('preview_id')!=preview_id or
                                    not isinstance(stream.get('preview_emitted_at'),(int,float))):
                                return self.reply(409,b'{}')
                            if key in owner.preview_seen:return self.reply(200,b'{"ok":true}')
                            owner.preview_seen.add(key)
                            event=owner.on_preview_seen
                            part=group.get('part')
                            elapsed=max(0.,time.monotonic()-stream['preview_emitted_at'])
                        if event is not None and isinstance(part,int):
                            event('ui_preview_seen',part=part,group=identity,preview_id=preview_id,
                                  backend_to_dom_ack=elapsed)
                        return self.reply(200,b'{"ok":true}')
                    if action=='ui_ticker':
                        # What the ticker shows for an open sentence: agreed words in black, the rest grey.
                        identity=payload.get('group');black=payload.get('black');grey=payload.get('grey');source=payload.get('source')
                        if (not isinstance(identity,str) or len(identity)>128 or not isinstance(black,str) or
                                not isinstance(grey,str) or len(black)+len(grey)>4000 or source not in ('live','stream')):
                            return self.reply(400,b'{}')
                        with owner.lock:
                            group=next((item for item in owner.state.get('groups',[]) if item.get('id')==identity),None)
                            part=group.get('part') if isinstance(group,dict) else None
                            event=owner.on_preview_seen
                        if event is not None and isinstance(part,int):
                            event('ui_ticker',part=part,group=identity,source=source,black=black,grey=grey)
                        return self.reply(200,b'{"ok":true}')
                    if action=='delete_session':
                        if payload.get('confirmed') is not True:return self.reply(400,b'{}')
                        try:
                            with owner.lock:
                                owner.session_history.delete(payload.get('id'),owner.state.get('session'))
                        except FileNotFoundError:return self.reply(404,b'{}')
                        except PermissionError:return self.reply(409,b'{}')
                        except OSError:return self.reply(500,b'{}')
                        return self.reply(200,b'{"ok":true}')
                    if action in CONTROL_ACTIONS:return self.reply(*owner.control(action,origin='window'))
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
                    if action=='text_size':
                        from .preferences import TEXT_SIZES,save
                        size=payload.get('value')
                        if size not in TEXT_SIZES:return self.reply(400,b'{}')
                        if owner.preference_folder is None:return self.reply(409,b'{}')
                        try:save(owner.preference_folder,text_size=size)
                        except (OSError,ValueError):return self.reply(500,b'{}')
                        with owner.lock:owner.state['text_size']=size
                        return self.reply(200,b'{"ok":true}')
                    if action in ('menu_hidden','sessions_hidden','dark_theme'):
                        from .preferences import save
                        hidden=payload.get('value')
                        if type(hidden) is not bool:return self.reply(400,b'{}')
                        if owner.preference_folder is None:return self.reply(409,b'{}')
                        try:save(owner.preference_folder,**{action:hidden})
                        except (OSError,ValueError):return self.reply(500,b'{}')
                        with owner.lock:owner.state[action]=hidden
                        return self.reply(200,b'{"ok":true}')
                    if action=='phone_view':
                        from .preferences import save
                        value=payload.get('value')
                        if type(value) is not bool:return self.reply(400,b'{}')
                        if owner.preference_folder is None:return self.reply(409,b'{}')
                        try:save(owner.preference_folder,phone_view=value)
                        except (OSError,ValueError):return self.reply(500,b'{}')
                        owner.set_phone_view(value)
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
                    if action=='input_source':
                        value=payload.get('value')
                        if value not in ('microphone','phone'):return self.reply(400,b'{}')
                        with owner.lock:
                            state=owner.state
                            if (state['finished'] or state.get('stopping') or state.get('recording_started') or
                                    state.get('input_source_locked') or owner.preference_folder is None):
                                return self.reply(409,b'{}')
                        from .preferences import save
                        try:save(owner.preference_folder,input_source=value)
                        except (OSError,ValueError):return self.reply(500,b'{}')
                        with owner.lock:owner.state.update(input_source=value,input_error=None)
                        if value=='phone':owner.check_phone()
                        return self.reply(200,b'{"ok":true}')
                    if action=='vocabulary_import':
                        # a file chosen in the vocabulary window: every entry is checked before
                        # anything is saved; a word already in the list keeps its place and takes
                        # the file's translations, a new word goes to the end of the list
                        from . import vocabulary
                        items=payload.get('entries')
                        if not isinstance(items,list) or not items:return self.reply(400,b'{"error":"invalid"}')
                        imported=[]
                        for index,item in enumerate(items):
                            entry,error=vocabulary_entry(item)
                            if error:return self.reply(400,json.dumps({'error':error,'index':index}).encode())
                            imported=[*vocabulary.remove(imported,entry.he),entry]
                        with owner.vocabulary_lock:
                            if vocabulary.damaged():return self.reply(409,b'{"error":"damaged"}')
                            entries=vocabulary.load()
                            known={entry.he:entry for entry in imported}
                            merged=[known.pop(entry.he,entry) for entry in entries]+list(known.values())
                            if len(merged)>max(VOCABULARY_LIMIT,len(entries)):return self.reply(409,b'{"error":"too_many"}')
                            try:vocabulary.save(merged)
                            except OSError:return self.reply(500,b'{}')
                            return self.reply(200,owner.vocabulary_json())
                    if action in ('vocabulary_set','vocabulary_delete'):
                        from . import vocabulary
                        with owner.vocabulary_lock:
                            if vocabulary.damaged():return self.reply(409,b'{"error":"damaged"}')
                            entries=vocabulary.load()
                            if action=='vocabulary_delete':
                                he=payload.get('he')
                                if not isinstance(he,str) or not vocabulary.clean(he):return self.reply(400,b'{}')
                                entries=vocabulary.remove(entries,he)
                            else:
                                entry,error=vocabulary_entry(payload.get('value'))
                                previous=payload.get('previous')
                                if error or previous is not None and not isinstance(previous,str):
                                    return self.reply(400,json.dumps({'error':error or 'invalid'}).encode())
                                place=[item.he for item in entries].index(vocabulary.clean(previous)) if (
                                    previous and vocabulary.clean(previous) in {item.he for item in entries}) else None
                                if place is not None:
                                    # an edit keeps the word's place, even with a new spelling: the order
                                    # says which entry wins when two match the same Hebrew
                                    entries=[entry if index==place else item for index,item in enumerate(entries)
                                             if index==place or item.he!=entry.he]
                                else:
                                    if entry.he not in {item.he for item in entries} and len(entries)>=VOCABULARY_LIMIT:
                                        return self.reply(409,b'{"error":"too_many"}')
                                    entries=vocabulary.add(entries,entry.he,entry.ru,entry.en)
                            try:vocabulary.save(entries)
                            except OSError:return self.reply(500,b'{}')
                            return self.reply(200,owner.vocabulary_json())
                    if action=='check_phone':
                        owner.check_phone()
                        return self.reply(202,b'{"ok":true}')
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
                    if action=='cancel_processing':
                        with owner.lock:
                            if owner.state['finished'] or not owner.stop_requested:return self.reply(409,b'{}')
                            if owner.cancel_requested:return self.reply(200,b'{"ok":true,"already_cancelling":true}')
                            owner.actions.put_nowait({'cancel_pending':True})
                            owner.cancel_requested=True
                            owner.state.update(cancelling=True,status='Отменяю оставшуюся обработку…',status_code='cancelling')
                        return self.reply(200,b'{"ok":true}')
                    key={'clear':'\x0c','direction':'\x14'}.get(action)
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

    @staticmethod
    def security_headers(handler):
        handler.send_header('Cache-Control','no-store');handler.send_header('Referrer-Policy','no-referrer')
        handler.send_header('X-Content-Type-Options','nosniff')
        handler.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'")

    def live_asset(self,name):
        """(bytes, content type) of one file of the packaged window, or None. Exact local build
        members only: a path from a request is never resolved."""
        import mimetypes
        assets={str(p.relative_to(self.live_root)):p for p in self.live_root.rglob('*') if p.is_file() and not p.is_symlink()}
        path=assets.get(name)
        if path is None:return None
        kind=mimetypes.guess_type(name)[0] or 'application/octet-stream'
        data=path.read_bytes()
        # Hide the retired selector in previously built local UI too.
        if name.endswith('.css'):data+=b'\n.live-mode{display:none!important}\n'
        if name=='live.html':
            with self.lock:dark=self.state.get('dark_theme') is True
            data=themed_page(data,dark)
        return data,kind

    def push_state(self,handler,snapshot,pushed=None,stopped=None):
        """Server-Sent Events on `handler`: `snapshot()` (called under `lock`) as JSON whenever the
        state really changes, meters at a calmer pace, a keepalive when nothing changes. Ends when
        the window closes, when `stopped()` turns true, or when the reader goes away."""
        handler.send_response(200)
        handler.send_header('Content-Type','text/event-stream; charset=utf-8')
        self.security_headers(handler)
        handler.end_headers()
        handler.close_connection=True
        handler.connection.settimeout(10.)  # A stalled reader must not pin this thread forever.
        state=self.state;changed=state.changed
        seen=None;pushed_at=written=0.
        try:
            while True:
                with changed:
                    while True:
                        if self.closing or stopped is not None and stopped():return
                        now=time.monotonic()
                        current=(state.version,state.meter_version)
                        if seen is None:due=now
                        elif seen[0]!=current[0]:due=pushed_at+PUSH_INTERVAL
                        elif seen[1]!=current[1]:due=pushed_at+METER_INTERVAL
                        else:due=written+KEEPALIVE_INTERVAL
                        if due<=now:break
                        changed.wait(due-now)
                if seen==current:
                    handler.wfile.write(b': keepalive\n\n');written=time.monotonic()
                    continue
                with self.lock:
                    # Read the counters before the snapshot: a later change is then pushed again, never lost.
                    seen=(state.version,state.meter_version)
                    data=json.dumps(snapshot(),ensure_ascii=False).encode()
                    finished=state['finished']
                handler.wfile.write(b'data: '+data+b'\n\n')
                pushed_at=written=time.monotonic()
                if pushed is not None:pushed(finished)
        except OSError:pass  # Client went away or stopped reading.

    def vocabulary_json(self):
        from dataclasses import asdict
        from . import vocabulary
        return json.dumps({'entries':[asdict(entry) for entry in vocabulary.load()],'damaged':vocabulary.damaged(),
                           'enabled':vocabulary.enabled(),'limit':VOCABULARY_LIMIT,
                           'lengths':VOCABULARY_LENGTH},ensure_ascii=False).encode()

    def set_phone_view(self,enabled):
        """Open or close the phone's read-only copy of this window (phone_view.py) off the request
        thread. Only the latest choice is carried out and published."""
        with self.lock:
            self.phone_view_ticket+=1;ticket=self.phone_view_ticket
            self.state.update(phone_view=enabled,phone_view_status='starting' if enabled else 'off',
                              phone_view_url=self.state.get('phone_view_url') if enabled else None)
        def publish(**values):
            with self.lock:
                if ticket==self.phone_view_ticket:self.state.update(values)
        def run():
            from . import phone_view
            with self.phone_view_lock:
                if ticket!=self.phone_view_ticket or self.closing:return   # a later choice carries on
                current=self.phone_view
                if not enabled:
                    if current:current.stop();self.phone_view=None
                    return
                try:address=(self.tailscale_probe or phone_view.tailscale_address)()
                except Exception:address=None
                if current and current.address==address:
                    return publish(phone_view_status='on',phone_view_url=current.url)
                if current:current.stop();self.phone_view=None
                if address is None:return publish(phone_view_status='no_tailscale',phone_view_url=None)
                try:
                    token=phone_view.load_token(data_root())
                    self.phone_view=phone_view.PhoneView(self,address,token).start()
                except OSError as error:
                    import errno
                    return publish(phone_view_status='port_busy' if error.errno==errno.EADDRINUSE else 'failed',phone_view_url=None)
                publish(phone_view_status='on',phone_view_url=self.phone_view.url)
        threading.Thread(target=run,name='phone-view-switch',daemon=True).start()

    def control(self,action,origin='window'):
        """Start, pause or resume (`pause`), finish (`stop`) or begin the next session
        (`start_session`): the recording controls the window and the phone's copy share.
        Returns (HTTP status, JSON body). A refused press is logged: the phone's page logs nothing else."""
        with self.lock:
            event=self.on_preview_seen
            phone_status=self.state.get('phone_status');finished=self.state['finished']
        status,body=self._control(action)
        if event is not None and status>=400 and not finished:
            try:event('control_refused',action=action,origin=origin,http_status=status,
                      reason=json.loads(body).get('error') if body!=b'{}' else None,phone_status=phone_status)
            except Exception:pass        # the session log may already be closed
        return status,body

    def _control(self,action):
        with self.lock:
            state=self.state
            if action=='start_session':
                if not state['finished'] or not state.get('can_start_new') or self.finished_seen.is_set():return 409,b'{}'
                state.update(can_start_new=False,phase='loading',status='Подготовка новой сессии…',status_code='preparing_session')
                self.next_session.set()
                return 200,b'{"ok":true}'
            if state['finished']:return 409,b'{}'
            if action=='stop':
                # Stop is idempotent. A second HTTP request must never turn
                # into cancellation of translation that was already accepted.
                if self.stop_requested:return 200,b'{"ok":true,"already_stopping":true}'
                try:self.actions.put_nowait('q')
                except queue.Full:return 400,b'{}'
                self.stop_requested=True
                state.update(stopping=True,phase='stopping',status='Завершаю обработку…',status_code='finishing')
                return 200,b'{"ok":true}'
            if action!='pause':return 400,b'{}'
            if self.phone_blocks_start():return 409,b'{"error":"phone_not_ready"}'
        try:self.actions.put_nowait(' ')
        except queue.Full:return 400,b'{}'
        return 200,b'{"ok":true}'

    def phone_blocks_start(self):
        """The phone is chosen but not known to be ready: Start would only fail. Call under `lock`."""
        state=self.state
        return (not state.get('recording_started') and state.get('input_source')=='phone' and
                state.get('phone_status')!='ready')

    def check_phone(self):
        """Ask adb about the phone off the request thread; only the latest check is published."""
        with self.lock:
            self.phone_check+=1;ticket=self.phone_check
            self.state.update(phone_status='checking')
        def run():
            try:
                if self.phone_probe is None:
                    from .phone_audio import status
                    self.phone_probe=status
                code=self.phone_probe()
            except Exception:code='unknown'
            with self.lock:
                if ticket==self.phone_check:self.state.update(phone_status=code)
        threading.Thread(target=run,name='phone-check',daemon=True).start()

    def begin_session(self, session):
        save_audio=getattr(session,'save_audio',True)
        with self.lock:
            self.preview_seen.clear()
            self.on_preview_seen=getattr(session,'event',None)
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
                              recording_started=False,capture_active=False,input_error=None,device=None,input_kind=None,rate=None,channels=None,
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
            with self.state.changed:
                self.closing=True;self.state.changed.notify_all()  # Close open event streams promptly.
            with self.phone_view_lock:
                if self.phone_view:self.phone_view.stop();self.phone_view=None
            self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
            self.keyboard.__exit__(exc_type,exc,tb)
