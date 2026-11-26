import {createContext, memo, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {Button} from '@heroui/react/button';
import {Card} from '@heroui/react/card';
import {Disclosure} from '@heroui/react/disclosure';
import './live.css';
import {useFollowLatest} from './useFollowLatest';
import {openStateStream} from './liveStream';
import {UiLog,clickTarget,renderRecords} from './uiLog';
import {TEXT_SIZES,TEXT_SIZE_KEY,textSize,translationPixels} from './textSize';
import type {TextSize} from './textSize';
import {MENU_HIDDEN_KEY,SESSIONS_HIDDEN_KEY,storedHidden,storedValue} from './layout';
import type {Drawn} from './uiLog';
import {agreeWords, agreedSplit, archiveRecordingLabel, figureParts, shownSource, heldText, isQuietMiss, isVisibleGroup, mergeLiveState, dayNotes, numberNotes, parseLiveState, parseVocabulary, shortHebrew, partialNoticeKind, phoneBlocksStart, phoneStatusText, shownPair, speechTurns, tickerParagraphs, unchangedPrefix, virtualIndexes} from './liveState';
import type {Agreement, Group, LiveState, Pair, SpeechTurn, TickerParagraph, VocabularyEntry, VocabularyList} from './liveState';
import {beginLocaleRequest,directionParts,htmlLanguage,isRtlLanguage,issueText,languageName,reconcileLocale,rollbackLocale,translator} from './i18n';
import type {LocaleRequest,TextKey,UiLocale} from './i18n';

declare global {
  interface Window {hebrewLive?:{requestQuit:()=>Promise<void>;showHelp:()=>Promise<void>;setUiLocale:(value:'en'|'ru')=>Promise<unknown>}}
}

type Translate=(key:TextKey,values?:Record<string,string|number>)=>string;
const I18nContext=createContext<{locale:UiLocale;tx:Translate}>({locale:'en',tx:translator('en')});
const useI18n=()=>useContext(I18nContext);
// Live display experiments the engine switched on (HEBREW_LIVE_CALM_DRAFTS, HEBREW_LIVE_SENTENCE_SPLIT,
// HEBREW_LIVE_SENTENCE_CONTEXT for frozen sentences, HEBREW_LIVE_TICKER for the ticker view).
const DisplayContext=createContext({calm:false,merge:false,frozen:false,ticker:false,append:false});

function Icon({kind}:{kind:string}) {
  const paths:Record<string,string>={trash:'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7',pause:'M8 5v14M16 5v14',play:'m8 5 11 7-11 7Z',stop:'M6 6h12v12H6Z',power:'M12 3v9m6.4-5.4a8 8 0 1 1-12.8 0',help:'M9.1 9a3 3 0 1 1 4.8 2.4c-1 .7-1.9 1.2-1.9 2.6m0 4h.01M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z',clear:'m4 16 8-12 8 6-8 12H8l-4-6Zm7 5h10',settings:'M4 7h16M4 17h16M9 4v6M15 14v6',theme:'M20 14a8 8 0 0 1-10-10 8 8 0 1 0 10 10Z',folder:'M3 6h7l2 3h9v11H3Z',sidebar:'M4 4h16v16H4ZM9 4v16',up:'m6 15 6-6 6 6',expand:'m6 9 6 6 6-6',down:'M12 4v16m-6-6 6 6 6-6',warning:'M12 3 2 21h20L12 3Zm0 6v5m0 3v1'};
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

/** Text whose unchanged leading words stay still; only the words that differ from the last render fade in. */
function ChangingText({text:incoming,hold=false}:{text:string;hold?:boolean}) {
  // Compared with the previous distinct text, so an unrelated re-render keeps the fade.
  const {calm}=useContext(DisplayContext);
  const seen=useRef({before:incoming,shown:incoming});
  if(!calm)return <>{incoming}</>;
  const text=heldText(seen.current.shown,incoming,hold);
  if(seen.current.shown!==text)seen.current={before:seen.current.shown,shown:text};
  const kept=unchangedPrefix(seen.current.before,text);
  if(kept>=text.length)return <>{text}</>;
  return <>{text.slice(0,kept)}<span className="text-fresh" key={text}>{text.slice(kept)}</span></>;
}

type Segment={id:string;pair:Pair;pending?:boolean;hebrew?:string};

/** Text with its figures (times, dates, sums, numbers) marked, so the eye finds them first. */
function Figures({text}:{text:string}) {
  return <>{figureParts(text).map((part,index)=>part.figure?<mark key={index} className="figure">{part.text}</mark>:part.text)}</>;
}

// What two versions in a row of each open translation agreed on (see agreeWords).
const agreements=new Map<string,Agreement>();

/** An open translation: the words two versions agreed on in the normal colour, the rest grey until
 * a later version confirms it. A closed one is all normal. */
function TranslationText({id,text,pending}:{id:string;text:string;pending?:boolean}) {
  // In the append-only view every shown word is final.
  const {append}=useContext(DisplayContext);
  if(!pending||append){agreements.delete(id);return <Figures text={text}/>;}
  const next=agreeWords(agreements.get(id),text);agreements.set(id,next);
  const [agreed,rest]=agreedSplit(text,next.agreed);
  return <>{agreed&&<Figures text={agreed}/>}{agreed&&rest?' ':''}{rest&&<span className="text-pending"><Figures text={rest}/></span>}</>;
}

/** One bubble's text: closed sentences in the normal colour, the still open part in grey. */
function SegmentText({segments,field,missing}:{segments:Segment[];field:'translation'|'source';missing:string}) {
  const {merge,frozen}=useContext(DisplayContext);
  const text=(segment:Segment)=>field==='source'?segment.hebrew??segment.pair.source:segment.pair.translation;
  const body=(segment:Segment)=>{
    const value=text(segment);
    if(!value)return missing;
    if(field==='source')return <Figures text={value}/>;
    return <TranslationText id={segment.id} text={value} pending={segment.pending}/>;
  };
  if(frozen)return <>{segments.map(segment=>
    // A line per sentence; a closed one never changes again.
    <span key={segment.id} className="sentence-line">{body(segment)}</span>)}</>;
  return <>{segments.map((segment,index)=>
    <span key={segment.id} className={merge&&segment.pending&&field==='source'?'text-pending':undefined}>{index?' ':''}{body(segment)}</span>)}</>;
}

/** Height a card keeps while its turn is open, so a closing sentence or a slower refresh never pulls the text under the reader upwards. */
function useNoShrink(open:boolean) {
  const ref=useRef<HTMLElement|null>(null);const tallest=useRef({height:0,width:0});
  useLayoutEffect(()=>{
    const node=ref.current;if(!node)return;
    if(!open){tallest.current={height:0,width:0};node.style.minHeight='';return;}
    const record=()=>{const {width}=node.getBoundingClientRect();
      // A narrower or wider window rewraps the text: the old height means nothing then.
      if(width!==tallest.current.width){tallest.current={height:0,width};node.style.minHeight='';}
      const natural=node.getBoundingClientRect().height;
      if(natural>tallest.current.height){tallest.current.height=natural;node.style.minHeight=`${natural}px`;}};
    record();const observer=new ResizeObserver(record);observer.observe(node);
    return()=>observer.disconnect();
  });
  return ref;
}

/** Hebrew as it is heard, above its translation in larger type; both always visible. */
function BubbleText({pair,segments,direction}:{pair?:Pair;segments?:Segment[];direction:string}) {
  const {tx}=useI18n();
  const [source,target]=directionParts(direction);const targetRtl=isRtlLanguage(target);
  const parts=segments||[{id:'only',pair:pair!}];
  return <div className="bubble-copy">
    <p className="bubble-hebrew" lang={htmlLanguage(source)} dir={isRtlLanguage(source)?'rtl':'ltr'}><SegmentText segments={parts} field="source" missing={tx('speechMissing')}/></p>
    <p className="translation" lang={htmlLanguage(target)} dir={targetRtl?'rtl':'ltr'}><SegmentText segments={parts} field="translation" missing={tx('translating')}/></p>
  </div>;
}

/** A calm note under a closed bubble whose figures differ between source and translation. */
function NumberNote({groups}:{groups:Group[]}) {
  const {tx}=useI18n();
  const notes=numberNotes(groups);
  return notes.length?<span className="bubble-status number-note">{tx('checkNumber',{numbers:notes.join(', ')})}</span>:null;
}

/** A calm note under a closed bubble whose weekday was corrected from the Hebrew, or is doubtful. */
function DayNote({groups}:{groups:Group[]}) {
  const {tx}=useI18n();
  const {fixed,check}=dayNotes(groups);
  return <>
    {fixed.length?<span className="bubble-status number-note">{tx('dayFixed',{days:fixed.join(', ')})}</span>:null}
    {check.length?<span className="bubble-status number-note">{tx('checkDay',{days:check.join(', ')})}</span>:null}
  </>;
}

type SpeechProps={turn:SpeechTurn;onRetry?:(id:string)=>void;retrying:boolean;retryEnabled:boolean;originalOpen:boolean;onOriginalToggle:(id:string,open:boolean)=>void};
const sameSpeech=(a:SpeechProps,b:SpeechProps)=>a.turn.id===b.turn.id&&a.turn.position===b.turn.position&&
  a.turn.groups.length===b.turn.groups.length&&a.turn.groups.every((group,index)=>group===b.turn.groups[index])&&
  a.onRetry===b.onRetry&&a.retrying===b.retrying&&a.retryEnabled===b.retryEnabled&&
  a.originalOpen===b.originalOpen&&a.onOriginalToggle===b.onOriginalToggle;

const Speech=memo(function Speech({turn,onRetry,retrying,retryEnabled,originalOpen,onOriginalToggle}:SpeechProps) {
  const {locale,tx}=useI18n();const {calm,frozen}=useContext(DisplayContext);
  const group=turn.groups.at(-1)!;const position=turn.position;
  const holdRef=useNoShrink(frozen&&!group.complete);
  if(turn.groups.length>1||frozen&&!turn.groups.some(item=>item.live?.issue||item.final?.issue)){
    const [,target]=directionParts(group.direction);
    const segments=turn.groups.map(item=>{const pair=shownPair(item,calm)||{source:'',translation:''};return {id:item.id,pair,pending:!item.complete,hebrew:shownSource(item,pair)};});
    return <article ref={holdRef} className={`speech-card chat-bubble ${isRtlLanguage(target)?'chat-bubble--reverse':''} ${frozen?'speech-card--frozen':''}`} data-group={group.id} data-preview-id={group.stream?.preview_id}>
      <BubbleText segments={segments} direction={group.direction}/>
      {!group.complete&&<span className="bubble-status">{tx('draft')}</span>}
      <NumberNote groups={turn.groups}/><DayNote groups={turn.groups}/>
    </article>;
  }
  const live=group.live;
  const issue=live?.issue||group.final?.issue;
  const pair=shownPair(group,calm);
  if(!pair&&!issue)return null;
  const shown=pair||{source:'',translation:''};
  const empty=group.complete&&!shown.source.trim()&&!shown.translation.trim();
  if(empty&&!issue)return null;
  const previous=live?.history.find(snapshot=>snapshot.translation.trim());
  const start=shown.start??live?.start;const end=shown.end??live?.end;
  const interval=start!==undefined?` · ${start.toFixed(1)}${end!==undefined?'–'+end.toFixed(1):''} s`:'';
  const unfinished=live?.stage==='unavailable'&&issue==='Завершённая версия недоступна; ранний текст не подтверждён';
  const shortMiss=isQuietMiss(live,issue,empty,start,end);
  const unconfirmedDraft=unfinished&&!empty&&Boolean(shown.translation.trim());
  const [,target]=directionParts(group.direction);
  return <article className={`speech-card chat-bubble ${isRtlLanguage(target)?'chat-bubble--reverse':''} ${issue&&empty&&!shortMiss?'chat-bubble--issue':''}`} data-group={group.id} data-preview-id={group.stream?.preview_id}>
    {empty
      ? <p className={`fragment-failed ${shortMiss?'fragment-muted':''}`}><Icon kind="warning"/><span>{shortMiss?tx('speechMissing'):tx('fragmentFailed')}<small>{tx('fragment',{number:position})}{interval}</small></span></p>
      : <BubbleText segments={[{id:group.id,pair:shown,pending:!group.complete,hebrew:shownSource(group,pair)}]} direction={group.direction}/>
    }
    {!group.complete&&<span className="bubble-status">{tx('draft')}</span>}
    {live?.stage==='technical'&&<span className="bubble-status">{tx('continued')}</span>}
    <NumberNote groups={[group]}/><DayNote groups={[group]}/>
    {issue&&!shortMiss&&(unconfirmedDraft?<span className="bubble-status bubble-unconfirmed">{issueText(locale,issue)}</span>:<p className="unavailable bubble-issue">{issueText(locale,issue)}</p>)}
    {issue&&onRetry&&<div className="fragment-retry"><Button variant="tertiary" isDisabled={!retryEnabled||retrying} onPress={()=>onRetry(group.id)}>{retrying?tx('retrying'):tx('retry')}</Button>{!retryEnabled&&!retrying&&<small>{tx('pauseFirst')}</small>}</div>}
    {previous&&<Disclosure className="history bubble-history"><Disclosure.Heading><Disclosure.Trigger className="history-trigger">{!previous.label||previous.label==='Предыдущая версия'?tx('previous'):previous.label}<Disclosure.Indicator/></Disclosure.Trigger></Disclosure.Heading><Disclosure.Content><Disclosure.Body className="history-body"><BubbleText pair={previous} direction={group.direction}/></Disclosure.Body></Disclosure.Content></Disclosure>}
  </article>;
},sameSpeech);

/**
 * One sentence of the ticker, memoised on the group so a new sentence never re-renders the old ones.
 * An open sentence shows the words two translations in a row agreed on in black and the rest in grey;
 * a translation still streaming in for the first time is all grey. What an open sentence shows is
 * reported to the diagnostics log.
 */
const TickerSentence=memo(function TickerSentence({group,pending,agreed}:{group:Group;pending:boolean;agreed:number}) {
  const pair=shownPair(group,true);const text=pair?.translation||'';
  const words=text.split(/\s+/).filter(Boolean);
  const black=pending?words.slice(0,agreed).join(' '):text;const grey=pending?words.slice(agreed).join(' '):'';
  const source=group.live?.current.translation.trim()?'live':'stream';
  useEffect(()=>{
    if(!pending)return;
    void fetch('../action',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'ui_ticker',group:group.id,source,black,grey})}).catch(()=>{});
  },[pending,group.id,source,black,grey]);
  return <span className="ticker-sentence" data-group={group.id} title={pair?.source||undefined}>
    {black}{black&&grey?' ':''}{grey&&<span className="text-pending">{grey}</span>}{' '}
  </span>;
});

