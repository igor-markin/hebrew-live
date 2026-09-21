import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {parseLiveState} from '../src/liveState.ts';

const fixture=JSON.parse(readFileSync(new URL('../../../tests/fixtures/live_states.json',import.meta.url),'utf8'));
test('synthetic Python/frontend contract snapshots parse without coercion',()=>{
  assert.match(fixture.provenance,/Synthetic/);
  for(const item of fixture.states){const parsed=parseLiveState(item.state);assert.equal(parsed.phase,item.state.phase);}
});
