import assert from 'node:assert/strict';
import test from 'node:test';
import {PHONE_STATUS_TEXT,parseLiveState,phoneBlocksStart,phoneStatusText} from '../src/liveState.ts';
import type {LiveState} from '../src/liveState.ts';
import {translator} from '../src/i18n.ts';

const state={groups:[],status:'Готово к началу',paused:true,finished:false,direction:'he-ru',phase:'paused'};

test('input source fields are validated strictly',()=>{
  const parsed=parseLiveState({...state,input_source:'phone',input_source_locked:false,phone_status:'no_device',input_error:'phone_not_ready'});
  assert.equal(parsed.input_source,'phone');assert.equal(parsed.phone_status,'no_device');
  parseLiveState({...state,input_source:'microphone',phone_status:null,input_error:null});
  parseLiveState(state);                                       // an older engine sends none of them
  assert.throws(()=>parseLiveState({...state,input_source:'bluetooth'}));
  assert.throws(()=>parseLiveState({...state,input_source_locked:'yes'}));
  assert.throws(()=>parseLiveState({...state,phone_status:3}));
  assert.throws(()=>parseLiveState({...state,input_error:'cable'}));
});

test('every phone check result has a text in every language',()=>{
  for(const locale of ['en','ru','he'] as const){
    const tx=translator(locale);
    for(const key of Object.values(PHONE_STATUS_TEXT))assert.ok(tx(key).length>3,`${locale}:${key}`);
    assert.match(tx('phoneStopped',{reason:tx('phoneNoDevice')}),/USB/);
  }
  assert.equal(translator('ru')(phoneStatusText('ready')),'Телефон подключён, жду звонка');
  assert.equal(phoneStatusText('something_new'),'phoneUnknown');
  assert.equal(phoneStatusText(null),'phoneChecking');
  assert.match(translator('en')(phoneStatusText('no_scrcpy')),/brew install scrcpy/);
});

test('start waits for a ready phone but never for the microphone',()=>{
  const at=(values:Partial<LiveState>)=>phoneBlocksStart(parseLiveState({...state,...values}));
  assert.equal(at({input_source:'microphone',phone_status:'no_device'}),false);
  assert.equal(at({}),false);
  assert.equal(at({input_source:'phone',phone_status:'ready'}),false);
  for(const status of ['checking','no_device','unauthorized',null])assert.equal(at({input_source:'phone',phone_status:status}),true,String(status));
  assert.equal(at({input_source:'phone',phone_status:'no_device',recording_started:true}),false);  // pause and resume stay free
});
