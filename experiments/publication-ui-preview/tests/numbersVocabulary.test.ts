import assert from 'node:assert/strict';
import test from 'node:test';
import {numberNotes,parseLiveState,parseVocabulary,shortHebrew} from '../src/liveState.ts';
import type {Group} from '../src/liveState.ts';
import {translator} from '../src/i18n.ts';

const pair={source:'בשעה 10',translation:'В 11'};
const group=(id:string,stage:string,numbers?:unknown,complete=true)=>({id,direction:'he-ru',complete,live:{current:pair,history:[],stage,...(numbers===undefined?{}:{numbers})}});
const state=(groups:unknown[])=>({groups,status:'',paused:false,finished:false,direction:'he-ru',phase:'listening'});

test('number notes are validated and come only from closed phrases',()=>{
  const groups=parseLiveState(state([group('a','closed',[{kind:'missing',number:'10'},{kind:'extra',number:'11'}]),
    group('b','technical',[{kind:'missing',number:'10'}]),group('c','closed',[])])).groups;
  assert.deepEqual(numberNotes(groups),['10','11']);                     // once each across a merged turn
  assert.deepEqual(numberNotes(groups.slice(2)),[]);
  const open=group('d','open',[{kind:'missing',number:'7'}],false) as Group;
  assert.deepEqual(numberNotes([open]),[]);                               // growing figures are never noted
  assert.deepEqual(numberNotes([group('e','unavailable',[{kind:'missing',number:'7'}]) as Group]),[]);
  assert.deepEqual(numberNotes([group('f','closed') as Group]),[]);       // an older engine sends none
  for(const bad of [[{kind:'lost',number:'1'}],[{kind:'missing',number:'1a'}],[{kind:'missing',number:1}],{}])
    assert.throws(()=>parseLiveState(state([group('x','closed',bad)])),JSON.stringify(bad));
});

test('the note reads the same way in every language',()=>{
  assert.equal(translator('ru')('checkNumber',{numbers:'30'}),'Проверь число: 30');
  assert.equal(translator('en')('checkNumber',{numbers:'30, 45'}),'Check the number: 30, 45');
  assert.match(translator('he')('checkNumber',{numbers:'30'}),/30/);
  for(const locale of ['en','ru','he'] as const)assert.ok(translator(locale)('vocabularyShort').includes('2'));
});

test('the vocabulary list is validated and short words are flagged',()=>{
  const list={entries:[{he:'חיפה',ru:'Хайфа',en:''}],damaged:false,enabled:true,limit:500,lengths:{he:60,ru:120,en:120}};
  assert.deepEqual(parseVocabulary(list),list);
  assert.throws(()=>parseVocabulary({...list,entries:[{he:'חיפה',ru:1,en:''}]}));
  assert.throws(()=>parseVocabulary({...list,lengths:{he:60}}));
  assert.throws(()=>parseVocabulary({...list,damaged:'no'}));
  assert.equal(shortHebrew('קו'),true);assert.equal(shortHebrew('חיפה'),false);
  assert.equal(shortHebrew(''),false);assert.equal(shortHebrew('קו חם'),false);
});
