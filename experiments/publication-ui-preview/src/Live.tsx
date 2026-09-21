import {createContext, memo, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {Button} from '@heroui/react/button';
import {Card} from '@heroui/react/card';
import {Disclosure} from '@heroui/react/disclosure';
import './live.css';
import {useFollowLatest} from './useFollowLatest';
import {archiveRecordingLabel, isVisibleGroup, mergeLiveState, parseLiveState, virtualIndexes} from './liveState';
import type {Group, LiveState, Pair} from './liveState';
import {beginLocaleRequest,directionParts,htmlLanguage,isRtlLanguage,issueText,languageName,reconcileLocale,rollbackLocale,translator} from './i18n';
import type {LocaleRequest,TextKey,UiLocale} from './i18n';

type Translate=(key:TextKey,values?:Record<string,string|number>)=>string;
const I18nContext=createContext<{locale:UiLocale;tx:Translate}>({locale:'en',tx:translator('en')});
const useI18n=()=>useContext(I18nContext);

function Icon({kind}:{kind:string}) {
  const paths:Record<string,string>={trash:'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7',pause:'M8 5v14M16 5v14',play:'m8 5 11 7-11 7Z',stop:'M6 6h12v12H6Z',clear:'m4 16 8-12 8 6-8 12H8l-4-6Zm7 5h10',settings:'M4 7h16M4 17h16M9 4v6M15 14v6',theme:'M20 14a8 8 0 0 1-10-10 8 8 0 1 0 10 10Z',folder:'M3 6h7l2 3h9v11H3Z',down:'M12 4v16m-6-6 6 6 6-6',warning:'M12 3 2 21h20L12 3Zm0 6v5m0 3v1'};
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[kind]||paths.settings}/></svg>;
}

const initialState:LiveState={groups:[],status:'Connecting…',status_code:'connecting',ui_locale:'en',target_language:'en',target_languages:[],paused:true,finished:false,direction:'he-en',phase:'loading'};
const timeoutSignal=()=>AbortSignal.timeout(6000);

