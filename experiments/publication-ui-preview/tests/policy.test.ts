import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { publication, compatible, reducer } from '../src/policy.ts';
import type { Example } from '../src/policy.ts';
const cases: Example[] = JSON.parse(readFileSync(new URL('../src/data/public-cases.json', import.meta.url),'utf8')).cases;
const case11 = cases[0];
function finalWith(change: Partial<Example['terminal']>): Example {return {...case11, terminal: {...case11.terminal, ...change}};}
test('a synthetic revision preserves the pair and exposes terminal as one or two entries', () => {
 for (const c of cases.slice(0,1)) {
  const early = publication(c,false,'single'); assert.deepEqual(early.entries[0].snapshot,c.early); assert.equal(early.history,null);
  const one = publication(c,true,'single'); assert.equal(one.entries.length,1); assert.deepEqual(one.entries[0].snapshot,c.terminal); assert.deepEqual(one.history,c.early); assert.equal(one.replaced,true);
  const two = publication(c,true,'versions'); assert.deepEqual(two.entries.map(e=>e.snapshot),[c.early,c.terminal]); assert.equal(two.history,null);
 }
});
test('compatible synthetic control appends in either mode; retains original snapshot', () => {
 const c=cases[1];assert.equal(compatible(c.early.translation,c.terminal.translation),true);
 for(const mode of ['single','versions'] as const){const v=publication(c,true,mode); assert.equal(v.entries.length,1);assert.equal(v.replaced,false);assert.deepEqual(v.history,c.early);}
});
test('rejected closure cannot promote stale or new draft',()=>{const v=publication(finalWith({status:'rejected'}),true,'single');assert.equal(v.unavailable,true);assert.deepEqual(v.entries[0].snapshot,case11.early);assert.equal(v.history,null);});
test('empty and whitespace closure cannot erase early text',()=>{for(const change of [{translation:''},{translation:' \n'},{source:''},{source:'  '},{closed:false}]){const v=publication(finalWith(change),true,'single');assert.equal(v.unavailable,true);assert.deepEqual(v.entries[0].snapshot,case11.early);}});
test('identical closure has no redundant history',()=>{const v=publication(finalWith({source:case11.early.source,translation:case11.early.translation}),true,'single');assert.equal(v.history,null);assert.equal(v.entries.length,1);});
test('source-only change preserves both versions of source',()=>{const c=finalWith({translation:case11.early.translation});const v=publication(c,true,'single');assert.equal(v.entries[0].snapshot.source,c.terminal.source);assert.equal(v.history?.source,c.early.source);});
test('punctuation, changed words and word boundaries are not normalised',()=>{assert.equal(compatible('Хорошо?','Хорошо, завтра?'),false);assert.equal(compatible('Что','Отлично.'),false);assert.equal(compatible('Я','Яков'),false);assert.equal(compatible('Я','Я приду.'),true);});
test('close is idempotent; mode and theme preserve selection and stage',()=>{let s={selected:case11.id,completed:false,mode:'single' as const,dark:false};const closed=reducer(s,{type:'close'});assert.equal(reducer(closed,{type:'close'}),closed);const switched=reducer(reducer(closed,{type:'mode',mode:'versions'}),{type:'theme'});assert.equal(switched.selected,s.selected);assert.equal(switched.completed,true);assert.equal(switched.dark,true);assert.equal(switched.mode,'versions');});
test('reset and selecting a different example open only the requested example',()=>{const state={selected:case11.id,completed:true,mode:'versions' as const,dark:true};assert.equal(reducer(state,{type:'reset'}).completed,false);assert.equal(reducer(state,{type:'select',id:state.selected}),state);const next=reducer(state,{type:'select',id:cases[1].id});assert.equal(next.completed,false);assert.equal(next.mode,'versions');assert.equal(next.dark,true);assert.equal(next.selected,cases[1].id);});
test('data model is not mutated by toggles, reset, and repeated publication',()=>{const before=JSON.stringify(cases);for(const c of cases){publication(c,true,'single');publication(c,true,'versions');publication(c,false,'single');}assert.equal(JSON.stringify(cases),before);});
