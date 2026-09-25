export type Pair = {source:string;translation:string;label?:string|null;start?:number;end?:number;issue?:string|null};
export type LiveValue = {current:Pair;history:Pair[];stage:string;issue?:string|null;reason?:string|null;start?:number;end?:number};
export type Group = {id:string;revision?:number;direction:string;complete:boolean;live?:LiveValue;final?:Pair;final_progress?:Pair};
export type PartialDetail = {part:number|null;direction:string|null;reason:string;start:number|null;end:number|null};
export type LiveState = {
  session_path?:string;phase:string;can_start_new?:boolean;groups:Group[];status:string;
  status_code?:string;ui_locale?:'en'|'ru'|'he';target_language?:string;
  desktop_mode?:boolean;recording_started?:boolean;capture_active?:boolean;
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
  return record(value)&&typeof value.source==='string'&&typeof value.translation==='string'&&optionalString(value.label)&&optionalString(value.issue)&&optionalNumber(value.start)&&optionalNumber(value.end);
}

function group(value:unknown): value is Group {
  if(!record(value)||typeof value.id!=='string'||typeof value.direction!=='string'||typeof value.complete!=='boolean')return false;
  if(value.revision!==undefined&&typeof value.revision!=='number')return false;
  if(value.final!==undefined&&!pair(value.final)||value.final_progress!==undefined&&!pair(value.final_progress))return false;
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
  if(!optionalBoolean(value.can_start_new)||!optionalBoolean(value.stopping)||!optionalBoolean(value.cancelling)||!optionalBoolean(value.model_switching)||!optionalBoolean(value.retry_supported)||!optionalBoolean(value.save_raw_audio)||!optionalBoolean(value.save_raw_audio_locked)||!optionalBoolean(value.audio_saved)||!optionalBoolean(value.partial)||!optionalBoolean(value.capture_discontinuity)||!optionalBoolean(value.target_capabilities_assumed)||!optionalBoolean(value.desktop_mode)||!optionalBoolean(value.recording_started)||!optionalBoolean(value.capture_active)||!optionalNumber(value.generation))throw new Error('Invalid local API snapshot');
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

export function isVisibleGroup(group:Group):boolean {
  const pair=group.live?.current||group.final||group.final_progress;
  const issue=group.live?.issue||group.final?.issue;
  return Boolean(issue||!group.complete||pair&&(pair.source.trim()||pair.translation.trim()));
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
