// The window's own log: every version of a bubble as it was drawn, and the reader's actions.
// Batches go to the engine (`ui_log`), which writes them into the session's diagnostics.
import {shownPair,shownSource} from './liveState.ts';
import type {Group} from './liveState.ts';

export type RenderRecord={type:'render';group:string;revision?:number;shown:'live'|'stream'|'none';complete:boolean;
  source:string;translation:string;source_changed:boolean;translation_changed:boolean;
  erased_source:number;erased_translation:number;emitted_at?:number;audio_lag?:number;view:string};
export type InputRecord={type:'click'|'scroll'|'key'|'visibility'|'resize'|'follow'|'settings';
  target?:string;label?:string;key?:string;state?:string;top?:number;height?:number;client_height?:number;
  width?:number;following?:boolean;visible?:boolean;view?:string};
export type LogRecord=RenderRecord|InputRecord;
export type Drawn={source:string;translation:string;complete:boolean};

const words=(text:string)=>text.split(/\s+/).filter(Boolean).map(word=>word.replace(/[.,!?…:;"'»«()–-]+$/,''));

/** Words of `before` that `after` no longer has at the same place: what the reader saw erased.
 * A last word that only grew (a streamed word completed) is not an erasure. */
export function erasedWords(before:string,after:string):number {
  const a=words(before),b=words(after);
  let kept=0;while(kept<a.length&&kept<b.length&&a[kept]===b[kept])kept++;
  if(kept===a.length-1&&b[kept]?.startsWith(a[kept]))kept++;
  return a.length-kept;
}

/** Records for the groups whose drawn text or state changed since `last`; updates `last`. */
export function renderRecords(groups:Group[],last:Map<string,Drawn>,calm:boolean,view:string):RenderRecord[] {
  const records:RenderRecord[]=[];
  for(const group of groups){
    const pair=shownPair(group,calm);
    const shown=!pair?'none':group.stream&&pair===group.stream?'stream':'live';
    const source=pair?shownSource(group,pair):'',translation=pair?.translation||'';
    const before=last.get(group.id);
    if(before&&before.source===source&&before.translation===translation&&before.complete===group.complete)continue;
    last.set(group.id,{source,translation,complete:group.complete});
    const sourceChanged=before?before.source!==source:Boolean(source),translationChanged=before?before.translation!==translation:Boolean(translation);
    // Newer Hebrew drawn ahead of its translation carries its own publication time.
    const ahead=Boolean(group.source_live&&source===group.source_live.source&&sourceChanged&&!translationChanged);
    const timing=ahead?{emitted_at:group.source_live?.emitted_at,audio_lag:group.source_live?.audio_lag}:
      shown==='stream'?{emitted_at:group.stream?.preview_emitted_at,audio_lag:group.stream?.audio_lag}:
      shown==='live'?{emitted_at:group.live?.emitted_at,audio_lag:group.live?.audio_lag}:{};
    records.push({type:'render',group:group.id,revision:group.revision,shown,complete:group.complete,source,translation,
      source_changed:sourceChanged,translation_changed:translationChanged,
      erased_source:before?erasedWords(before.source,source):0,erased_translation:before?erasedWords(before.translation,translation):0,
      ...timing,view});
  }
  return records;
}

type Queued=LogRecord&{at:number};
export type Sender=(body:string,keepalive:boolean)=>void;
const defaultSender:Sender=(body,keepalive)=>{void fetch('../action',{method:'POST',headers:{'Content-Type':'application/json'},body,keepalive}).catch(()=>{});};

/** Sends records in batches every `interval` ms; `age_ms` says how long each waited, so the engine
 * can place it at the moment it was drawn. */
export class UiLog {
  private queue:Queued[]=[];private timer:ReturnType<typeof setTimeout>|undefined;
  private send:Sender;private now:()=>number;private interval:number;
  constructor(send:Sender=defaultSender,now:()=>number=()=>performance.now(),interval=250){this.send=send;this.now=now;this.interval=interval;}
  push(record:LogRecord){
    this.queue.push({...record,at:this.now()});
    if(this.queue.length>=200)this.flush();
    else if(this.timer===undefined)this.timer=setTimeout(()=>this.flush(),this.interval);
  }
  flush(keepalive=false){
    if(this.timer!==undefined){clearTimeout(this.timer);this.timer=undefined;}
    while(this.queue.length){
      const now=this.now();
      const items=this.queue.splice(0,keepalive?40:200).map(({at,...record})=>({...record,age_ms:Math.max(0,now-at)}));
      this.send(JSON.stringify({action:'ui_log',items}),keepalive);
    }
  }
}

/** A short name for what was clicked: a control's own label, never the text of a bubble. */
export function clickTarget(element:Element|null):{target:string;label?:string} {
  const control=element?.closest('button,summary,a,input,select,label,[role=radio],[role=button]');
  if(control){
    const label=(control.getAttribute('aria-label')||(control instanceof HTMLInputElement?control.type:control.textContent)||'').trim().slice(0,60);
    return {target:control.tagName.toLowerCase()+(control.className&&typeof control.className==='string'?'.'+control.className.split(/\s+/)[0]:''),label};
  }
  const bubble=element?.closest('[data-group]');
  if(bubble)return {target:'bubble',label:(bubble as HTMLElement).dataset.group};
  return {target:element?element.tagName.toLowerCase():'none'};
}
