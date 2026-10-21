export type Pair = {source:string;translation:string;label?:string|null;start?:number;end?:number;issue?:string|null;preview_id?:string;preview_emitted_at?:number};
export type LiveValue = {current:Pair;history:Pair[];stage:string;issue?:string|null;reason?:string|null;start?:number;end?:number};
export type Group = {id:string;revision?:number;direction:string;complete:boolean;live?:LiveValue;stream?:Pair;final?:Pair;final_progress?:Pair};
export type PartialDetail = {part:number|null;direction:string|null;reason:string;start:number|null;end:number|null};
export type LiveState = {
  session_path?:string;phase:string;can_start_new?:boolean;groups:Group[];status:string;
  status_code?:string;ui_locale?:'en'|'ru'|'he';target_language?:string;
  desktop_mode?:boolean;calm_drafts?:boolean;merge_sentences?:boolean;frozen_sentences?:boolean;ticker_view?:boolean;recording_started?:boolean;capture_active?:boolean;
  target_languages?:{code:string;name:string;rtl:boolean}[];target_error?:string|null;target_error_code?:string|null;
  target_capabilities_assumed?:boolean;
  publication?:string;paused:boolean;finished:boolean;stopping?:boolean;cancelling?:boolean;
  model_switching?:boolean;direction:string;input_kind?:string;device?:string;session?:string;
  model_selection?:{asr:string;translation:string}|null;
  generation?:number;exports?:{id:string;name:string;label:string}[];warning?:string;
  retrying_group?:string|null;retry_error?:string|null;
  retry_supported?:boolean;
  save_raw_audio?:boolean;save_raw_audio_locked?:boolean;audio_saved?:boolean;partial?:boolean;integrity_warning?:string|null;
  partial_kind?:'known_unprocessed'|'capture_unknown'|'mixed'|null;partial_ranges?:string[];partial_details?:PartialDetail[];capture_discontinuity?:boolean;
};

const phases = new Set(['loading','opening','listening','paused','stopping','finished','error','exited']);
const record = (value:unknown): value is Record<string,unknown> => typeof value==='object'&&value!==null&&!Array.isArray(value);
const optionalString = (value:unknown) => value===undefined||value===null||typeof value==='string';
const optionalBoolean = (value:unknown) => value===undefined||typeof value==='boolean';
const optionalNumber = (value:unknown) => value===undefined||typeof value==='number'&&Number.isFinite(value);

function pair(value:unknown): value is Pair {
  return record(value)&&typeof value.source==='string'&&typeof value.translation==='string'&&optionalString(value.label)&&optionalString(value.issue)&&optionalNumber(value.start)&&optionalNumber(value.end)&&optionalString(value.preview_id)&&optionalNumber(value.preview_emitted_at);
}

function group(value:unknown): value is Group {
  if(!record(value)||typeof value.id!=='string'||typeof value.direction!=='string'||typeof value.complete!=='boolean')return false;
  if(value.revision!==undefined&&typeof value.revision!=='number')return false;
  if(value.final!==undefined&&!pair(value.final)||value.final_progress!==undefined&&!pair(value.final_progress)||value.stream!==undefined&&!pair(value.stream))return false;
  if(value.live!==undefined){
    if(!record(value.live)||!pair(value.live.current)||!Array.isArray(value.live.history)||!value.live.history.every(pair)||typeof value.live.stage!=='string'||!optionalString(value.live.issue)||!optionalString(value.live.reason)||!optionalNumber(value.live.start)||!optionalNumber(value.live.end))return false;
  }
  return true;
}