async function readJson(url:string,signal?:AbortSignal):Promise<unknown>{
  const requestSignal=signal?AbortSignal.any([signal,timeoutSignal()]):timeoutSignal();
  const response=await fetch(url,{signal:requestSignal});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function BubbleText({pair,direction,originalOpen,onOriginalToggle}:{pair:Pair;direction:string;originalOpen?:boolean;onOriginalToggle?:(open:boolean)=>void}) {
  const {locale,tx}=useI18n();
  const [source,target]=directionParts(direction);const targetRtl=isRtlLanguage(target);
  return <div className="bubble-copy">
    <p className="translation" lang={htmlLanguage(target)} dir={targetRtl?'rtl':'ltr'}>{pair.translation||tx('translating')}</p>
    <details className="bubble-original" open={originalOpen} onToggle={onOriginalToggle?event=>onOriginalToggle(event.currentTarget.open):undefined}>
      <summary>{tx('original')}</summary>
      <div className="bubble-source">
        <span className="bubble-source-label">{tx('recognized',{language:languageName(locale,source,source)})}</span>
        <p lang={htmlLanguage(source)} dir={isRtlLanguage(source)?'rtl':'ltr'}>{pair.source||tx('speechMissing')}</p>
      </div>
    </details>
  </div>;
}

const Speech=memo(function Speech({group,position,onRetry,retrying,retryEnabled,originalOpen,onOriginalToggle}:{group:Group;position:number;onRetry?:(id:string)=>void;retrying:boolean;retryEnabled:boolean;originalOpen:boolean;onOriginalToggle:(id:string,open:boolean)=>void}) {
  const {locale,tx}=useI18n();
  const live=group.live;
  const issue=live?.issue||group.final?.issue;
  const pair=live?.current||group.final||group.final_progress;
  if(!pair&&!issue)return null;
  const shown=pair||{source:'',translation:''};
  const empty=group.complete&&!shown.source.trim()&&!shown.translation.trim();
  if(empty&&!issue)return null;
  const previous=live?.history.find(snapshot=>snapshot.translation.trim());
  const start=shown.start??live?.start;const end=shown.end??live?.end;
  const interval=start!==undefined?` · ${start.toFixed(1)}${end!==undefined?'–'+end.toFixed(1):''} s`:'';
  const [,target]=directionParts(group.direction);
  return <article className={`speech-card chat-bubble ${isRtlLanguage(target)?'chat-bubble--reverse':''} ${issue&&empty?'chat-bubble--issue':''}`} data-group={group.id}>
    {empty
      ? <p className="fragment-failed"><Icon kind="warning"/><span>{tx('fragmentFailed')}<small>{tx('fragment',{number:position})}{interval}</small></span></p>
      : <BubbleText pair={shown} direction={group.direction} originalOpen={originalOpen} onOriginalToggle={open=>onOriginalToggle(group.id,open)}/>
    }
    {!group.complete&&<span className="bubble-status">{tx('draft')}</span>}
    {live?.stage==='technical'&&<span className="bubble-status">{tx('continued')}</span>}
    {issue&&<p className="unavailable bubble-issue">{issueText(locale,issue)}</p>}
    {issue&&onRetry&&<div className="fragment-retry"><Button variant="tertiary" isDisabled={!retryEnabled||retrying} onPress={()=>onRetry(group.id)}>{retrying?tx('retrying'):tx('retry')}</Button>{!retryEnabled&&!retrying&&<small>{tx('pauseFirst')}</small>}</div>}
    {previous&&<Disclosure className="history bubble-history"><Disclosure.Heading><Disclosure.Trigger className="history-trigger">{!previous.label||previous.label==='Предыдущая версия'?tx('previous'):previous.label}<Disclosure.Indicator/></Disclosure.Trigger></Disclosure.Heading><Disclosure.Content><Disclosure.Body className="history-body"><BubbleText pair={previous} direction={group.direction}/></Disclosure.Body></Disclosure.Content></Disclosure>}
  </article>;
});

const ESTIMATED_CARD_HEIGHT=170;
const CARD_GAP=10;
const MessageCards=memo(function MessageCards({groups,scope,scroller,onRetry,retrying,retryEnabled}:{groups:Group[];scope:string;scroller:React.RefObject<HTMLElement|null>;onRetry?:(id:string)=>void;retrying?:string|null;retryEnabled:boolean}){
  const visible=useMemo(()=>groups.flatMap((group,index)=>isVisibleGroup(group)?[{group,position:index+1}]:[]),[groups]);
  const [heights,setHeights]=useState<Record<string,number>>({});
  const heightsRef=useRef<Record<string,number>>({});
  const [openOriginals,setOpenOriginals]=useState<Set<string>>(()=>new Set());
  const [range,setRange]=useState<[number,number]>([0,Math.min(visible.length,12)]);
  const anchorId=useRef<string|null>(null);const [pinnedId,setPinnedId]=useState<string|null>(null);
  const observers=useRef(new Map<string,ResizeObserver>());
  const offsets=useMemo(()=>{const values=[0];for(const {group} of visible)values.push(values.at(-1)!+(heights[group.id]||ESTIMATED_CARD_HEIGHT)+CARD_GAP);return values;},[visible,heights]);
  const total=offsets.at(-1)||0;
  const updateRange=useCallback(()=>{
    const node=scroller.current;if(!node)return;
    const top=node.scrollTop;const bottom=top+node.clientHeight;
    let start=0;while(start<visible.length&&offsets[start+1]<top)start++;
    let end=start;while(end<visible.length&&offsets[end]<bottom)end++;
    anchorId.current=visible[start]?.group.id||null;start=Math.max(0,start-5);end=Math.min(visible.length,end+6);
    setRange(old=>old[0]===start&&old[1]===end?old:[start,end]);
  },[offsets,scroller,visible.length]);
  useEffect(()=>{const node=scroller.current;if(!node)return;updateRange();node.addEventListener('scroll',updateRange,{passive:true});const observer=new ResizeObserver(updateRange);observer.observe(node);return()=>{node.removeEventListener('scroll',updateRange);observer.disconnect();};},[scroller,updateRange]);
  useEffect(()=>{const selection=()=>{const selected=document.getSelection()?.anchorNode;const element=selected instanceof Element?selected:selected?.parentElement;const row=element?.closest<HTMLElement>('[data-virtual-id]');setPinnedId(row?.dataset.virtualId||null);};document.addEventListener('selectionchange',selection);return()=>document.removeEventListener('selectionchange',selection);},[]);
  useEffect(()=>{if(pinnedId&&!visible.some(item=>item.group.id===pinnedId))setPinnedId(null);if(anchorId.current&&!visible.some(item=>item.group.id===anchorId.current))anchorId.current=null;},[pinnedId,visible]);
  useLayoutEffect(updateRange,[total,updateRange]);
  useEffect(()=>()=>{for(const observer of observers.current.values())observer.disconnect();observers.current.clear();},[]);
  const measure=useCallback((id:string,index:number,node:HTMLDivElement|null)=>{
    observers.current.get(id)?.disconnect();observers.current.delete(id);if(!node)return;
    const record=()=>{const height=Math.ceil(node.getBoundingClientRect().height);const old=heightsRef.current;
      if(!height||old[id]===height)return;
      const before=old[id]||ESTIMATED_CARD_HEIGHT;const container=scroller.current;
      heightsRef.current={...old,[id]:height};
      const anchorIndex=anchorId.current===null?-1:visible.findIndex(item=>item.group.id===anchorId.current);
      if(container&&anchorIndex>=0&&index<anchorIndex)container.scrollTop+=height-before;
      setHeights(heightsRef.current);
    };record();const observer=new ResizeObserver(record);observer.observe(node);
    observers.current.set(id,observer);
  },[scroller,visible]);
  const toggleOriginal=useCallback((id:string,open:boolean)=>setOpenOriginals(old=>{const next=new Set(old);if(open)next.add(id);else next.delete(id);return next;}),[]);
  const rendered=useMemo(()=>virtualIndexes(visible.length,range,pinnedId===null?-1:visible.findIndex(item=>item.group.id===pinnedId)),[pinnedId,range,visible]);
  return <div className="virtual-message-list" style={{height:total}} data-rendered-count={rendered.length}>
    {rendered.map(index=>{const {group,position}=visible[index];const [,target]=directionParts(group.direction);return <div key={scope+group.id} ref={node=>{measure(group.id,index,node);}} data-virtual-index={index} data-virtual-id={group.id} className={`virtual-message-row ${isRtlLanguage(target)?'virtual-message-row--reverse':''}`} style={{transform:`translateY(${offsets[index]}px)`}}><Speech group={group} position={position} onRetry={onRetry} retrying={retrying===group.id} retryEnabled={retryEnabled} originalOpen={openOriginals.has(group.id)} onOriginalToggle={toggleOriginal}/></div>;})}
  </div>;
});

function RecordingControls({state,pending,localePending,selected,onAction,dark,setDark,locale,onLocale,settingsRef}:{state:LiveState;pending:boolean;localePending:boolean;selected:boolean;onAction:(action:string,value?:string)=>void;dark:boolean;setDark:(value:boolean)=>void;locale:UiLocale;onLocale:(value:UiLocale)=>void;settingsRef:React.RefObject<HTMLDetailsElement|null>}){
  const {tx}=useI18n();
  const loading=state.phase==='loading'||state.phase==='opening';
  const busy=pending||loading||state.finished||state.stopping||state.model_switching;
  const [source,target]=directionParts(state.direction);
  const direction=tx('direction',{source:languageName(locale,source,source),target:languageName(locale,target,target)});
  const archiveKey=selected?archiveRecordingLabel(state):'';
  const archiveState=archiveKey?tx(archiveKey as TextKey):'';
  const statusKey=state.stopping?(state.cancelling?'cancelling':'finishing'):state.status_code;
  const localizedStatus=statusKey&&['listening','playing_recording','finishing_translation','opening_audio','loading_models','preparing_session','app_closed','finishing','cancelling','session_finished','paused','saved_session','runtime_status'].includes(statusKey)?tx(statusKey as TextKey):state.status;
  const inputKind=state.input_kind==='Файл'?tx('inputFile'):state.input_kind==='Микрофон'?tx('inputMicrophone'):state.input_kind;
  return <section className="live-controls" aria-label={tx('recordingControls')}>
    <div className="live-toolbar">
      <div className="live-status" role="status"><span className={`state-dot ${state.paused||state.stopping?'':'state-dot--closed'}`}/><span><strong>{localizedStatus}</strong><small>{direction}{state.device?' · '+state.device:inputKind?' · '+inputKind:''}{archiveState?' · '+archiveState:''}</small></span></div>
      {state.finished?(state.can_start_new?<Button variant="primary" isDisabled={pending} onPress={()=>onAction('start_session')}><Icon kind="play"/>{tx('newRecording')}</Button>:null):state.stopping?<Button variant="tertiary" className="cancel-processing" isDisabled={pending||state.cancelling} onPress={()=>{if(window.confirm(tx('cancelConfirm')))onAction('cancel_processing');}}><Icon kind="stop"/>{state.cancelling?tx('cancelShort'):tx('cancelRemaining')}</Button>:<div className="session-buttons" role="group" aria-label={tx('recordingControls')}>
        <Button variant="primary" className="finish-button" isDisabled={busy} onPress={()=>onAction('pause')}><Icon kind={state.paused?'play':'pause'}/>{state.paused?tx('continue'):tx('pause')}</Button>
        <Button variant="tertiary" isDisabled={busy} onPress={()=>onAction('stop')}><Icon kind="stop"/>{tx('finishRecording')}</Button>
      </div>}
      <details ref={settingsRef} className="live-settings">
        <summary><Icon kind="settings"/>{tx('settings')}</summary>
        <div className="live-settings-panel">
          <label className="settings-field"><span>{tx('interfaceLanguage')}</span><select value={locale} disabled={pending||localePending} onChange={event=>onLocale(event.target.value as UiLocale)}><option value="en">English</option><option value="ru">Русский</option><option value="he">עברית</option></select></label>
          <label className="settings-field"><span>{tx('targetLanguage')}</span><select value={state.target_language||target} disabled={busy||selected} onChange={event=>onAction('target_language',event.target.value)}>{(state.target_languages||[]).map(item=><option key={item.code} value={item.code}>{languageName(locale,item.code,item.name)}</option>)}</select><small>{tx('targetBoundary')}{state.target_capabilities_assumed?' '+tx('customCapability'):''}</small></label>
          <p className="reading-note">{state.publication==='draft'?tx('readingDraft'):tx('readingEarly')}</p>
          <div className="actions"><Button variant="tertiary" onPress={()=>setDark(!dark)}><Icon kind="theme"/>{dark?tx('lightTheme'):tx('darkTheme')}</Button><Button variant="tertiary" isDisabled={busy} onPress={()=>onAction('clear')}><Icon kind="clear"/>{tx('clearScreen')}</Button></div>
        </div>
      </details>
    </div>
  </section>;
}

export default function Live(){
  const [state,setState]=useState<LiveState>(initialState);
  const [locale,setLocale]=useState<UiLocale>('en');
  const tx=useMemo(()=>translator(locale),[locale]);
  const i18n=useMemo(()=>({locale,tx}),[locale,tx]);
  const localeRequested=useRef<LocaleRequest|null>(null);
  const localeConfirmed=useRef<UiLocale|null>(null);
  const [localePending,setLocalePending]=useState(false);
  const [sessions,setSessions]=useState<{id:string;label:string;title?:string;preview?:string}[]>([]);
  const [sessionsLoaded,setSessionsLoaded]=useState(false);
  const [sessionsError,setSessionsError]=useState('');
  const [sessionsReload,setSessionsReload]=useState(0);
  const [selected,setSelected]=useState('');
  const [archives,setArchives]=useState<Record<string,LiveState>>({});
  const [archiveLoading,setArchiveLoading]=useState('');
  const [archiveError,setArchiveError]=useState('');
  const [archiveRetries,setArchiveRetries]=useState<Record<string,number>>({});
  const [search,setSearch]=useState('');
  const [sidebar,setSidebar]=useState(false);
  const [narrow,setNarrow]=useState(()=>matchMedia('(max-width: 900px)').matches);
  const [dark,setDark]=useState(()=>localStorage.getItem('hebrew-live-theme')==='dark');
  const [connectionError,setConnectionError]=useState('');
  const [actionError,setActionError]=useState('');
  const [lastSuccess,setLastSuccess]=useState<number>();
  const [clock,setClock]=useState(Date.now());
  const [pending,setPending]=useState(false);
  const [closed,setClosed]=useState(false);
  const [deleting,setDeleting]=useState('');
  const [deleteError,setDeleteError]=useState('');
  const settingsRef=useRef<HTMLDetailsElement>(null);
  const sidebarRef=useRef<HTMLElement>(null);
  const openSidebarRef=useRef<HTMLButtonElement>(null);
  const archiveRequestRef=useRef(0);
  const actionContext=useRef({state,closed});
  const actionBusy=useRef(false);
  actionContext.current={state,closed};
  const selectedArchive=selected?archives[selected]:undefined;
  const shown=selected?selectedArchive:state;
  const visibleGroups=shown?.groups||[];
  const shownVisibleGroups=useMemo(()=>visibleGroups.filter(isVisibleGroup),[visibleGroups]);
  const lastGroup=shownVisibleGroups.at(-1);
  const lastPair=lastGroup?.live?.current||lastGroup?.final||lastGroup?.final_progress;
  const followKey=selected?'archive':`${lastGroup?.id||''}:${lastGroup?.revision??''}:${lastPair?.source||''}:${lastPair?.translation||''}`;
  const follow=useFollowLatest(followKey,!selected);

  useEffect(()=>{
    const saved=state.ui_locale;
    if(!saved)return;
    const reconciled=reconcileLocale(saved,localeRequested.current);
    localeRequested.current=reconciled.request;
    setLocale(reconciled.locale);
    if(!reconciled.request)setLocalePending(false);
  },[state.ui_locale]);
  useEffect(()=>{document.documentElement.lang=locale;document.documentElement.dir=locale==='he'?'rtl':'ltr';},[locale]);

  const closeSidebar=useCallback(()=>{setSidebar(false);requestAnimationFrame(()=>openSidebarRef.current?.focus());},[]);
  useEffect(()=>{
    const media=matchMedia('(max-width: 900px)');
    const changed=()=>setNarrow(media.matches);changed();media.addEventListener('change',changed);
    return()=>media.removeEventListener('change',changed);
  },[]);
  useEffect(()=>{
    if(!sidebar||!narrow)return;
    const first=sidebarRef.current?.querySelector<HTMLElement>('button,input');first?.focus();
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();closeSidebar();return;}
      if(event.key!=='Tab'||!sidebarRef.current)return;
      const items=[...sidebarRef.current.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled)')];
      if(!items.length)return;
      const index=items.indexOf(document.activeElement as HTMLElement);
      if(event.shiftKey&&index<=0){event.preventDefault();items.at(-1)?.focus();}
      else if(!event.shiftKey&&index===items.length-1){event.preventDefault();items[0].focus();}
    };
    document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key);
  },[sidebar,narrow,closeSidebar]);

  useEffect(()=>{
    const controller=new AbortController();setSessionsError('');
    void readJson('../sessions',controller.signal).then(value=>{
      if(!Array.isArray(value)||!value.every(item=>typeof item?.id==='string'&&typeof item?.label==='string'&&(item.title===undefined||typeof item.title==='string')&&(item.preview===undefined||typeof item.preview==='string')))throw new Error('bad sessions');
      setSessions(value);setSessionsLoaded(true);
    }).catch(error=>{if(error.name!=='AbortError')setSessionsError(tx('loadSessionsError'));});
    return()=>controller.abort();
  },[state.finished,sessionsReload,tx]);

  const selectedRetry=selected?archiveRetries[selected]||0:0;
  const archiveVersions=useRef<Record<string,number>>({});
  useEffect(()=>{
    if(!selected||archives[selected]&&archiveVersions.current[selected]===selectedRetry)return;
    const request=++archiveRequestRef.current;
    const controller=new AbortController();setArchiveLoading(selected);setArchiveError('');
    void readJson('../session-'+encodeURIComponent(selected),controller.signal).then(parseLiveState).then(value=>{
      if(request!==archiveRequestRef.current)return;
      archiveVersions.current[selected]=selectedRetry;setArchives(old=>({...old,[selected]:value}));
    }).catch(error=>{if(request===archiveRequestRef.current&&error.name!=='AbortError')setArchiveError(tx('openArchiveError'));}).finally(()=>{if(request===archiveRequestRef.current)setArchiveLoading(old=>old===selected?'':old);});
    return()=>{controller.abort();if(request===archiveRequestRef.current)archiveRequestRef.current++;};
  },[selected,selectedRetry,tx]);

  function choose(id:string){
    if(narrow)closeSidebar();else setSidebar(false);
    setArchiveError('');
    if(id===selected)return;
    setSelected(id);
    if(id){follow.stop();follow.containerRef.current?.scrollTo({top:0,behavior:'instant'});}else requestAnimationFrame(follow.resume);
  }
  const currentId=state.session?.split('/').pop();
  useEffect(()=>{if(!selected)requestAnimationFrame(follow.resume);},[state.session]);

  useEffect(()=>{
    const outside=(event:PointerEvent)=>{const el=settingsRef.current;if(el&&!el.contains(event.target as Node))el.open=false;};
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&settingsRef.current)settingsRef.current.open=false;};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);};
  },[]);

  async function deleteSession(item:{id:string;label:string}){
    if(deleting||!window.confirm(tx('deleteConfirm',{label:item.label})))return;
    setDeleting(item.id);setDeleteError('');
    try{
      const response=await fetch('../action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete_session',id:item.id,confirmed:true}),signal:timeoutSignal()});
      if(!response.ok)throw new Error();
      setSessions(old=>old.filter(x=>x.id!==item.id));setArchives(old=>{const copy={...old};delete copy[item.id];return copy;});
      if(selected===item.id)choose('');
    }catch{setDeleteError(tx('deleteError'));}
    finally{setDeleting('');}
  }

  useEffect(()=>{document.title=tx('liveTitle')+' — '+(state.publication!=='phrases'?tx('experimentMode'):tx('ordinaryMode'));},[state.publication,tx]);
  useEffect(()=>{document.documentElement.dataset.theme=dark?'dark':'light';localStorage.setItem('hebrew-live-theme',dark?'dark':'light');},[dark]);
  useEffect(()=>{
    if(!connectionError)return;
    setClock(Date.now());const timer=window.setInterval(()=>setClock(Date.now()),1000);
    return()=>window.clearInterval(timer);
  },[connectionError]);
  useEffect(()=>{
    if(closed)return;
    let cancelled=false,timer:number|undefined;
    async function poll(){
      try{
        let next=parseLiveState(await readJson('../state'));
        if(cancelled)return;
        if(localeConfirmed.current){
          if(next.ui_locale===localeConfirmed.current)localeConfirmed.current=null;
          else next={...next,ui_locale:localeConfirmed.current};
        }
        setState(old=>mergeLiveState(old,next));setLastSuccess(Date.now());setConnectionError('');
        if(next.phase!=='exited')timer=window.setTimeout(poll,next.finished?700:200);
      }catch(error){if(!cancelled){
        const message=error instanceof Error?error.message:'';const name=error instanceof Error?error.name:'';
        const reason=name==='TimeoutError'?tx('timeout'):message.startsWith('Invalid local API')||name==='SyntaxError'?tx('badSnapshot'):message.startsWith('HTTP ')?tx('httpError',{code:message.slice(5)}):tx('noResponse');
        setConnectionError(reason+' '+tx('lastSnapshot'));timer=window.setTimeout(poll,1500);
      }}
    }
    void poll();return()=>{cancelled=true;window.clearTimeout(timer);};
  },[closed,tx]);

  const act=useCallback(async(action:string,value?:string)=>{
    const {state,closed}=actionContext.current;
    const loading=state.phase==='loading'||state.phase==='opening';
    const localeAction=action==='ui_locale';
    if(closed||actionBusy.current||(!localeAction&&((loading&&!['stop','open_archive_folder'].includes(action))||(state.finished&&!['open_folder','open_archive_folder','exports_ready','start_session'].includes(action))||(!['stop','cancel_processing','open_folder','open_archive_folder','exports_ready','start_session'].includes(action)&&(state.stopping||state.model_switching)))))return false;
    actionBusy.current=true;
    setPending(true);setActionError('');
    try{
      const response=await fetch('../action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,value}),signal:timeoutSignal()});
      if(!response.ok)throw new Error();
      if(action==='stop')setState(old=>({...old,stopping:true,phase:'stopping',status_code:'finishing'}));
      if(action==='cancel_processing')setState(old=>({...old,cancelling:true,status_code:'cancelling'}));
      if(action==='start_session')setState(old=>({...old,can_start_new:false}));
      if(action==='exports_ready'){setClosed(true);setState(old=>({...old,phase:'exited',can_start_new:false,status_code:'app_closed'}));}
      return true;
    }catch{setActionError(action==='open_archive_folder'?tx('openFolderError'):tx('actionError'));return false;}
    finally{actionBusy.current=false;setPending(false);}
  },[tx]);
  const onAction=useCallback((action:string,value?:string)=>{void act(action,value);},[act]);
  const retryFragment=useCallback((id:string)=>{void act('retry_fragment',id);},[act]);
  const changeLocale=useCallback(async(value:UiLocale)=>{
    const request=beginLocaleRequest(locale,state.ui_locale,value,localeRequested.current);
    if(!request)return;
    localeRequested.current=request;setLocalePending(true);setLocale(value);
    if(await act('ui_locale',value)){
      localeConfirmed.current=value;localeRequested.current=null;setLocalePending(false);
      setState(old=>({...old,ui_locale:value}));setLocale(value);return;
    }
    if(localeRequested.current===request){
      localeRequested.current=null;setLocalePending(false);
      setLocale(rollbackLocale(actionContext.current.state.ui_locale,request));
    }
  },[act,locale,state.ui_locale]);

  const query=search.trim().toLocaleLowerCase(locale);
  const filtered=sessions.filter(item=>item.id!==currentId&&(!query||[item.label,item.id,item.title||'',item.preview||''].some(value=>value.toLocaleLowerCase(locale).includes(query))));
  const loading=state.phase==='loading'||state.phase==='opening';
  return <I18nContext.Provider value={i18n}><div className={`app-shell live-shell messenger-shell ${sidebar?'sessions-open':''}`}>
    <aside ref={sidebarRef} className="session-sidebar" aria-label={tx('sessions')} role={narrow?'dialog':undefined} aria-modal={narrow||undefined} aria-hidden={narrow&&!sidebar||undefined}>
      <header><h1>{tx('sessions')}</h1><Button variant="tertiary" className="close-sessions" onPress={closeSidebar} aria-label={tx('closeSessions')}>×</Button></header>
      <label className="session-search"><Icon kind="folder"/><input value={search} onChange={event=>setSearch(event.target.value)} placeholder={tx('searchPlaceholder')} aria-label={tx('searchSaved')}/></label>
      <nav aria-label={tx('savedConversations')}>
        <button className={`session-row ${!selected?'selected':''}`} onClick={()=>choose('')} aria-current={!selected?'page':undefined}><span className="session-avatar"><Icon kind="play"/></span><span><strong>{tx('currentSession')}</strong><small>{state.status_code&&['listening','playing_recording','finishing_translation','opening_audio','loading_models','preparing_session','app_closed','finishing','cancelling','session_finished','paused','saved_session'].includes(state.status_code)?tx(state.status_code as TextKey):state.status}</small></span></button>
        <p className="session-list-label">{tx('saved')}</p>
        {filtered.map(item=><div className="session-entry" key={item.id}><button className={`session-row ${selected===item.id?'selected':''}`} onClick={()=>choose(item.id)} aria-current={selected===item.id?'page':undefined}><span className="session-avatar"><Icon kind="folder"/></span><span><strong>{item.title?.startsWith('Разговор ')?item.label:item.title||item.label}</strong><small>{item.preview||item.label}</small><small className="session-date">{item.label}</small></span></button><button className="session-delete" disabled={!!deleting} onClick={()=>void deleteSession(item)} aria-label={tx('deleteSession',{label:item.label})} title={tx('deleteTitle')}><Icon kind="trash"/></button></div>)}
        {sessionsLoaded&&!sessions.length&&<p className="session-list-label">{tx('noneSaved')}</p>}
        {sessionsLoaded&&sessions.length>0&&!filtered.length&&<p className="session-list-label">{tx('nothingFound')}</p>}
        {sessionsError&&<div className="session-list-error" role="alert"><p>{sessionsError}</p><Button variant="tertiary" onPress={()=>setSessionsReload(value=>value+1)}>{tx('retryButton')}</Button></div>}
      </nav>
      {deleteError&&<p className="unavailable" role="alert">{deleteError}</p>}
    </aside>
    <main className="conversation-pane">
      <div className="conversation-title"><Button ref={openSidebarRef} variant="tertiary" className="show-sessions" onPress={()=>setSidebar(true)}><Icon kind="folder"/>{tx('sessions')}</Button><div><strong>{selected?sessions.find(item=>item.id===selected)?.label||tx('savedConversation'):tx('liveTitle')}</strong><small>{selected?tx('readOnly'):tx('onThisMac')}</small></div>{selected&&<Button variant="tertiary" onPress={()=>choose('')}><Icon kind="play"/>{tx('backToLive')}</Button>}</div>
      <RecordingControls state={state} pending={pending} localePending={localePending} selected={!!selected} onAction={onAction} dark={dark} setDark={setDark} locale={locale} onLocale={value=>{void changeLocale(value);}} settingsRef={settingsRef}/>
      {connectionError&&<p className="unavailable global-error" role="alert">{connectionError}{lastSuccess?' '+tx('secondsAgo',{seconds:Math.max(1,Math.floor((clock-lastSuccess)/1000))}):''}</p>}
      {actionError&&<p className="unavailable global-error" role="alert">{actionError}</p>}
      {!selected&&state.retry_error&&<p className="unavailable global-error" role="alert">{issueText(locale,state.retry_error)}</p>}
      {!selected&&state.target_error&&<p className="unavailable global-error" role="alert">{tx(state.target_error_code==='target_preference_not_saved'?'targetPreferenceError':state.target_error_code==='target_busy'?'targetBusyError':'targetChangeError')}</p>}
      {selected&&archiveError&&<div className="archive-error" role="alert"><p className="unavailable">{archiveError}</p><Button variant="tertiary" onPress={()=>{setArchiveRetries(old=>({...old,[selected]:(old[selected]||0)+1}));setArchiveError('');}}>{tx('retryButton')}</Button></div>}
      {selected&&selectedArchive?.warning&&<p role="status" className="reading-note">{selectedArchive.warning==='В журнале есть неполная запись.'?tx('archiveIncomplete'):selectedArchive.warning}</p>}
      <section ref={follow.containerRef} className="live-feed chat-feed" onClickCapture={event=>{if((event.target as HTMLElement).closest('.history'))follow.stop();}} aria-label={tx('feedLabel')}>
        <MessageCards key={`${selected||state.session||'current'}:${shown?.generation??0}`} groups={visibleGroups} scope={selected||'current'} scroller={follow.containerRef} onRetry={selected||!state.retry_supported?undefined:retryFragment} retrying={state.retrying_group} retryEnabled={!selected&&state.paused&&!state.finished&&!state.stopping&&!state.model_switching}/>
        {!shownVisibleGroups.length&&<Card className="speech-card"><Card.Content className="live-empty">{selected?(selectedArchive?tx('noMessages'):archiveError?tx('conversationUnavailable'):archiveLoading===selected?tx('loadingConversation'):tx('chooseAgain')):loading?tx('loadingBeforeRecord'):state.finished?(closed?tx('closed'):state.can_start_new?tx('readyNew'):tx('recordingFinished')):state.paused?tx('readyToSpeak'):state.phase==='listening'?tx('waitingSpeech'):state.status}</Card.Content></Card>}
        {((selected&&selectedArchive)||(!selected&&state.finished))&&<section className="live-exports"><h2>{tx('sessionSaved')}</h2><p>{tx('filesInFolder')}</p><code>{selected?selectedArchive?.session_path:state.session}</code><Button isDisabled={closed||pending} onPress={()=>void act(selected?'open_archive_folder':'open_folder',selected||undefined)}><Icon kind="folder"/>{tx('openFinder')}</Button></section>}
      </section>
      {!selected&&!follow.following&&state.groups.length>0&&<Button className="follow-latest" variant="primary" onPress={follow.resume}><Icon kind="down"/>{tx('backToCurrent')}</Button>}
    </main><footer className="app-footer"><span>{tx('onThisMac')}</span><span>{tx('lateNotBetter')}</span></footer>
  </div></I18nContext.Provider>;
}