/**
 * Ticker view: the conversation as plain paragraphs. Closed sentences never change; the sentence
 * still being spoken ends the text, its unconfirmed words in grey, and turns black when it closes.
 */
const TickerView=memo(function TickerView({groups}:{groups:Group[]}) {
  const {tx}=useI18n();
  const agreements=useRef(new Map<string,Agreement>());
  const paragraphs:TickerParagraph[]=useMemo(()=>tickerParagraphs(groups),[groups]);
  if(!paragraphs.length)return null;
  const [,target]=directionParts(groups[0].direction);
  // Only published translations count as opinions; a streamed preview is never compared.
  const agreed=(group:Group)=>{
    const text=group.live?.current.translation||'';
    if(!text.trim())return 0;
    const next=agreeWords(agreements.current.get(group.id),text);
    agreements.current.set(group.id,next);return next.agreed;
  };
  return <article className="ticker" lang={htmlLanguage(target)} dir={isRtlLanguage(target)?'rtl':'ltr'}>
    {paragraphs.map(paragraph=><p key={paragraph.id} className="ticker-paragraph">
      {paragraph.sentences.map(({group,pending})=>shownPair(group,true)?.translation.trim()
        ?<TickerSentence key={group.id} group={group} pending={pending} agreed={pending?agreed(group):0}/>
        :<span key={group.id} className="ticker-sentence text-pending">{tx('translating')}</span>)}
    </p>)}
  </article>;
});

