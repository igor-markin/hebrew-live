import assert from 'node:assert/strict';
import test from 'node:test';
import {watchGrowingContent} from '../src/useFollowLatest.ts';

test('new children and later card growth remain observed for follow-latest scrolling',()=>{
  const first={} as Element;const second={} as Element;
  const container={children:[first]} as unknown as HTMLElement;
  let resizeCallback=()=>{};let mutationCallback=()=>{};let growths=0;let resizeDisconnects=0;let mutationDisconnects=0;
  const observed:Element[][]=[];let round:Element[]=[];
  const stop=watchGrowingContent(container,()=>growths++,callback=>{
    resizeCallback=callback;
    return {observe:(target:Element)=>round.push(target),disconnect:()=>{if(round.length)observed.push(round);round=[];resizeDisconnects++;}};
  },callback=>{
    mutationCallback=callback;
    return {observe:()=>{},disconnect:()=>{mutationDisconnects++;}};
  });
  resizeCallback();assert.equal(growths,1);
  (container.children as unknown as Element[]).push(second);mutationCallback();resizeCallback();
  assert.equal(growths,2);assert.deepEqual(round,[first,second]);
  stop();assert.ok(resizeDisconnects>=2);assert.equal(mutationDisconnects,1);
});
