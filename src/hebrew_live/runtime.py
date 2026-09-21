"""One inference worker, ordered recording worker, and foreground terminal UI."""
from contextlib import nullcontext
import queue
import sys
import threading
import time

from .display import Terminal, TerminalKeys, TranslationScreen
from .stream import Settings, Control, transfer, replay
from .tuning import DEFAULTS

def read_retry_audio(part, start_seconds, end_seconds):
    """Read an immutable time range from the original WAV and return 16 kHz mono."""
    import soundfile as sf
    if not 0<=start_seconds<end_seconds:raise ValueError('Invalid retry audio range')
    source_rate=part.rate or 16000
    source_start=round(start_seconds*source_rate);source_end=round(end_seconds*source_rate)
    part.audio.flush()
    audio,rate=sf.read(part.audio_path,start=source_start,stop=source_end,dtype='float32',always_2d=False)
    if len(audio)!=source_end-source_start or not len(audio):raise ValueError('Retry audio range is unavailable')
    if getattr(audio,'ndim',1)==2:audio=audio.mean(axis=1)
    if rate!=16000:
        import soxr
        audio=soxr.resample(audio,rate,16000).astype('float32',copy=False)
    return audio

def retry_request_current(request, session, control, browser_ui, stop, cancel, switching_models):
    """Revalidate a browser-admitted retry immediately before reading audio."""
    if browser_ui is None or switching_models or stop.is_set() or cancel.is_set():return False
    with control.lock:
        if not control.paused:return False
    with browser_ui.lock:
        state=browser_ui.state
        if state.get('session')!=request.get('session') or str(session.path)!=request.get('session'):return False
        if state.get('retrying_group')!=request.get('group'):return False
        if state.get('finished') or state.get('stopping') or state.get('model_switching') or not state.get('paused'):return False
        if state.get('generation')!=request.get('generation'):return False
        group=next((item for item in state.get('groups',[]) if item.get('id')==request.get('group')),None)
        live=group.get('live') if isinstance(group,dict) else None
        if not group or not group.get('complete') or not isinstance(live,dict) or not live.get('issue'):return False
        return (group.get('part')==request.get('part') and group.get('direction')==request.get('direction')
                and live.get('start')==request.get('start') and live.get('end')==request.get('end'))


def target_action_blocker(switching_models, stop, cancel):
    """Return the runtime state that invalidates an earlier HTTP admission."""
    if switching_models:return 'model_switch'
    if cancel.is_set():return 'cancelling'
    if stop.is_set():return 'stopping'
    return None


def persist_target_preference(folder, target, save, session):
    """Persist a completed boundary without making storage failure fatal."""
    try:
        save(folder,target_language=target)
    except OSError as exc:
        session.event('target_language_preference_failed',target=target,error=type(exc).__name__)
        return False
    return True


