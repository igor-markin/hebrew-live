// Push channel for the local state: Server-Sent Events first, polling `state` as the fallback.
export type EventSourceLike = {onmessage:((event:{data:string})=>void)|null;onerror:((event:unknown)=>void)|null;close:()=>void};
export type EventSourceFactory = new (url:string)=>EventSourceLike;

/**
 * Opens the push stream and hands every message to `onData`. `onFallback` runs at most once, when the browser has
 * no EventSource or the stream fails (HTTP error, push switched off on the server, broken connection); the stream
 * is closed first, so the caller can start polling without a gap. The returned function stops the stream silently.
 */
export function openStateStream(url:string,onData:(text:string)=>void,onFallback:()=>void,
    Source:EventSourceFactory|undefined=(globalThis as {EventSource?:EventSourceFactory}).EventSource):()=>void {
  let live=true;
  let source:EventSourceLike|undefined;
  const stop=()=>{live=false;source?.close();};
  if(typeof Source!=='function'){live=false;onFallback();return stop;}
  try{source=new Source(url);}catch{live=false;onFallback();return stop;}
  source.onmessage=event=>{if(live)onData(event.data);};
  source.onerror=()=>{if(!live)return;stop();onFallback();};
  return stop;
}