export function parseLiveState(value:unknown):LiveState {
  if(!record(value)||!Array.isArray(value.groups)||!value.groups.every(group)||typeof value.status!=='string'||typeof value.paused!=='boolean'||typeof value.finished!=='boolean'||typeof value.direction!=='string')throw new Error('Invalid local API snapshot');
  if(!optionalString(value.session_path)||!optionalString(value.publication)||!optionalString(value.input_kind)||!optionalString(value.device)||!optionalString(value.session)||!optionalString(value.warning)||!optionalString(value.integrity_warning)||!optionalString(value.retrying_group)||!optionalString(value.retry_error)||!optionalString(value.status_code)||!optionalString(value.target_language)||!optionalString(value.target_error)||!optionalString(value.target_error_code))throw new Error('Invalid local API snapshot');
  if(value.ui_locale!==undefined&&!['en','ru','he'].includes(String(value.ui_locale)))throw new Error('Invalid local API snapshot');
  if(value.model_selection!==undefined&&value.model_selection!==null&&(!record(value.model_selection)||typeof value.model_selection.asr!=='string'||typeof value.model_selection.translation!=='string'))throw new Error('Invalid local API snapshot');
  if(value.target_languages!==undefined&&(!Array.isArray(value.target_languages)||!value.target_languages.every(item=>record(item)&&typeof item.code==='string'&&typeof item.name==='string'&&typeof item.rtl==='boolean')))throw new Error('Invalid local API snapshot');
  if(value.partial_kind!==undefined&&value.partial_kind!==null&&!['known_unprocessed','capture_unknown','mixed'].includes(String(value.partial_kind)))throw new Error('Invalid local API snapshot');
  if(value.partial_ranges!==undefined&&(!Array.isArray(value.partial_ranges)||!value.partial_ranges.every(item=>typeof item==='string')))throw new Error('Invalid local API snapshot');
  if(value.partial_details!==undefined&&(!Array.isArray(value.partial_details)||!value.partial_details.every(item=>record(item)&&(item.part===null||typeof item.part==='number')&&(item.direction===null||typeof item.direction==='string')&&typeof item.reason==='string'&&(item.start===null||typeof item.start==='number')&&(item.end===null||typeof item.end==='number'))))throw new Error('Invalid local API snapshot');
  if(!optionalBoolean(value.can_start_new)||!optionalBoolean(value.stopping)||!optionalBoolean(value.cancelling)||!optionalBoolean(value.model_switching)||!optionalBoolean(value.retry_supported)||!optionalBoolean(value.save_raw_audio)||!optionalBoolean(value.save_raw_audio_locked)||!optionalBoolean(value.audio_saved)||!optionalBoolean(value.partial)||!optionalBoolean(value.capture_discontinuity)||!optionalBoolean(value.target_capabilities_assumed)||!optionalBoolean(value.desktop_mode)||!optionalBoolean(value.calm_drafts)||!optionalBoolean(value.merge_sentences)||!optionalBoolean(value.frozen_sentences)||!optionalBoolean(value.ticker_view)||!optionalBoolean(value.recording_started)||!optionalBoolean(value.capture_active)||!optionalNumber(value.generation))throw new Error('Invalid local API snapshot');
  if(value.exports!==undefined&&(!Array.isArray(value.exports)||!value.exports.every(item=>record(item)&&typeof item.id==='string'&&typeof item.name==='string'&&typeof item.label==='string')))throw new Error('Invalid local API snapshot');
  if(value.phase!==undefined&&(typeof value.phase!=='string'||!phases.has(value.phase)))throw new Error('Invalid local API phase');
  const phase=(value.phase as string|undefined)??(value.finished?'finished':value.paused?'paused':'listening');
  return {...value,phase} as LiveState;
}

export function keepStableGroups(previous:Group[],next:Group[]):Group[] {
  if(!previous.length)return next;
  const old=new Map(previous.map(item=>[item.id,item]));
  let changed=previous.length!==next.length;
  const result=next.map((item,index)=>{
    const before=old.get(item.id);
    const same=before&&(item.revision!==undefined&&before.revision===item.revision||item.revision===undefined&&JSON.stringify(before)===JSON.stringify(item));
    if(same){if(previous[index]!==before)changed=true;return before;}
    changed=true;return item;
  });
  return changed?result:previous;
}

export function virtualIndexes(length:number,range:readonly [number,number],pinnedIndex=-1):number[] {
  if(length<=0)return [];
  const start=Math.min(Math.max(0,range[0]),length-1);
  const end=Math.max(start+1,Math.min(range[1],length));
  const indexes=Array.from({length:end-start},(_,index)=>start+index);
  if(pinnedIndex>=0&&pinnedIndex<length&&!indexes.includes(pinnedIndex))indexes.push(pinnedIndex);
  return indexes;
}

export function mergeLiveState(previous:LiveState,next:LiveState):LiveState {
  const sameStream=previous.session===next.session&&previous.generation===next.generation;
  return {...next,groups:sameStream?keepStableGroups(previous.groups,next.groups):next.groups};
}

/**
 * The pair a bubble shows. A refresh streams its translation from the first word,
 * so showing that stream over an existing translation shrinks the bubble to a few
 * words every second; the stream is shown only while the group has no translation.
 */
export function shownPair(group:Group,calm=false):Pair|undefined {
  const durable=group.live?.current||group.final||group.final_progress;
  if(!calm)return group.stream||durable;
  return group.stream&&!durable?.translation.trim()?group.stream:durable||group.stream;
}

