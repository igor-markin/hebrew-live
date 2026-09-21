import {useCallback, useEffect, useLayoutEffect, useRef, useState} from 'react';

type Observer={disconnect:()=>void};
type ResizeFactory=(callback:()=>void)=>Observer&{observe:(target:Element)=>void};
type MutationFactory=(callback:()=>void)=>Observer&{observe:(target:Node,options:MutationObserverInit)=>void};

export function watchGrowingContent(container:HTMLElement,resized:()=>void,
  makeResize:ResizeFactory=callback=>new ResizeObserver(callback),
  makeMutation:MutationFactory=callback=>new MutationObserver(callback)){
  const contentObserver=makeResize(resized);
  const observeContent=()=>{contentObserver.disconnect();for(const child of container.children)contentObserver.observe(child);};
  const mutationObserver=makeMutation(observeContent);
  observeContent();mutationObserver.observe(container,{childList:true});
  return()=>{contentObserver.disconnect();mutationObserver.disconnect();};
}

export function useFollowLatest(contentRevision:string,enabled=true) {
  const [following,setFollowing]=useState(true);
  const active=useRef(true);
  const position=useRef(0);
  const pointerActive=useRef(false);
  const scheduledScroll=useRef<number|undefined>(undefined);
  const containerRef=useRef<HTMLElement|null>(null);
  const stop=useCallback(()=>{active.current=false;setFollowing(false);},[]);
  const scrollNow=useCallback(()=>{
    const container=containerRef.current;
    if(!container||!enabled)return;
    container.scrollTo({top:container.scrollHeight,behavior:'instant'});position.current=container.scrollTop;
  },[enabled]);
  const scroll=useCallback(()=>{
    if(scheduledScroll.current!==undefined)return;
    scheduledScroll.current=requestAnimationFrame(()=>{scheduledScroll.current=undefined;if(active.current)scrollNow();});
  },[scrollNow]);
  const resume=useCallback(()=>{active.current=true;setFollowing(true);scroll();},[scroll]);
  useEffect(()=>{
    const container=containerRef.current;if(!container)return;
    position.current=container.scrollTop;
    const wheel=(event:WheelEvent)=>{if(event.deltaY<0)stop();};
    const moved=()=>{if(pointerActive.current&&container.scrollTop<position.current-2)stop();position.current=container.scrollTop;};
    const pointerDown=()=>{pointerActive.current=true;position.current=container.scrollTop;};
    const pointerUp=()=>{pointerActive.current=false;};
    const resized=()=>{if(active.current)scroll();};
    const key=(event:KeyboardEvent)=>{
      if((event.target as HTMLElement)?.closest('input,textarea,select,[contenteditable="true"]'))return;
      if((event.target as HTMLElement)?.closest('.session-sidebar'))return;
      if(['ArrowUp','PageUp','Home'].includes(event.key)||(event.key===' '&&event.shiftKey))stop();
      if(event.key==='End'){event.preventDefault();resume();}
    };
    const stopWatching=watchGrowingContent(container,resized);
    container.addEventListener('wheel',wheel,{passive:true});container.addEventListener('scroll',moved,{passive:true});container.addEventListener('pointerdown',pointerDown,{passive:true});
    window.addEventListener('pointerup',pointerUp);window.addEventListener('pointercancel',pointerUp);
    window.addEventListener('keydown',key);window.addEventListener('resize',resized);
    return()=>{container.removeEventListener('wheel',wheel);container.removeEventListener('scroll',moved);container.removeEventListener('pointerdown',pointerDown);window.removeEventListener('pointerup',pointerUp);window.removeEventListener('pointercancel',pointerUp);window.removeEventListener('keydown',key);window.removeEventListener('resize',resized);stopWatching();if(scheduledScroll.current!==undefined){cancelAnimationFrame(scheduledScroll.current);scheduledScroll.current=undefined;}};
  },[resume,scroll,stop]);
  useLayoutEffect(()=>{if(active.current&&enabled&&contentRevision)scroll();},[contentRevision,enabled,scroll]);
  return {following,containerRef,stop,resume};
}
