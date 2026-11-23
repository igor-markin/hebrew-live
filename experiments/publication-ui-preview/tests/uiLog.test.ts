import assert from 'node:assert/strict';
import test from 'node:test';
import {UiLog,erasedWords,renderRecords} from '../src/uiLog.ts';
import type {Drawn} from '../src/uiLog.ts';
import type {Group} from '../src/liveState.ts';

const live=(source:string,translation:string,extra:Record<string,number>={}):Group=>({id:'0:1',direction:'he-ru',complete:false,revision:1,
  live:{current:{source,translation},history:[],stage:'open',...extra}});

test('counts words the reader saw erased, not words that only grew',()=>{
  assert.equal(erasedWords('','Здравствуйте'),0);
  assert.equal(erasedWords('Я хочу','Я хочу записаться'),0);
  assert.equal(erasedWords('Я хоч','Я хочу'),0);
  assert.equal(erasedWords('Я хочу к врачу','Я хочу записаться к врачу'),2);
  assert.equal(erasedWords('один два три','другое'),3);
});

test('records a group only when its drawn text or state changes, with the publication time',()=>{
  const last=new Map<string,Drawn>();
  const first=renderRecords([live('שלום','Здравствуйте',{emitted_at:10,audio_lag:.4})],last,false,'cards');
  assert.equal(first.length,1);
  assert.deepEqual({...first[0]},{type:'render',group:'0:1',revision:1,shown:'live',complete:false,source:'שלום',translation:'Здравствуйте',
    source_changed:true,translation_changed:true,erased_source:0,erased_translation:0,emitted_at:10,audio_lag:.4,view:'cards'});
  assert.equal(renderRecords([live('שלום','Здравствуйте')],last,false,'cards').length,0);
  const stream:Group={...live('שלום אני','Здравствуйте'),stream:{source:'שלום אני',translation:'Здравствуйте, я',preview_emitted_at:11,audio_lag:.2}};
  const [next]=renderRecords([stream],last,false,'cards');
  assert.equal(next.shown,'stream');assert.equal(next.emitted_at,11);assert.equal(next.audio_lag,.2);
  assert.equal(next.source_changed,true);assert.equal(next.erased_translation,0);
  const [closed]=renderRecords([{...live('שלום','Привет'),complete:true}],last,false,'cards');
  assert.equal(closed.complete,true);assert.equal(closed.erased_translation,2);
});

test('sends batches with the time each record waited',()=>{
  const sent:{body:string;keepalive:boolean}[]=[];let clock=100;
  const log=new UiLog((body,keepalive)=>sent.push({body,keepalive}),()=>clock,1e9);
  log.push({type:'click',target:'button'});clock=130;log.push({type:'scroll',top:5});clock=150;
  log.flush();
  assert.equal(sent.length,1);
  const body=JSON.parse(sent[0].body);
  assert.equal(body.action,'ui_log');
  assert.deepEqual(body.items.map((item:{age_ms:number})=>item.age_ms),[50,20]);
  log.flush();assert.equal(sent.length,1);
});