// Rows not measured yet take the average measured height, so a new bubble does not
// first reserve a tall slot and then shrink the feed under the reader.
const ESTIMATED_CARD_HEIGHT=90;
const CARD_GAP=10;
const MessageCards=memo(function MessageCards({groups,scope,scroller,onRetry,retrying,retryEnabled}:{groups:Group[];scope:string;scroller:React.RefObject<HTMLElement|null>;onRetry?:(id:string)=>void;retrying?:string|null;retryEnabled:boolean}){
  const {merge}=useContext(DisplayContext);
  const visible=useMemo(()=>speechTurns(groups,merge),[groups,merge]);
  const [heights,setHeights]=useState<Record<string,number>>({});
  const heightsRef=useRef<Record<string,number>>({});
  const [openOriginals,setOpenOriginals]=useState<Set<string>>(()=>new Set());
  const [range,setRange]=useState<[number,number]>([0,Math.min(visible.length,12)]);
  const anchorId=useRef<string|null>(null);const [pinnedId,setPinnedId]=useState<string|null>(null);
  const observers=useRef(new Map<string,ResizeObserver>());
  const estimate=useMemo(()=>{const measured=Object.values(heights);return measured.length?Math.round(measured.reduce((sum,value)=>sum+value,0)/measured.length):ESTIMATED_CARD_HEIGHT;},[heights]);
  const offsets=useMemo(()=>{const values=[0];for(const {id} of visible)values.push(values.at(-1)!+(heights[id]||estimate)+CARD_GAP);return values;},[visible,heights,estimate]);
  const total=offsets.at(-1)||0;
  const updateRange=useCallback(()=>{
    const node=scroller.current;if(!node)return;
    const top=node.scrollTop;const bottom=top+node.clientHeight;
    let start=0;while(start<visible.length&&offsets[start+1]<top)start++;
    let end=start;while(end<visible.length&&offsets[end]<bottom)end++;
    anchorId.current=visible[start]?.id||null;start=Math.max(0,start-5);end=Math.min(visible.length,end+6);
    setRange(old=>old[0]===start&&old[1]===end?old:[start,end]);
  },[offsets,scroller,visible.length]);
  useEffect(()=>{const node=scroller.current;if(!node)return;updateRange();node.addEventListener('scroll',updateRange,{passive:true});const observer=new ResizeObserver(updateRange);observer.observe(node);return()=>{node.removeEventListener('scroll',updateRange);observer.disconnect();};},[scroller,updateRange]);
  useEffect(()=>{const selection=()=>{const selected=document.getSelection()?.anchorNode;const element=selected instanceof Element?selected:selected?.parentElement;const row=element?.closest<HTMLElement>('[data-virtual-id]');setPinnedId(row?.dataset.virtualId||null);};document.addEventListener('selectionchange',selection);return()=>document.removeEventListener('selectionchange',selection);},[]);
  useEffect(()=>{if(pinnedId&&!visible.some(item=>item.id===pinnedId))setPinnedId(null);if(anchorId.current&&!visible.some(item=>item.id===anchorId.current))anchorId.current=null;},[pinnedId,visible]);
  useLayoutEffect(updateRange,[total,updateRange]);
  useEffect(()=>()=>{for(const observer of observers.current.values())observer.disconnect();observers.current.clear();},[]);
  const measure=useCallback((id:string,index:number,node:HTMLDivElement|null)=>{
    observers.current.get(id)?.disconnect();observers.current.delete(id);if(!node)return;
    const record=()=>{const height=Math.ceil(node.getBoundingClientRect().height);const old=heightsRef.current;
      if(!height||old[id]===height)return;
      const before=old[id]||estimate;const container=scroller.current;
      heightsRef.current={...old,[id]:height};
      const anchorIndex=anchorId.current===null?-1:visible.findIndex(item=>item.id===anchorId.current);
      if(container&&anchorIndex>=0&&index<anchorIndex)container.scrollTop+=height-before;
      setHeights(heightsRef.current);
    };record();const observer=new ResizeObserver(record);observer.observe(node);
    observers.current.set(id,observer);
  },[estimate,scroller,visible]);
  const toggleOriginal=useCallback((id:string,open:boolean)=>setOpenOriginals(old=>{const next=new Set(old);if(open)next.add(id);else next.delete(id);return next;}),[]);
  const rendered=useMemo(()=>virtualIndexes(visible.length,range,pinnedId===null?-1:visible.findIndex(item=>item.id===pinnedId)),[pinnedId,range,visible]);
  return <div className="virtual-message-list" style={{height:total}} data-rendered-count={rendered.length}>
    {rendered.map(index=>{const turn=visible[index];const [,target]=directionParts(turn.groups[0].direction);return <div key={scope+turn.id} ref={node=>{measure(turn.id,index,node);}} data-virtual-index={index} data-virtual-id={turn.id} className={`virtual-message-row ${isRtlLanguage(target)?'virtual-message-row--reverse':''}`} style={{transform:`translateY(${offsets[index]}px)`}}><Speech turn={turn} onRetry={onRetry} retrying={turn.groups.some(group=>group.id===retrying)} retryEnabled={retryEnabled} originalOpen={openOriginals.has(turn.id)} onOriginalToggle={toggleOriginal}/></div>;})}
  </div>;
});

