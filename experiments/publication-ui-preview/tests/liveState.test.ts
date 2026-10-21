import assert from 'node:assert/strict';
import test from 'node:test';
import {archiveRecordingLabel,heldText,isQuietMiss,isVisibleGroup,keepStableGroups,mergeLiveState,parseLiveState,shownPair,speechTurns,tickerParagraphs,unchangedPrefix,virtualIndexes} from '../src/liveState.ts';

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

test('mutes short empty bubbles the backend gave up on, for both unavailable messages',()=>{
  const live=(issue:string,stage='unavailable')=>({current:{source:'',translation:''},history:[],stage,issue});
  for(const issue of ['Речь не распознана','Завершённая версия недоступна; ранний текст не подтверждён']){
    assert.equal(isQuietMiss(live(issue),issue,true,3,4.5),true);
    assert.equal(isQuietMiss(live(issue),issue,true,3,5.5),false);
    assert.equal(isQuietMiss(live(issue),issue,false,3,4.5),false);
    assert.equal(isQuietMiss(live(issue),issue,true),false);
    assert.equal(isQuietMiss(live(issue,'closed'),issue,true,3,4.5),false);
  }
  assert.equal(isQuietMiss(live('Отменено'),'Отменено',true,3,4.5),false);
  assert.equal(isQuietMiss(undefined,'Речь не распознана',true,3,4.5),false);
});

test('describes the actual recording phase while an archive is open',()=>{
  assert.equal(archiveRecordingLabel(parseLiveState({...state,phase:'paused',paused:true})),'recordingPaused');
  assert.equal(archiveRecordingLabel(parseLiveState({...state,phase:'stopping',stopping:true})),'recordingEnding');
  assert.equal(archiveRecordingLabel(parseLiveState({...state,phase:'loading'})),'recordingPreparing');
  assert.equal(archiveRecordingLabel(parseLiveState({...state,phase:'listening'})),'recordingContinues');
});

test('a refresh stream does not replace a translation already shown',()=>{
  const current={source:'שלום',translation:'Старый перевод целиком'};
  const stream={source:'שלום חדש',translation:'Новый'};
  assert.equal(shownPair({id:'1',direction:'he-ru',complete:false,live:{current,history:[],stage:'open'},stream},true)?.translation,'Старый перевод целиком');
  assert.equal(shownPair({id:'1',direction:'he-ru',complete:false,live:{current,history:[],stage:'open'},stream})?.translation,'Новый');  // off by default
  assert.equal(shownPair({id:'1',direction:'he-ru',complete:false,live:{current:{source:'שלום',translation:''},history:[],stage:'open'},stream},true)?.translation,'Новый');
  assert.equal(shownPair({id:'1',direction:'he-ru',complete:false,stream},true)?.translation,'Новый');
});

test('unchanged leading words end at a word boundary',()=>{
  assert.equal(unchangedPrefix('Он пришёл домой','Он пришёл домой поздно'),'Он пришёл домой '.length);
  assert.equal(unchangedPrefix('Он пришёл домой','Он пришёл в дом'),'Он пришёл '.length);
  assert.equal(unchangedPrefix('Он при','Он пришёл'),'Он '.length);
  assert.equal(unchangedPrefix('','Новый текст'),0);
  assert.equal(unchangedPrefix('Тот же текст','Тот же текст'),'Тот же текст'.length);
});

test('sentences split while the speaker goes on share one bubble; a pause starts a new one',()=>{
  const closed=(id:string,reason:string,extra={})=>({id,direction:'he-ru',complete:true,live:{current:{source:id,translation:id},history:[],stage:'closed',reason,...extra}});
  const open={id:'e',direction:'he-ru',complete:false,live:{current:{source:'e',translation:''},history:[],stage:'open'}};
  const turns=speechTurns([closed('a','sentence'),closed('b','silence'),closed('c','sentence'),closed('d','sentence',{issue:'Пустой перевод'}),open],true);
  assert.deepEqual(turns.map(turn=>turn.groups.map(group=>group.id)),[['a','b'],['c'],['d'],['e']]);
  assert.deepEqual(turns.map(turn=>[turn.id,turn.position]),[['a',1],['c',3],['d',4],['e',5]]);
  const long=speechTurns(Array.from({length:10},(_,index)=>closed(String(index),'sentence')),true);
  assert.equal(speechTurns([closed('a','sentence'),closed('b','silence')]).length,2);  // off by default
  assert.deepEqual(long.map(turn=>turn.groups.length),[8,2]);
});

test('an open sentence never gets shorter on screen; a closed one shows its own text',()=>{
  assert.equal(heldText('Для получения информации о судах','Для получения',true),'Для получения информации о судах');
  assert.equal(heldText('Для получения','Чтобы получить информацию о судах',true),'Чтобы получить информацию о судах');
  assert.equal(heldText('Для получения информации о судах','Для информации.',false),'Для информации.');
  assert.doesNotThrow(()=>parseLiveState({...state,frozen_sentences:true}));
  assert.throws(()=>parseLiveState({...state,frozen_sentences:'yes'}));
});

test('the ticker keeps closed sentences in place and ends with the open one; a pause starts a paragraph',()=>{
  const closed=(id:string,reason:string,extra={})=>({id,direction:'he-ru',complete:true,live:{current:{source:id,translation:id},history:[],stage:'closed',reason,...extra}});
  const open={id:'e',direction:'he-ru',complete:false,live:{current:{source:'e',translation:'e'},history:[],stage:'open'}};
  const empty={id:'x',direction:'he-ru',complete:true,live:{current:{source:'',translation:''},history:[],stage:'unavailable',issue:'Речь не распознана'}};
  const paragraphs=tickerParagraphs([closed('a','sentence'),closed('b','silence'),empty,closed('c','sentence'),closed('d','sentence',{issue:'Пустой перевод'}),open]);
  assert.deepEqual(paragraphs.map(item=>item.sentences.map(({group,pending})=>group.id+(pending?'?':''))),[['a','b'],['c'],['d'],['e?']]);
  assert.deepEqual(tickerParagraphs([closed('a','sentence'),open]).map(item=>item.sentences.length),[2]);
  assert.doesNotThrow(()=>parseLiveState({...state,ticker_view:true}));
  assert.throws(()=>parseLiveState({...state,ticker_view:1}));
});
