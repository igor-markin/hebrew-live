import assert from 'node:assert/strict';
import test from 'node:test';
import {openStateStream} from '../src/liveStream.ts';
import type {EventSourceLike} from '../src/liveStream.ts';

class FakeSource implements EventSourceLike {
  static created:FakeSource[]=[];
  onmessage:((event:{data:string})=>void)|null=null;
  onerror:((event:unknown)=>void)|null=null;
  closed=false;
  url:string;
  constructor(url:string){this.url=url;FakeSource.created.push(this);}
  close(){this.closed=true;}
}

test('delivers pushed snapshots to the consumer',()=>{
  FakeSource.created=[];const seen:string[]=[];let fallbacks=0;
  openStateStream('../events',text=>seen.push(text),()=>{fallbacks++;},FakeSource);
  const [source]=FakeSource.created;
  assert.equal(source.url,'../events');
  source.onmessage?.({data:'{"a":1}'});source.onmessage?.({data:'{"a":2}'});
  assert.deepEqual(seen,['{"a":1}','{"a":2}']);assert.equal(fallbacks,0);assert.equal(source.closed,false);
});

test('falls back to polling once when the stream errors, and closes it first',()=>{
  FakeSource.created=[];const seen:string[]=[];let fallbacks=0,closedAtFallback=false;
  openStateStream('../events',text=>seen.push(text),()=>{fallbacks++;closedAtFallback=FakeSource.created[0].closed;},FakeSource);
  const [source]=FakeSource.created;
  source.onerror?.(new Event('error'));source.onerror?.(new Event('error'));
  source.onmessage?.({data:'late'});
  assert.equal(fallbacks,1);assert.equal(closedAtFallback,true);assert.equal(source.closed,true);assert.deepEqual(seen,[]);
});

test('falls back immediately when EventSource is missing or cannot be constructed',()=>{
  let fallbacks=0;
  const stop=openStateStream('../events',()=>assert.fail('no data expected'),()=>{fallbacks++;},undefined);
  assert.equal(fallbacks,1);stop();
  class Broken{constructor(){throw new Error('blocked');}onmessage=null;onerror=null;close(){}}
  openStateStream('../events',()=>assert.fail('no data expected'),()=>{fallbacks++;},Broken);
  assert.equal(fallbacks,2);
});

test('stopping the stream is silent: no fallback and no more data',()=>{
  FakeSource.created=[];const seen:string[]=[];let fallbacks=0;
  const stop=openStateStream('../events',text=>seen.push(text),()=>{fallbacks++;},FakeSource);
  const [source]=FakeSource.created;
  source.onmessage?.({data:'one'});stop();source.onmessage?.({data:'two'});source.onerror?.(new Event('error'));
  assert.deepEqual(seen,['one']);assert.equal(fallbacks,0);assert.equal(source.closed,true);
});