def run_session(args, session, browser_ui=None):
    import sounddevice as sd
    import soundfile as sf
    from .cli import Engine, VAD, Inbox, Fragment, segment, verify, validate_custom_models
    from .feed import inference,RetryRequest
    custom_models=validate_custom_models(args.models,getattr(args,'asr_model',None),
                                         getattr(args,'translation_model',None),getattr(args,'vad_model',None))
    from .preferences import read as read_preferences,save as save_preferences
    from .model_selection import ASR,TRANSLATION
    preference_folder=args.models.parent/'.local-settings'
    if browser_ui:browser_ui.preference_folder=preference_folder
    preferences=read_preferences(preference_folder)
    preference_notices=preferences.get('preference_notices',())
    for notice in preference_notices:session.event('preference_migrated',message=notice)
    draft_limit=preferences.get('draft_max_audio_seconds',20.0)
    session.event('draft_config',max_audio_seconds=draft_limit,catchup_enabled=preferences.get('draft_catchup_enabled',False))
    if preferences.get('models') and not custom_models:
        # Explicit command-line choices override saved browser selections.
        if not any(x=='--asr-backend' or x.startswith('--asr-backend=') for x in sys.argv):args.asr_backend=preferences['models']['asr']
    asr_backend=getattr(args,'asr_backend','turbo')
    from .languages import split_direction,target_language_options
    source_language,target_language=split_direction(args.direction)
    required=set()
    if not custom_models.get('asr'):required.add('asr_multilingual' if asr_backend=='multilingual' else 'asr')
    if not custom_models.get('translation'):required.add('translation')
    if not custom_models.get('vad'):required.add('vad')
    if required:verify(args.models,required)
    asr_label='Custom local MLX Whisper' if custom_models.get('asr') else ASR[asr_backend][0]
    translation_label=('Custom local MLX-LM · MiLMMT prompt contract'
                       if custom_models.get('translation') else TRANSLATION['milmmt'][0])
    if browser_ui:browser_ui.details(models={'Распознавание':asr_label,'Перевод':translation_label,'Проверка языка':'Фильтр письменности; без определения аудиоязыка'},
        target_language=target_language,target_languages=target_language_options(),
        target_capabilities_assumed=bool(custom_models.get('translation')),
        ui_locale=preferences.get('ui_locale','en'),target_error=None,
        model_message=' '.join(preference_notices) if preference_notices else None)
    session.event('effective_models',asr=getattr(args,'asr_backend','turbo'),translation='milmmt',
                  custom_asr=bool(custom_models.get('asr')),custom_translation=bool(custom_models.get('translation')),
                  custom_vad=bool(custom_models.get('vad')))
    print('Loading and warming local models…',file=sys.stderr)
    engine=Engine(args.models,session,args.language or source_language,backend=asr_backend,
                  asr_path=custom_models.get('asr'),
                  translation_path=custom_models.get('translation'))
    from dataclasses import replace
    session.event('language_check_mode',mode='off')
    engine.direction=args.direction;engine.topic=args.topic
    engine.warmup()
    vad=VAD(custom_models.get('vad',args.models/'silero.onnx'))
    stop=threading.Event();cancel=threading.Event()
    control=Control(Settings(draft_catchup_enabled=preferences.get('draft_catchup_enabled',False),draft_max_audio_seconds=draft_limit,direction=args.direction,language=args.language or source_language,topic=args.topic,timing=tuple(preferences['timing'].values()) if preferences.get('timing') else DEFAULTS,mode=getattr(args,'translation_mode',None) or preferences.get('mode','phrases'),publication='draft'),stop)
    if getattr(args,'start_paused',False):
        control.paused=True;control.pause_started=time.monotonic()
    session.event('publication_mode',publication=control.settings.publication)
    session.event('translation_mode',mode=control.settings.mode)
    raw=queue.Queue(maxsize=300);inbox=Inbox();updates=queue.Queue();errors=queue.Queue()
    segmenter=threading.Thread(target=segment,args=(raw,inbox,vad,stop,session,errors),name='segment')
    worker=threading.Thread(target=inference,args=(inbox,engine,updates,stop,errors,session,cancel),name='inference')
    segmenter.start();worker.start()

    def source():
        writer=None
        try:
            file=sf.SoundFile(args.file) if args.command=='benchmark' else None
            with file if file else nullcontext():
                rate=file.samplerate if file else int(sd.query_devices(args.device,'input')['default_samplerate'])
                channels=file.channels if file else 1
                if browser_ui:
                    browser_ui.details(device=str(args.file.name) if file else sd.query_devices(args.device,'input')['name'],
                                       rate=rate,channels=channels,input_kind='Файл' if file else 'Микрофон')
                writer=threading.Thread(target=transfer,args=(control,raw,session,rate,channels,segmenter,errors,updates),name='recording')
                writer.start()
                if file:
                    updates.put(('status',0,'Playing recording'))
                    replay(file,control)
                else:
                    def callback(data,frames,timing,status):
                        try:
                            if status:raise RuntimeError('Audio device overflow/underflow')
                            control.accept(data[:,0],time.monotonic())
                        except Exception as exc:
                            errors.put(exc);stop.set()
                    with sd.InputStream(device=args.device,samplerate=rate,channels=1,dtype='float32',blocksize=rate//10,callback=callback):
                        session.event('device',rate=rate,channels=1)
                        updates.put(('status',0,'Listening'))
                        stop.wait()
        except Exception as exc:
            errors.put(exc);stop.set()
        finally:
            # EOF closes admission before the recording worker's sentinel. Hotkeys
            # during the remaining inference must not create unreachable boundaries.
            with control.lock:
                stop.set()
            updates.put(('status',0,'Finishing accepted audio…'))
            if writer:
                while writer.is_alive():
                    try:control.queue.put(None,timeout=.1);break
                    except queue.Full:pass
                writer.join()
            else:
                raw.put(None)

    source_thread=threading.Thread(target=source,name='source');source_thread.start()
    screen=TranslationScreen();screen.direction=args.direction;screen.topic=args.topic
    terminal=browser_ui is not None or (getattr(args,'ui','auto')!='plain' and sys.stdout.isatty() and sys.stdin.isatty())
    stopping='';interrupts=0;done=False;switching_models=False
    if browser_ui and not custom_models:
        from .model_selection import ASR,TRANSLATION
        browser_ui.details(model_selection=dict(asr=engine.backend,translation=engine.translation_size),model_options={'asr':{k:v[0] for k,v in ASR.items() if (args.models/v[1]).is_dir()},'translation':{k:v[0] for k,v in TRANSLATION.items() if (args.models/v[1]).is_dir()}})
    elif browser_ui:
        browser_ui.details(model_selection=None,model_options={'asr':{},'translation':{}},
                           model_message='Runtime model switching is disabled for explicit local model paths.')
    pipe_finals={}

    def request_stop():
        nonlocal interrupts, stopping
        interrupts+=1
        if interrupts>1:
            request_cancel();return
        stop.set();stopping='Завершаю обработку…'

    def request_cancel():
        nonlocal stopping
        if cancel.is_set():return
        cancel.set();stop.set();stopping='Отменяю оставшуюся обработку…'
        session.event('cancel_requested')

    try:
        with nullcontext(browser_ui) if browser_ui else (Terminal() if terminal else TerminalKeys()) as ui:
            while not done:
                try:
                    keys=ui.keys(screen) if terminal else ui.read()
                    for key in keys:
                        if isinstance(key,dict) and 'retry_fragment' in key:
                            request=key['retry_fragment']
                            try:
                                if not retry_request_current(request,session,control,browser_ui,stop,cancel,switching_models):
                                    raise PermissionError('Retry state changed')
                                part=session.parts[request['part']]
                                audio=read_retry_audio(part,request['start'],request['end'])
                                retry_source,_=split_direction(request['direction'])
                                settings=replace(control.settings,part=request['part'],direction=request['direction'],language=retry_source,publication='draft')
                                fragment=Fragment(9_000_000+int(time.monotonic()*1000)%1_000_000,1,audio,0.,time.monotonic(),True,settings,request['end'],0.,'retry')
                                inbox.put_retry(RetryRequest(fragment,request['group']))
                                session.event('fragment_retry_requested',group=request['group'],start=request['start'],end=request['end'])
                            except Exception as exc:
                                session.event('fragment_retry_rejected',group=request.get('group'),error=type(exc).__name__)
                                if browser_ui:
                                    with browser_ui.lock:
                                        if browser_ui.state.get('retrying_group')==request.get('group'):
                                            browser_ui.state.update(retrying_group=None,retry_error='Состояние сессии изменилось или исходная запись фрагмента недоступна.')
                            continue
                        if isinstance(key,dict) and 'model_selection' in key:
                            if custom_models:
                                session.event('model_switch_rejected',reason='custom_local_model_paths')
                                continue
                            if switching_models or stop.is_set():continue
                            from .model_selection import validate
                            selection=validate(key['model_selection'],args.models)
                            control.switch_models(selection);switching_models=True
                            if browser_ui:browser_ui.details(model_switching=True,model_message='Завершаю принятую речь и загружаю модели…')
                            continue
                        if isinstance(key,dict) and key.get('cancel_pending') is True:
                            request_cancel()
                            continue
                        if isinstance(key,dict) and 'target_language' in key:
                            target=key['target_language']
                            blocker=target_action_blocker(switching_models,stop,cancel)
                            if blocker:
                                session.event('target_language_rejected',target=target,reason=blocker)
                                if browser_ui:browser_ui.details(
                                    target_error='The target language was not changed because the runtime state changed.',
                                    target_error_code='target_busy')
                                continue
                            try:
                                changed=control.switch_target(target)
                            except (ValueError,queue.Full) as exc:
                                session.event('target_language_rejected',target=target,error=type(exc).__name__)
                                if browser_ui:browser_ui.details(
                                    target_error='The target language change could not be queued. Try again.',
                                    target_error_code='target_queue_failed')
                            else:
                                args.direction=control.settings.direction
                                preference_saved=persist_target_preference(
                                    preference_folder,target,save_preferences,session)
                                session.event('target_language_selected',target=target,changed=changed,
                                              boundary='next_captured_audio',preference_saved=preference_saved)
                                if browser_ui:browser_ui.details(direction=control.settings.direction,
                                    target_language=target,
                                    target_error=None if preference_saved else 'The target changed for this session but could not be saved for the next session.',
                                    target_error_code=None if preference_saved else 'target_preference_not_saved')
                            continue
                        if switching_models and key not in ('q','Q','\x03'):continue
                        if isinstance(key,dict) and 'publication' in key:
                            control.switch_publication(key['publication'])
                            save_preferences(preference_folder,publication=key['publication'])
                            session.event('publication_requested',publication=key['publication'])
                            continue
                        if isinstance(key,dict):
                            from .tuning import validate,as_dict
                            timing=validate(key.get('timing_values',key))
                            mode=key.get('mode',control.settings.mode)
                            save_preferences(preference_folder,timing=as_dict(timing),mode=mode)
                            with control.lock:control.settings=replace(control.settings,timing=timing,mode=mode)
                            session.event('timing_requested',mode=mode,**as_dict(timing))
                            continue
                        if key in ('q','Q','\x03'):
                            request_stop()
                            continue
                        if control.key(key):
                            if key=='\x0c':screen.clear(control.settings.generation)
                            if key==' ':screen.level=0
                    if not errors.empty():
                        stop.set();stopping='Error; finishing accepted audio…'
                    for _ in range(100):
                        try:kind,sid,value=updates.get_nowait()
                        except queue.Empty:break
                        if kind=='models_ready':
                            save_preferences(preference_folder,models=value)
                            switching_models=False
                            from .model_selection import ASR,TRANSLATION
                            if browser_ui:browser_ui.details(model_switching=False,model_selection=value,model_message='Модели готовы. Нажми «Продолжить».',models={'Распознавание':ASR[value['asr']][0],'Перевод':TRANSLATION['milmmt'][0],'Проверка языка':'Фильтр письменности; без определения аудиоязыка'},target_languages=target_language_options())
                            continue
                        if kind=='done':done=True;continue
                        if kind=='retry_done':
                            if browser_ui:browser_ui.details(retrying_group=None,retry_error=None)
                            continue
                        if kind=='retry_failed':
                            if browser_ui:browser_ui.details(retrying_group=None,retry_error=value['error'])
                            continue
                        if kind=='level':
                            screen.level=0 if control.paused else value
                        elif kind=='lag':screen.lag=value
                        elif kind=='status':screen.status=value
                        else:
                            screen.update(kind,sid,value)
                            if not terminal:
                                if kind=='live_publication':
                                    print('\nВерсия '+value['stage']+':\n'+value['current']['source']+'\n'+value['current']['translation'],flush=True)
                                if kind=='group_progress':
                                    old=pipe_finals.get(sid,'')
                                    if sid not in pipe_finals:print(('\nУточнение распознавания:\n' if value.get('correction_of') else '\nПеревод:\n' if value.get('phrase') else '\nПолный перевод:\n')+value['source']+'\n',flush=True)
                                    if value['translation'].startswith(old):
                                        print(value['translation'][len(old):],end='',flush=True)
                                        pipe_finals[sid]=value['translation']
                                elif kind=='group_final':
                                    if sid in pipe_finals:
                                        old=pipe_finals.pop(sid)
                                        if value['translation'].startswith(old):print(value['translation'][len(old):],flush=True)
                                        else:print('\n['+value['translation']+']',flush=True)
                                    elif value.get('phrase'):
                                        print(('Уточнение распознавания:\n' if value.get('correction_of') else 'Перевод:\n')+value['source']+'\n'+value['translation'],flush=True)
                                    print('\n'+'─'*48+'\n',flush=True)
                    if terminal:ui.draw(screen,control,stopping)
                    time.sleep(.03)
                except KeyboardInterrupt:
                    request_stop()
    finally:
        stop.set()
        # Also protect teardown from another Ctrl+C while native MLX finishes.
        while any(th.is_alive() for th in (source_thread,segmenter,worker)):
            try:
                for th in (source_thread,segmenter,worker):th.join(.1)
            except KeyboardInterrupt:cancel.set()
        if hasattr(engine,'close'):engine.close()
    if terminal:
        if not browser_ui:print(screen.plain())
        print(f'Session saved: {session.path}',file=sys.stderr)
    if not errors.empty():raise errors.get()
    session.event('finished',cancelled=cancel.is_set())
    if browser_ui and hasattr(browser_ui,'prepare_exports'):browser_ui.prepare_exports(session)
