// The phone's read-only copy of the window (phone_view.py) is served under `/<secret>/phone/`;
// the Mac's own window under `/<secret>/live/`. The same build draws both.
export const VIEWER_SEGMENT='phone';

/** Whether this page is the phone's copy: it then shows the conversation only and sends nothing back. */
export function isViewerPath(pathname:string):boolean {
  return pathname.split('/').filter(Boolean)[1]===VIEWER_SEGMENT;
}

export type PhoneViewStatus='off'|'starting'|'on'|'no_tailscale'|'port_busy'|'failed';
const NOTES:Record<PhoneViewStatus,'phoneViewHintOff'|'phoneViewStarting'|'phoneViewHint'|'phoneViewNoTailscale'|'phoneViewPortBusy'|'phoneViewFailed'>={
  off:'phoneViewHintOff',starting:'phoneViewStarting',on:'phoneViewHint',no_tailscale:'phoneViewNoTailscale',port_busy:'phoneViewPortBusy',failed:'phoneViewFailed'};

/** The note under the «translation on the phone» switch. */
export function phoneViewNote(enabled:boolean|undefined,status:string|null|undefined){
  if(!enabled)return NOTES.off;
  return NOTES[(status&&status in NOTES?status:'starting') as PhoneViewStatus];
}

/** What the phone shows before the first card: it has no buttons, so it says what the Mac is doing. */
export function viewerIdleNote(recordingStarted:boolean|undefined):'viewerWaiting'|'viewerPaused' {
  return recordingStarted?'viewerPaused':'viewerWaiting';
}

/** The recording controls the phone shows: the same as the window's, minus everything else. */
export type ViewerControls={
  toggle:'startRecording'|'continue'|'pause'|null;toggleBlocked:boolean;
  finish:boolean;finishEnabled:boolean;next:boolean;
};
export function viewerControls(state:{finished:boolean;stopping?:boolean;paused:boolean;can_start_new?:boolean;
  desktop_mode?:boolean;recording_started?:boolean;status_code?:string|null;phase:string;model_switching?:boolean;
  input_source?:string;phone_status?:string|null}):ViewerControls {
  if(state.finished)return {toggle:null,toggleBlocked:false,finish:false,finishEnabled:false,next:!!state.can_start_new};
  if(state.stopping)return {toggle:null,toggleBlocked:false,finish:false,finishEnabled:false,next:false};
  const loading=state.phase==='loading'||state.phase==='opening';
  const phoneBlocks=!state.recording_started&&state.input_source==='phone'&&state.phone_status!=='ready';
  const toggle=state.paused?(state.desktop_mode&&state.status_code==='ready_to_start'||!state.recording_started?'startRecording':'continue'):'pause';
  return {toggle,toggleBlocked:loading||!!state.model_switching||phoneBlocks,finish:true,
    finishEnabled:!loading&&!state.model_switching&&!(state.desktop_mode&&!state.recording_started),next:false};
}
