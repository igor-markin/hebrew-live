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