const emptyEntry:VocabularyEntry={he:'',ru:'',en:''};

/** The owner's words in Settings: the engine re-reads the file, so edits apply from the next phrase. */
function VocabularyEditor() {
  const {tx}=useI18n();
  const [list,setList]=useState<VocabularyList|null>(null);
  const [error,setError]=useState('');
  const [form,setForm]=useState<VocabularyEntry>(emptyEntry);
  const [editing,setEditing]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const load=useCallback(async()=>{
    try{setList(parseVocabulary(await readJson('../vocabulary')));setError('');}catch{setError(tx('vocabularyLoadError'));}
  },[tx]);
  const failure=(code:unknown)=>{
    const keys:Record<string,TextKey>={empty_hebrew:'vocabularyEmptyHebrew',not_hebrew:'vocabularyNotHebrew',no_translation:'vocabularyNoTranslation',
      too_long:'vocabularyTooLong',too_many:'vocabularyTooMany',damaged:'vocabularyDamaged'};
    return tx(keys[String(code)]||'vocabularyError',{limit:list?.limit??500});
  };
  const send=async(body:object)=>{
    setBusy(true);setError('');
    try{
      const response=await fetch('../action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:timeoutSignal()});
      const data:unknown=await response.json().catch(()=>({}));
      if(!response.ok){setError(failure((data as {error?:unknown}).error));return false;}
      setList(parseVocabulary(data));return true;
    }catch{setError(tx('vocabularyError'));return false;}
    finally{setBusy(false);}
  };
  const submit=async(event:React.FormEvent)=>{
    event.preventDefault();
    if(!form.he.trim()){setError(tx('vocabularyEmptyHebrew'));return;}
    if(!form.ru.trim()&&!form.en.trim()){setError(tx('vocabularyNoTranslation'));return;}
    if(await send({action:'vocabulary_set',value:form,...(editing?{previous:editing}:{})})){setForm(emptyEntry);setEditing(null);}
  };
  const field=(key:keyof VocabularyEntry,label:TextKey,rtl=false)=><label className="vocabulary-field"><span>{tx(label)}</span>
    <input value={form[key]} dir={rtl?'rtl':'auto'} lang={key} maxLength={list?.lengths[key]??120} disabled={busy}
      onChange={event=>setForm(old=>({...old,[key]:event.target.value}))}/></label>;
  const blocked=busy||!list||list.damaged;
  return <details className="vocabulary" onToggle={event=>{if(event.currentTarget.open)void load();}}>
    <summary>{tx('vocabulary')}{list?` · ${list.entries.length}`:''}</summary>
    <p className="vocabulary-note">{tx('vocabularyHint')}</p>
    <p className={`vocabulary-note ${shortHebrew(form.he)?'vocabulary-note--warn':''}`}>{tx('vocabularyShort')}</p>
    {list&&!list.enabled&&<p className="vocabulary-note vocabulary-note--warn">{tx('vocabularyOff')}</p>}
    {list?.damaged&&<p className="vocabulary-error" role="alert">{tx('vocabularyDamaged')}</p>}
    <form className="vocabulary-form" onSubmit={event=>void submit(event)}>
      {field('he','vocabularyHebrew',true)}{field('ru','vocabularyRussian')}{field('en','vocabularyEnglish')}
      <div className="vocabulary-buttons">
        <button type="submit" className="vocabulary-submit" disabled={blocked}>{editing?tx('vocabularySave'):tx('vocabularyAdd')}</button>
        {editing&&<button type="button" className="vocabulary-cancel" disabled={busy} onClick={()=>{setEditing(null);setForm(emptyEntry);setError('');}}>{tx('vocabularyCancel')}</button>}
      </div>
    </form>
    {error&&<p className="vocabulary-error" role="alert">{error}</p>}
    {list?(list.entries.length?<ul className="vocabulary-list">{list.entries.map(entry=><li key={entry.he}>
      <span><strong lang="he" dir="rtl">{entry.he}</strong><small>{[entry.ru,entry.en].filter(Boolean).join(' · ')}</small></span>
      <button type="button" disabled={blocked} onClick={()=>{setEditing(entry.he);setForm(entry);setError('');}}>{tx('vocabularyEdit')}</button>
      <button type="button" disabled={blocked} onClick={()=>{if(window.confirm(tx('vocabularyDeleteConfirm',{word:entry.he})))void send({action:'vocabulary_delete',he:entry.he});}}>{tx('vocabularyDelete')}</button>
    </li>)}</ul>:<p className="vocabulary-note">{tx('vocabularyEmpty')}</p>):!error&&<p className="vocabulary-note">{tx('vocabularyLoading')}</p>}
  </details>;
}

/** Microphone or phone, chosen before recording starts; for the phone, whether a call can be taken now. */
function InputSource({state,pending,onAction}:{state:LiveState;pending:boolean;onAction:(action:string,value?:string|boolean)=>void}){
  const {tx}=useI18n();
  const phone=state.input_source==='phone';const checking=state.phone_status==='checking'||state.phone_status==null;
  const locked=pending||!!state.input_source_locked||!!state.stopping;
  const option=(value:'microphone'|'phone',label:string)=><button type="button" role="radio" aria-checked={state.input_source===value||(!state.input_source&&value==='microphone')} disabled={locked} onClick={()=>{if(state.input_source!==value)onAction('input_source',value);}}>{label}</button>;
  return <div className="input-source">
    <span className="input-source-label" id="input-source-label">{tx('inputSource')}</span>
    <div className="input-source-options" role="radiogroup" aria-labelledby="input-source-label">{option('microphone',tx('inputMicrophone'))}{option('phone',tx('inputPhone'))}</div>
    {phone&&<span className={`phone-status ${state.phone_status==='ready'?'phone-status--ready':checking?'':'phone-status--problem'}`} role="status">{tx(phoneStatusText(state.phone_status))}</span>}
    {phone&&<Button variant="tertiary" className="phone-check" isDisabled={pending||checking} onPress={()=>onAction('check_phone')}>{tx('phoneCheckAgain')}</Button>}
    {phone&&<small className="input-source-hint">{tx('phoneHint')}</small>}
  </div>;
}

function RecordingControls({state,pending,localePending,selected,onAction,dark,setDark,size,setSize,locale,onLocale,settingsRef,menuHidden,setMenuHidden,sessionsButton,onSessions,sessionsRef}:{state:LiveState;pending:boolean;localePending:boolean;selected:boolean;onAction:(action:string,value?:string|boolean)=>void;dark:boolean;setDark:(value:boolean)=>void;size:TextSize;setSize:(value:TextSize)=>void;locale:UiLocale;onLocale:(value:UiLocale)=>void;settingsRef:React.RefObject<HTMLDetailsElement|null>;menuHidden:boolean;setMenuHidden:(value:boolean)=>void;sessionsButton:boolean;onSessions:()=>void;sessionsRef:React.RefObject<HTMLButtonElement|null>}){
  const {tx}=useI18n();
  const loading=state.phase==='loading'||state.phase==='opening';
  const busy=pending||loading||state.finished||state.stopping||state.model_switching;
  const [source,target]=directionParts(state.direction);
  const direction=tx('direction',{source:languageName(locale,source,source),target:languageName(locale,target,target)});
  const archiveKey=selected?archiveRecordingLabel(state):'';
  const archiveState=archiveKey?tx(archiveKey as TextKey):'';
  const statusKey=state.stopping?(state.cancelling?'cancelling':'finishing'):state.status_code;
  const localizedStatus=statusKey&&['listening','playing_recording','finishing_translation','opening_audio','loading_models','preparing_session','app_closed','finishing','cancelling','session_finished','paused','ready_to_start','saved_session','runtime_status','partial_processing','restart_required'].includes(statusKey)?tx(statusKey as TextKey):state.status;
  const inputKind=state.input_kind==='Файл'?tx('inputFile'):state.input_kind==='Микрофон'?tx('inputMicrophone'):state.input_kind==='Телефон'?tx('inputPhone'):state.input_kind;
  const device=state.input_kind==='Телефон'?tx('phoneSession'):state.device;
  const choosing=!selected&&!state.finished&&!state.recording_started;
  const sessions=sessionsButton&&<Button ref={sessionsRef} variant="tertiary" className="show-sessions" onPress={onSessions} aria-label={tx('sessions')}><Icon kind="sidebar"/></Button>;
  const dot=<span className={`state-dot ${state.paused||state.stopping?'':'state-dot--closed'}`}/>;
  // A hidden menu leaves one thin line: what the app is doing and the way back to the menu.
  if(menuHidden)return <section className="live-controls live-controls--hidden" aria-label={tx('recordingControls')}>
    <div className="live-toolbar">
      {sessions}
      <div className="live-status" role="status">{dot}<span><strong>{localizedStatus}</strong></span></div>
      <Button variant="tertiary" className="menu-toggle" onPress={()=>setMenuHidden(false)}><Icon kind="expand"/>{tx('showMenu')}</Button>
    </div>
  </section>;
  return <section className="live-controls" aria-label={tx('recordingControls')}>
    <div className="live-toolbar">
      {sessions}
      <div className="live-status" role="status">{dot}<span><strong>{localizedStatus}</strong><small>{direction}{device?' · '+device:inputKind?' · '+inputKind:''}{archiveState?' · '+archiveState:''}</small></span></div>
      {state.finished?(state.can_start_new?<Button variant="primary" isDisabled={pending} onPress={()=>onAction('start_session')}><Icon kind="play"/>{tx('newRecording')}</Button>:null):state.stopping?<Button variant="tertiary" className="cancel-processing" isDisabled={pending||state.cancelling} onPress={()=>{if(window.confirm(tx('cancelConfirm')))onAction('cancel_processing');}}><Icon kind="stop"/>{state.cancelling?tx('cancelShort'):tx('cancelRemaining')}</Button>:<div className="session-buttons" role="group" aria-label={tx('recordingControls')}>
        <Button variant="primary" className="finish-button" isDisabled={busy||phoneBlocksStart(state)} onPress={()=>onAction('pause')}><Icon kind={state.paused?'play':'pause'}/>{state.paused?(state.desktop_mode&&state.status_code==='ready_to_start'?tx('startRecording'):tx('continue')):tx('pause')}</Button>
        <Button variant="tertiary" isDisabled={busy||(state.desktop_mode&&!state.recording_started)} onPress={()=>onAction('stop')}><Icon kind="stop"/>{tx('finishRecording')}</Button>
      </div>}
      {window.hebrewLive&&<Button variant="tertiary" onPress={()=>void window.hebrewLive?.showHelp()} aria-label={tx('helpFeedback')}><Icon kind="help"/><span className="button-label">{tx('helpFeedback')}</span></Button>}
      <Button variant="tertiary" isDisabled={pending} onPress={()=>{if(window.hebrewLive){void window.hebrewLive.requestQuit();return;}if(state.finished||window.confirm(tx('quitConfirm')))onAction('quit');}} aria-label={tx('quitApp')}><Icon kind="power"/><span className="button-label">{tx('quitApp')}</span></Button>
      <details ref={settingsRef} className="live-settings">
        <summary aria-label={tx('settings')}><Icon kind="settings"/><span className="button-label">{tx('settings')}</span></summary>
        <div className="live-settings-panel">
          <label className="settings-field"><span>{tx('interfaceLanguage')}</span><select value={locale} disabled={pending||localePending} onChange={event=>onLocale(event.target.value as UiLocale)}><option value="en">English</option><option value="ru">Русский</option>{!state.desktop_mode&&<option value="he">עברית</option>}</select></label>
          <label className="settings-field"><span>{tx('targetLanguage')}</span><select value={state.target_language||target} disabled={busy||selected} onChange={event=>onAction('target_language',event.target.value)}>{(state.target_languages||[]).map(item=><option key={item.code} value={item.code}>{languageName(locale,item.code,item.name)}</option>)}</select><small>{tx('targetBoundary')}{state.target_capabilities_assumed?' '+tx('customCapability'):''}</small></label>
          <label className="settings-check"><input type="checkbox" checked={state.save_raw_audio!==false} disabled={pending||selected||state.save_raw_audio_locked} onChange={event=>onAction('save_raw_audio',event.target.checked)}/><span>{tx('saveRawAudio')}<small>{tx(state.save_raw_audio_locked?'saveRawAudioCli':'saveRawAudioNext')}</small></span></label>
          <label className="settings-field"><span>{tx('textSize')}</span><select value={size} disabled={pending} onChange={event=>setSize(textSize(event.target.value))}>{TEXT_SIZES.map(item=><option key={item} value={item}>{tx('textSizeOption',{name:tx(`textSize_${item}` as TextKey),px:String(translationPixels(item))})}</option>)}</select></label>
          <VocabularyEditor/>
          <p className="reading-note">{state.publication==='draft'?tx('readingDraft'):tx('readingEarly')}</p>
          <div className="actions"><Button variant="tertiary" onPress={()=>setDark(!dark)}><Icon kind="theme"/>{dark?tx('lightTheme'):tx('darkTheme')}</Button><Button variant="tertiary" isDisabled={busy} onPress={()=>onAction('clear')}><Icon kind="clear"/>{tx('clearScreen')}</Button></div>
        </div>
      </details>
      <Button variant="tertiary" className="menu-toggle" onPress={()=>setMenuHidden(true)} aria-label={tx('hideMenu')}><Icon kind="up"/></Button>
    </div>
    {choosing&&<InputSource state={state} pending={pending} onAction={onAction}/>}
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
  const [size,setSize]=useState<TextSize>(()=>textSize(localStorage.getItem(TEXT_SIZE_KEY)));
  const [menuHidden,setMenuHidden]=useState(()=>storedHidden(localStorage.getItem(MENU_HIDDEN_KEY)));
  const [sessionsHidden,setSessionsHidden]=useState(()=>storedHidden(localStorage.getItem(SESSIONS_HIDDEN_KEY)));
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
  const seenPreviews=useRef(new Set<string>());
  actionContext.current={state,closed};
  const selectedArchive=selected?archives[selected]:undefined;
  const shown=selected?selectedArchive:state;
  const reasonKey=(reason:string):TextKey=>({translation_backlog:'partialReasonOverload',low_storage:'partialReasonLowStorage',storage_or_recording_write_failed:'partialReasonStorageIo',shutdown_deadline:'partialReasonShutdown',cancel_deadline:'partialReasonCancel',python_worker_shutdown_timeout:'partialReasonWorker',cancelled_pending:'partialReasonPending'} as Record<string,TextKey>)[reason]||'partialReasonRuntime';
  const described=(shown?.partial_details||[]).map(item=>tx('partialDetail',{part:String(item.part??'?'),direction:item.direction||'?',range:typeof item.start==='number'&&typeof item.end==='number'?`${item.start.toFixed(3)}–${item.end.toFixed(3)}s`:tx('rangeUnavailable'),reason:tx(reasonKey(item.reason))}));
  const partialRanges=described.join('; ')||(shown?.partial_ranges||[]).join(', ')||tx('rangeUnavailable');
  const partialNoticeType=shown?partialNoticeKind(shown):null;
  const partialNotice=partialNoticeType==='capture_unknown'?tx('partialCaptureUnknown'):
    partialNoticeType==='mixed'?tx('partialMixed',{ranges:partialRanges}):
    partialNoticeType==='known_unprocessed'?tx('partialKnown',{ranges:partialRanges}):partialNoticeType==='generic'?tx('partialSession'):'';
  const visibleGroups=shown?.groups||[];
  const shownVisibleGroups=useMemo(()=>visibleGroups.filter(isVisibleGroup),[visibleGroups]);
  const lastGroup=shownVisibleGroups.at(-1);
  const lastPair=lastGroup&&shownPair(lastGroup,!!state.calm_drafts);
  const display=useMemo(()=>({calm:!!state.calm_drafts,merge:!!state.merge_sentences,frozen:!!state.frozen_sentences,ticker:!!state.ticker_view,append:!!state.append_view}),[state.calm_drafts,state.merge_sentences,state.frozen_sentences,state.ticker_view,state.append_view]);
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
  useEffect(()=>{
    if(document.visibilityState!=='visible'||selected)return;
    const candidates=state.groups.flatMap(group=>group.stream?.preview_id?[{group:group.id,id:group.stream.preview_id}]:[]);
    let first=0,second=0;
    first=requestAnimationFrame(()=>{second=requestAnimationFrame(()=>{
      for(const candidate of candidates){
        const key=`${state.session}:${candidate.group}:${candidate.id}`;
        if(seenPreviews.current.has(key))continue;
        const card=Array.from(document.querySelectorAll<HTMLElement>('[data-preview-id]'))
          .find(item=>item.dataset.group===candidate.group&&item.dataset.previewId===candidate.id);
        if(!card||!card.getClientRects().length)continue;
        seenPreviews.current.add(key);
        void fetch('../action',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({action:'ui_preview_seen',group:candidate.group,preview_id:candidate.id})}).catch(()=>{});
      }
    });});
    return()=>{cancelAnimationFrame(first);cancelAnimationFrame(second);};
  },[state.groups,state.session,selected]);

  // Everything the reader saw and did goes to the session log (see uiLog.ts).
  const uiLog=useMemo(()=>new UiLog(),[]);
  const drawn=useRef(new Map<string,Drawn>());
  const viewName=display.ticker?'ticker':display.frozen?'frozen':'cards';
  useEffect(()=>{drawn.current.clear();},[state.session,state.generation]);
  useEffect(()=>{
    if(selected)return;
    let first=0,second=0;
    first=requestAnimationFrame(()=>{second=requestAnimationFrame(()=>{
      for(const record of renderRecords(state.groups.filter(isVisibleGroup),drawn.current,display.calm,viewName))uiLog.push(record);
    });});
    return()=>{cancelAnimationFrame(first);cancelAnimationFrame(second);};
  },[state.groups,selected,display.calm,viewName,uiLog]);
  useEffect(()=>{
    const view=()=>viewName;
    const click=(event:PointerEvent)=>uiLog.push({type:'click',...clickTarget(event.target as Element|null),view:view()});
    const key=(event:KeyboardEvent)=>{
      // Only the name of a control key; what is typed into a field is never logged.
      const typing=event.key.length===1&&(event.target as HTMLElement|null)?.closest('input,textarea');
      uiLog.push({type:'key',key:typing?'char':event.key.slice(0,24),...clickTarget(event.target as Element|null)});
    };
    const visibility=()=>{uiLog.push({type:'visibility',visible:document.visibilityState==='visible'});if(document.visibilityState!=='visible')uiLog.flush(true);};
    let resizeTimer:ReturnType<typeof setTimeout>|undefined;
    const resize=()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>uiLog.push({type:'resize',width:window.innerWidth,height:window.innerHeight}),300);};
    const toggle=(event:Event)=>{const node=event.target as HTMLElement;if(node instanceof HTMLDetailsElement)uiLog.push({type:'settings',target:node.className.split(/\s+/)[0]||'details',state:node.open?'open':'closed'});};
    const leave=()=>uiLog.flush(true);
    document.addEventListener('pointerdown',click,true);document.addEventListener('keydown',key,true);
    document.addEventListener('visibilitychange',visibility);window.addEventListener('resize',resize);
    document.addEventListener('toggle',toggle,true);window.addEventListener('pagehide',leave);
    uiLog.push({type:'resize',width:window.innerWidth,height:window.innerHeight});
    return()=>{document.removeEventListener('pointerdown',click,true);document.removeEventListener('keydown',key,true);
      document.removeEventListener('visibilitychange',visibility);window.removeEventListener('resize',resize);
      document.removeEventListener('toggle',toggle,true);window.removeEventListener('pagehide',leave);clearTimeout(resizeTimer);uiLog.flush(true);};
  },[uiLog,viewName]);

  useEffect(()=>{uiLog.push({type:'follow',following:follow.following});},[follow.following,uiLog]);
  useEffect(()=>{
    const node=follow.containerRef.current;if(!node)return;
    let timer:ReturnType<typeof setTimeout>|undefined;
    const scrolled=()=>{if(timer!==undefined)return;timer=setTimeout(()=>{timer=undefined;
      uiLog.push({type:'scroll',top:Math.round(node.scrollTop),height:node.scrollHeight,client_height:node.clientHeight});},300);};
    node.addEventListener('scroll',scrolled,{passive:true});
    return()=>{node.removeEventListener('scroll',scrolled);clearTimeout(timer);};
  },[follow.containerRef,uiLog]);

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
  useEffect(()=>{document.documentElement.dataset.textSize=size;localStorage.setItem(TEXT_SIZE_KEY,size);},[size]);
  // The saved preference wins: the window's address (and so its localStorage) changes every launch.
  useEffect(()=>{if(state.text_size!==undefined)setSize(textSize(state.text_size));},[state.text_size]);
  useEffect(()=>{localStorage.setItem(MENU_HIDDEN_KEY,storedValue(menuHidden));},[menuHidden]);
  useEffect(()=>{localStorage.setItem(SESSIONS_HIDDEN_KEY,storedValue(sessionsHidden));},[sessionsHidden]);
  useEffect(()=>{if(state.menu_hidden!==undefined)setMenuHidden(state.menu_hidden);},[state.menu_hidden]);
  useEffect(()=>{if(state.sessions_hidden!==undefined)setSessionsHidden(state.sessions_hidden);},[state.sessions_hidden]);
  useEffect(()=>{
    if(!connectionError)return;
    setClock(Date.now());const timer=window.setInterval(()=>setClock(Date.now()),1000);
    return()=>window.clearInterval(timer);
  },[connectionError]);
  useEffect(()=>{
    if(closed)return;
    let cancelled=false,timer:number|undefined,stop=()=>{};
    function accept(parsed:LiveState){
      let next=parsed;
      if(localeConfirmed.current){
        if(next.ui_locale===localeConfirmed.current)localeConfirmed.current=null;
        else next={...next,ui_locale:localeConfirmed.current};
      }
      setState(old=>mergeLiveState(old,next));setLastSuccess(Date.now());setConnectionError('');
      return next;
    }
    function fail(error:unknown){
      const message=error instanceof Error?error.message:'';const name=error instanceof Error?error.name:'';
      const reason=name==='TimeoutError'?tx('timeout'):message.startsWith('Invalid local API')||name==='SyntaxError'?tx('badSnapshot'):message.startsWith('HTTP ')?tx('httpError',{code:message.slice(5)}):tx('noResponse');
      setConnectionError(reason+' '+tx('lastSnapshot'));
    }
    async function poll(){
      try{
        const next=parseLiveState(await readJson('../state'));
        if(cancelled)return;
        accept(next);
        if(next.phase!=='exited')timer=window.setTimeout(poll,next.finished?700:200);
      }catch(error){if(!cancelled){fail(error);timer=window.setTimeout(poll,1500);}}
    }
    // Push first: the server sends every change at once. Polling stays as the fallback when the stream is
    // unavailable (HEBREW_LIVE_UI_PUSH=0, no EventSource) or breaks.
    stop=openStateStream('../events',text=>{
      try{if(accept(parseLiveState(JSON.parse(text))).phase==='exited')stop();}catch(error){if(!cancelled)fail(error);}
    },()=>{void poll();});
    return()=>{cancelled=true;window.clearTimeout(timer);stop();};
  },[closed,tx]);

  const act=useCallback(async(action:string,value?:string|boolean)=>{
    const {state,closed}=actionContext.current;
    const loading=state.phase==='loading'||state.phase==='opening';
    const preferenceAction=['ui_locale','text_size','menu_hidden','sessions_hidden','save_raw_audio','input_source','check_phone'].includes(action);
    if(closed||actionBusy.current||(!preferenceAction&&((loading&&!['stop','quit','open_archive_folder'].includes(action))||(state.finished&&!['open_folder','open_archive_folder','exports_ready','start_session','quit'].includes(action))||(!['stop','quit','cancel_processing','open_folder','open_archive_folder','exports_ready','start_session'].includes(action)&&(state.stopping||state.model_switching)))))return false;
    actionBusy.current=true;
    setPending(true);setActionError('');
    try{
      const response=await fetch('../action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,value}),signal:timeoutSignal()});
      if(!response.ok)throw new Error();
      if(action==='stop')setState(old=>({...old,stopping:true,phase:'stopping',status_code:'finishing'}));
      if(action==='cancel_processing')setState(old=>({...old,cancelling:true,status_code:'cancelling'}));
      if(action==='start_session')setState(old=>({...old,can_start_new:false}));
      if(action==='save_raw_audio'&&typeof value==='boolean')setState(old=>({...old,save_raw_audio:value}));
      if(action==='input_source'&&(value==='microphone'||value==='phone'))setState(old=>({...old,input_source:value,input_error:null,...(value==='phone'?{phone_status:'checking'}:{})}));
      if(action==='check_phone')setState(old=>({...old,phone_status:'checking'}));
      if(action==='exports_ready'){setClosed(true);setState(old=>({...old,phase:'exited',can_start_new:false,status_code:'app_closed'}));}
      if(action==='quit'){
        if(state.finished){setClosed(true);setState(old=>({...old,phase:'exited',can_start_new:false,status_code:'app_closed'}));}
        else setState(old=>({...old,stopping:true,phase:'stopping',status_code:'finishing'}));
      }
      return true;
    }catch{setActionError(action==='open_archive_folder'?tx('openFolderError'):tx('actionError'));return false;}
    finally{actionBusy.current=false;setPending(false);}
  },[tx]);
  const onAction=useCallback((action:string,value?:string|boolean)=>{void act(action,value);},[act]);
  const chooseSize=useCallback((value:TextSize)=>{setSize(value);void act('text_size',value).then(saved=>{if(saved)setState(old=>({...old,text_size:value}));});},[act]);
  const chooseMenuHidden=useCallback((value:boolean)=>{setMenuHidden(value);void act('menu_hidden',value).then(saved=>{if(saved)setState(old=>({...old,menu_hidden:value}));});},[act]);
  const chooseSessionsHidden=useCallback((value:boolean)=>{
    setSessionsHidden(value);
    if(value)requestAnimationFrame(()=>openSidebarRef.current?.focus());
    void act('sessions_hidden',value).then(saved=>{if(saved)setState(old=>({...old,sessions_hidden:value}));});
  },[act]);
  const retryFragment=useCallback((id:string)=>{void act('retry_fragment',id);},[act]);
  const changeLocale=useCallback(async(value:UiLocale)=>{
    const request=beginLocaleRequest(locale,state.ui_locale,value,localeRequested.current);
    if(!request)return;
    localeRequested.current=request;setLocalePending(true);setLocale(value);
    if(await act('ui_locale',value)){
      if(window.hebrewLive&&(value==='en'||value==='ru'))await window.hebrewLive.setUiLocale(value);
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
  return <I18nContext.Provider value={i18n}><div className={`app-shell live-shell messenger-shell ${sidebar?'sessions-open':''} ${sessionsHidden&&!narrow?'sessions-hidden':''}`}>
    <aside ref={sidebarRef} className="session-sidebar" aria-label={tx('sessions')} role={narrow?'dialog':undefined} aria-modal={narrow||undefined} aria-hidden={(narrow?!sidebar:sessionsHidden)||undefined}>
      <header><h1>{tx('sessions')}</h1><Button variant="tertiary" className="close-sessions" onPress={narrow?closeSidebar:()=>chooseSessionsHidden(true)} aria-label={tx(narrow?'closeSessions':'hideSessions')}>×</Button></header>
      <label className="session-search"><Icon kind="folder"/><input value={search} onChange={event=>setSearch(event.target.value)} placeholder={tx('searchPlaceholder')} aria-label={tx('searchSaved')}/></label>
      <nav aria-label={tx('savedConversations')}>
        <button className={`session-row ${!selected?'selected':''}`} onClick={()=>choose('')} aria-current={!selected?'page':undefined}><span className="session-avatar"><Icon kind="play"/></span><span><strong>{tx('currentSession')}</strong><small>{state.status_code&&['listening','playing_recording','finishing_translation','opening_audio','loading_models','preparing_session','app_closed','finishing','cancelling','session_finished','paused','ready_to_start','saved_session'].includes(state.status_code)?tx(state.status_code as TextKey):state.status}</small></span></button>
        <p className="session-list-label">{tx('saved')}</p>
        {filtered.map(item=><div className="session-entry" key={item.id}><button className={`session-row ${selected===item.id?'selected':''}`} onClick={()=>choose(item.id)} aria-current={selected===item.id?'page':undefined}><span className="session-avatar"><Icon kind="folder"/></span><span><strong>{item.title?.startsWith('Разговор ')?item.label:item.title||item.label}</strong><small>{item.preview||item.label}</small><small className="session-date">{item.label}</small></span></button><button className="session-delete" disabled={!!deleting} onClick={()=>void deleteSession(item)} aria-label={tx('deleteSession',{label:item.label})} title={tx('deleteTitle')}><Icon kind="trash"/></button></div>)}
        {sessionsLoaded&&!sessions.length&&<p className="session-list-label">{tx('noneSaved')}</p>}
        {sessionsLoaded&&sessions.length>0&&!filtered.length&&<p className="session-list-label">{tx('nothingFound')}</p>}
        {sessionsError&&<div className="session-list-error" role="alert"><p>{sessionsError}</p><Button variant="tertiary" onPress={()=>setSessionsReload(value=>value+1)}>{tx('retryButton')}</Button></div>}
      </nav>
      {deleteError&&<p className="unavailable" role="alert">{deleteError}</p>}
    </aside>
    <main className="conversation-pane">
      {selected&&<div className="conversation-title"><div><strong>{sessions.find(item=>item.id===selected)?.label||tx('savedConversation')}</strong><small>{tx('readOnly')}</small></div><Button variant="tertiary" onPress={()=>choose('')}><Icon kind="play"/>{tx('backToLive')}</Button></div>}
      <RecordingControls state={state} pending={pending} localePending={localePending} selected={!!selected} onAction={onAction} dark={dark} setDark={setDark} size={size} setSize={chooseSize} locale={locale} onLocale={value=>{void changeLocale(value);}} settingsRef={settingsRef}
        menuHidden={menuHidden} setMenuHidden={chooseMenuHidden} sessionsButton={narrow||sessionsHidden} onSessions={narrow?()=>setSidebar(true):()=>chooseSessionsHidden(false)} sessionsRef={openSidebarRef}/>
      {connectionError&&<p className="unavailable global-error" role="alert">{connectionError}{lastSuccess?' '+tx('secondsAgo',{seconds:Math.max(1,Math.floor((clock-lastSuccess)/1000))}):''}</p>}
      {actionError&&<p className="unavailable global-error" role="alert">{actionError}</p>}
      {!selected&&state.input_error&&(state.input_error==='phone_stopped'||state.phone_status!=='ready')&&<p className="unavailable global-error" role="alert">{tx(state.input_error==='phone_stopped'?'phoneStopped':'phoneNotReadyAtStart',{reason:tx(phoneStatusText(state.phone_status))})}</p>}
      {!selected&&state.retry_error&&<p className="unavailable global-error" role="alert">{issueText(locale,state.retry_error)}</p>}
      {!selected&&state.target_error&&<p className="unavailable global-error" role="alert">{tx(state.target_error_code==='target_preference_not_saved'?'targetPreferenceError':state.target_error_code==='target_busy'?'targetBusyError':'targetChangeError')}</p>}
      {!selected&&partialNotice&&<p className="unavailable global-error" role="status">{partialNotice}</p>}
      {selected&&archiveError&&<div className="archive-error" role="alert"><p className="unavailable">{archiveError}</p><Button variant="tertiary" onPress={()=>{setArchiveRetries(old=>({...old,[selected]:(old[selected]||0)+1}));setArchiveError('');}}>{tx('retryButton')}</Button></div>}
      {selected&&partialNotice&&<p role="status" className="unavailable global-error">{partialNotice}</p>}
      {selected&&selectedArchive?.warning&&!selectedArchive.partial&&<p role="status" className="reading-note">{selectedArchive.warning==='В журнале есть неполная запись.'?tx('archiveIncomplete'):selectedArchive.warning}</p>}
      <section ref={follow.containerRef} className="live-feed chat-feed" onClickCapture={event=>{if((event.target as HTMLElement).closest('.history'))follow.stop();}} aria-label={tx('feedLabel')}>
        <DisplayContext.Provider value={display}>{display.ticker&&!selected?<TickerView groups={visibleGroups}/>:<MessageCards key={`${selected||state.session||'current'}:${shown?.generation??0}`} groups={visibleGroups} scope={selected||'current'} scroller={follow.containerRef} onRetry={selected||state.finished||!state.retry_supported?undefined:retryFragment} retrying={state.retrying_group} retryEnabled={!selected&&state.paused&&!state.finished&&!state.stopping&&!state.model_switching}/>}</DisplayContext.Provider>
        {!shownVisibleGroups.length&&<Card className="speech-card"><Card.Content className="live-empty">{selected?(selectedArchive?tx('noMessages'):archiveError?tx('conversationUnavailable'):archiveLoading===selected?tx('loadingConversation'):tx('chooseAgain')):loading?tx('loadingBeforeRecord'):state.finished?(closed?tx('closed'):state.can_start_new?tx('readyNew'):tx('recordingFinished')):state.paused?(state.desktop_mode&&!state.recording_started?tx(state.input_source==='phone'?'readyToStartPhoneHint':'readyToStartHint'):tx('readyToSpeak')):state.phase==='listening'?tx('waitingSpeech'):state.status}</Card.Content></Card>}
        {((selected&&selectedArchive)||(!selected&&state.finished))&&<section className="live-exports"><h2>{tx('sessionSaved')}</h2><p>{tx((selected?selectedArchive?.audio_saved:state.audio_saved)===false?'filesInFolderNoAudio':'filesInFolder')}</p><code>{selected?selectedArchive?.session_path:state.session}</code><Button isDisabled={closed||pending} onPress={()=>void act(selected?'open_archive_folder':'open_folder',selected||undefined)}><Icon kind="folder"/>{tx('openFinder')}</Button></section>}
      </section>
      {!selected&&!follow.following&&state.groups.length>0&&<Button className="follow-latest" variant="primary" onPress={follow.resume}><Icon kind="down"/>{tx('backToCurrent')}</Button>}
    </main><footer className="app-footer"><span>{tx('onThisMac')}</span><span>{tx('lateNotBetter')}</span></footer>
  </div></I18nContext.Provider>;
}