/** Length of the leading text whose words are unchanged from `before`, ending at a word boundary. */
export function unchangedPrefix(before:string,after:string):number {
  const old=before.split(/\s+/).filter(Boolean);
  let end=0,index=0;
  for(const match of after.matchAll(/\S+\s*/g)){
    if(match[0].trimEnd()!==old[index++])break;
    end=match.index+match[0].length;
  }
  return end;
}

const wordCount=(text:string)=>text.split(/\s+/).filter(Boolean).length;

/**
 * Text for a still open sentence when frozen sentences are on: a refresh with fewer words
 * than the text on screen keeps the longer one until a refresh catches up, so the reader
 * never sees the open line get shorter. A closed sentence always shows its own text.
 */
export function heldText(shown:string,next:string,hold:boolean):string {
  return hold&&wordCount(next)<wordCount(shown)?shown:next;
}

export type SpeechTurn = {id:string;groups:Group[];position:number};
/** Bound on one merged bubble, so a long monologue stays a list of virtual rows. */
export const TURN_MAX_GROUPS = 8;

const groupIssue=(group:Group)=>group.live?.issue||group.final?.issue;

/**
 * Bubbles to show. The engine closes a group at a sentence end or a technical cut while
 * the speaker goes on; those groups continue the same bubble, and only a pause (or a
 * problem) starts a new one, so a closed sentence never moves the next one away.
 */
export function speechTurns(groups:Group[],merge=false):SpeechTurn[] {
  const turns:SpeechTurn[]=[];
  groups.forEach((group,index)=>{
    if(!isVisibleGroup(group))return;
    const last=turns.at(-1);const tail=last?.groups.at(-1);
    const continued=Boolean(merge&&last&&tail&&tail.complete&&tail.direction===group.direction&&
      (tail.live?.reason==='sentence'||tail.live?.stage==='technical')&&
      !groupIssue(tail)&&!groupIssue(group)&&last.groups.length<TURN_MAX_GROUPS);
    if(continued)last!.groups.push(group);
    else turns.push({id:group.id,groups:[group],position:index+1});
  });
  return turns;
}

export type TickerSentence = {group:Group;pending:boolean};
export type TickerParagraph = {id:string;sentences:TickerSentence[]};

/**
 * Paragraphs of the ticker view. Closed sentences keep their place and text; the open one
 * ends the last paragraph in grey and only changes colour when it closes, so nothing above
 * it ever moves. A pause (a group closed by silence, not at a sentence end or a technical
 * cut) or a problem starts a new paragraph.
 */
export function tickerParagraphs(groups:Group[]):TickerParagraph[] {
  const paragraphs:TickerParagraph[]=[];
  let continues=false;
  for(const group of groups){
    if(!isVisibleGroup(group))continue;
    const pair=shownPair(group,true);
    const issue=Boolean(groupIssue(group));
    if(group.complete&&!pair?.translation.trim())continue;
    const last=paragraphs.at(-1);
    if(last&&continues&&!issue)last.sentences.push({group,pending:!group.complete});
    else paragraphs.push({id:group.id,sentences:[{group,pending:!group.complete}]});
    continues=group.complete&&!issue&&(group.live?.reason==='sentence'||group.live?.stage==='technical');
  }
  return paragraphs;
}

export function isVisibleGroup(group:Group):boolean {
  const pair=shownPair(group);
  const issue=group.live?.issue||group.final?.issue;
  return Boolean(issue||!group.complete||pair&&(pair.source.trim()||pair.translation.trim()));
}

const FINAL_UNAVAILABLE='Завершённая версия недоступна; ранний текст не подтверждён';
const NO_SPEECH='Речь не распознана';

/** A short empty bubble the backend gave up on: shown as a muted line, not as a failure card. */
export function isQuietMiss(live:LiveValue|undefined,issue:string|null|undefined,empty:boolean,start?:number,end?:number):boolean {
  const closedEmpty=live?.stage==='unavailable'&&(issue===FINAL_UNAVAILABLE||issue===NO_SPEECH);
  return closedEmpty&&empty&&start!==undefined&&end!==undefined&&end-start<=2;
}

export function archiveRecordingLabel(state:LiveState):string {
  if(state.finished)return '';
  if(state.stopping)return 'recordingEnding';
  if(state.phase==='paused'||state.paused)return 'recordingPaused';
  if(state.phase==='loading'||state.phase==='opening')return 'recordingPreparing';
  if(state.phase==='listening')return 'recordingContinues';
  return 'recordingUpdating';
}

export function partialNoticeKind(state:LiveState):'known_unprocessed'|'capture_unknown'|'mixed'|'generic'|null {
  if(state.partial_kind)return state.partial_kind;
  return state.partial?'generic':null;
}
