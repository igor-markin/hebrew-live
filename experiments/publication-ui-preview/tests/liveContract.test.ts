import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {parseLiveState,partialNoticeKind} from '../src/liveState.ts';

const fixture=JSON.parse(readFileSync(new URL('../../../tests/fixtures/live_states.json',import.meta.url),'utf8'));
test('synthetic Python/frontend contract snapshots parse without coercion',()=>{
  assert.match(fixture.provenance,/Synthetic/);
  for(const item of fixture.states){const parsed=parseLiveState(item.state);assert.equal(parsed.phase,item.state.phase);}
});

test('partial UI contract preserves structured cause and has a generic legacy fallback',()=>{
  const base={phase:'finished',groups:[],status:'saved',paused:true,finished:true,direction:'he-en'};
  const detailed=parseLiveState({...base,partial:true,partial_kind:'known_unprocessed',save_raw_audio_locked:true,
    partial_details:[{part:2,direction:'he-ru',reason:'translation_backlog',start:0,end:5.25}]});
  assert.equal(detailed.partial_details?.[0].direction,'he-ru');
  assert.equal(detailed.save_raw_audio_locked,true);assert.equal(partialNoticeKind(detailed),'known_unprocessed');
  assert.equal(partialNoticeKind(parseLiveState({...base,partial:true})),'generic');
  assert.equal(partialNoticeKind(parseLiveState({...base,partial:false})),null);
});
