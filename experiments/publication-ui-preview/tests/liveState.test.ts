import assert from 'node:assert/strict';
import test from 'node:test';
import {archiveRecordingLabel,isVisibleGroup,keepStableGroups,mergeLiveState,parseLiveState,virtualIndexes} from '../src/liveState.ts';

const state={groups:[],status:'Слушаю',paused:false,finished:false,direction:'he-ru',phase:'listening'};

test('rejects a damaged API snapshot',()=>{
  assert.throws(()=>parseLiveState({...state,status:undefined}));
  assert.throws(()=>parseLiveState({...state,groups:[{id:'1'}]}));
});

test('normalizes an unknown phase without depending on status text',()=>{
  assert.equal(parseLiveState({...state,phase:undefined}).phase,'listening');
  assert.throws(()=>parseLiveState({...state,phase:'future'}));
});

test('rejects malformed optional fields consumed by the UI',()=>{
  for(const patch of [{session:{}},{device:{}},{warning:[]},{stopping:'yes'},{generation:'1'},{exports:[{id:'1'}]},{ui_locale:'fr'},{target_error_code:[]},{target_languages:[{code:'en'}]}])assert.throws(()=>parseLiveState({...state,...patch}));
});

test('accepts localized settings and model-scoped target options',()=>{
  const parsed=parseLiveState({...state,status_code:'listening',ui_locale:'he',target_language:'en',target_languages:[{code:'en',name:'English',rtl:false}]});
  assert.equal(parsed.ui_locale,'he');
  assert.equal(parsed.target_languages?.[0].code,'en');
});

test('accepts nullable issue and reason emitted by the Python backend',()=>{
  const current={source:'שלום',translation:'Привет'};
  const parsed=parseLiveState({...state,groups:[{id:'1',direction:'he-ru',complete:false,live:{current,history:[],stage:'open',issue:null,reason:null,start:0,end:1}}]});
  assert.equal(parsed.groups[0].live?.current.translation,'Привет');
});

test('accepts a transient streaming pair without changing the durable version',()=>{
  const current={source:'שלום',translation:'Старый перевод'};
  const group={id:'1',direction:'he-ru',complete:false,live:{current,history:[],stage:'open'},stream:{source:'שלום חדש',translation:'Новый'}};
  const parsed=parseLiveState({...state,groups:[group]});
  assert.equal(parsed.groups[0].stream?.translation,'Новый');
  assert.equal(parsed.groups[0].live?.current.translation,'Старый перевод');
  assert.throws(()=>parseLiveState({...state,groups:[{...group,stream:{source:'שלום'}}]}));
});

test('retains unchanged group objects by revision',()=>{
  const first={id:'1',revision:3,direction:'he-ru',complete:false};
  const next={...first};
  assert.equal(keepStableGroups([first],[next])[0],first);
  assert.notEqual(keepStableGroups([first],[{...next,revision:4}])[0],first);
});

test('preserves the order supplied by the server',()=>{
  const first={id:'1',revision:1,direction:'he-ru',complete:false};
  const second={id:'2',revision:1,direction:'he-ru',complete:false};
  const reordered=keepStableGroups([first,second],[{...second},{...first}]);
  assert.deepEqual(reordered.map(item=>item.id),['2','1']);
  assert.equal(reordered[0],second);
});

test('does not reuse groups across session or generation boundaries',()=>{
  const first={id:'1',revision:1,direction:'he-ru',complete:false};
  const previous=parseLiveState({...state,session:'old',generation:1,groups:[first]});
  const sessionGroup={...first};
  assert.equal(mergeLiveState(previous,parseLiveState({...state,session:'new',generation:1,groups:[sessionGroup]})).groups[0],sessionGroup);
  const generationGroup={...first};
  assert.equal(mergeLiveState(previous,parseLiveState({...state,session:'old',generation:2,groups:[generationGroup]})).groups[0],generationGroup);
});

test('clamps a stale virtual range when a reloaded archive becomes smaller',()=>{
  assert.deepEqual(virtualIndexes(250,[240,250]),[240,241,242,243,244,245,246,247,248,249]);
  assert.deepEqual(virtualIndexes(3,[240,250]),[2]);
  assert.deepEqual(virtualIndexes(3,[240,250],1),[2,1]);
  assert.deepEqual(virtualIndexes(0,[240,250],249),[]);
  assert.deepEqual(virtualIndexes(1,[240,250]),[0]);
});

test('hides only completed empty groups without an issue',()=>{
  const empty={id:'1',direction:'he-ru',complete:true,final:{source:'',translation:''}};
  assert.equal(isVisibleGroup(empty),false);
  assert.equal(isVisibleGroup({...empty,final:{source:'',translation:'',issue:'Речь не распознана'}}),true);
  assert.equal(isVisibleGroup({...empty,complete:false}),true);
});

test('describes the actual recording phase while an archive is open',()=>{
  assert.equal(archiveRecordingLabel(parseLiveState({...state,phase:'paused',paused:true})),'recordingPaused');
  assert.equal(archiveRecordingLabel(parseLiveState({...state,phase:'stopping',stopping:true})),'recordingEnding');
  assert.equal(archiveRecordingLabel(parseLiveState({...state,phase:'loading'})),'recordingPreparing');
  assert.equal(archiveRecordingLabel(parseLiveState({...state,phase:'listening'})),'recordingContinues');
});
