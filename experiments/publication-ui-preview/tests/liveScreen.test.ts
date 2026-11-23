import assert from 'node:assert/strict';
import test from 'node:test';
import {agreedSplit,dayNotes,figureParts,shownSource} from '../src/liveState.ts';
import type {DayIssue,Group} from '../src/liveState.ts';

const figures=(text:string)=>figureParts(text).filter(part=>part.figure).map(part=>part.text);

test('marks times, dates, sums and plain numbers',()=>{
  assert.deepEqual(figures('во вторник в 10:30, 23.11, стоит 1,500 ₪ и 20%'),['10:30','23.11','1,500 ₪','20%']);
  assert.deepEqual(figures('בשעה 10 בבוקר, 250 ש"ח'),['10','250 ש"ח']);
  assert.deepEqual(figures('без чисел'),[]);
  assert.equal(figureParts('в 10 часов').map(part=>part.text).join(''),'в 10 часов');
});

test('an open group shows the newest Hebrew before its translation arrives',()=>{
  const group:Group={id:'0:1',direction:'he-ru',complete:false,live:{current:{source:'שלום',translation:'Привет'},history:[],stage:'open'},
    source_live:{source:'שלום אני רוצה'}};
  assert.equal(shownSource(group,group.live!.current),'שלום אני רוצה');
  assert.equal(shownSource({...group,complete:true},group.live!.current),'שלום');
  assert.equal(shownSource({...group,source_live:undefined},group.live!.current),'שלום');
});

test('splits an open translation into agreed words and the rest',()=>{
  assert.deepEqual(agreedSplit('Я хочу записаться на прием',2),['Я хочу','записаться на прием']);
  assert.deepEqual(agreedSplit('Я хочу',0),['','Я хочу']);
});

test('weekday notes come from closed phrases only, once each',()=>{
  const live=(stage:string,days:DayIssue[])=>({current:{source:'',translation:''},history:[],stage,days});
  const groups:Group[]=[
    {id:'1',direction:'he-ru',complete:true,live:live('closed',[{kind:'fixed',he:'שלישי',ru:'четверг',expected:'вторник'},{kind:'extra',he:'',ru:'среду',expected:''}])},
    {id:'2',direction:'he-ru',complete:true,live:live('closed',[{kind:'fixed',he:'שלישי',ru:'понедельник',expected:'вторник'}])},
    {id:'3',direction:'he-ru',complete:false,live:live('open',[{kind:'missing',he:'שישי',ru:'',expected:'пятница'}])}];
  assert.deepEqual(dayNotes(groups),{fixed:['вторник'],check:['среду']});
});
