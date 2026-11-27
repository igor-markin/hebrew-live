import assert from 'node:assert/strict';
import test from 'node:test';
import {isViewerPath,phoneViewNote,viewerControls,viewerIdleNote} from '../src/viewer.ts';
import {translator} from '../src/i18n.ts';
import {parseLiveState} from '../src/liveState.ts';

test('only the phone path is the read-only copy',()=>{
  assert.equal(isViewerPath('/s3cret/phone/'),true);
  assert.equal(isViewerPath('/s3cret/phone/live.html'),true);
  for(const path of ['/s3cret/live/','/s3cret/','/phone/','/s3cret/live/phone/',''])assert.equal(isViewerPath(path),false,path);
});

test('the switch explains each state of the phone link in every interface language',()=>{
  assert.equal(phoneViewNote(false,'on'),'phoneViewHintOff');
  assert.equal(phoneViewNote(true,'on'),'phoneViewHint');
  assert.equal(phoneViewNote(true,'no_tailscale'),'phoneViewNoTailscale');
  assert.equal(phoneViewNote(true,'port_busy'),'phoneViewPortBusy');
  assert.equal(phoneViewNote(true,null),'phoneViewStarting');
  assert.equal(phoneViewNote(true,'something new'),'phoneViewStarting');
  for(const locale of ['en','ru','he'] as const){
    const tx=translator(locale);
    for(const key of ['phoneView','phoneViewHintOff','phoneViewStarting','phoneViewHint','phoneViewNoTailscale','phoneViewPortBusy','phoneViewFailed','phoneViewCopy','phoneViewCopied','viewerNote','viewerWaiting','viewerPaused'] as const)
      assert.notEqual(tx(key),key,`${locale} ${key}`);
  }
  assert.equal(translator('ru')('phoneView'),'Перевод на телефоне');
});

test('before the first card the phone says what is happening instead of naming a button',()=>{
  assert.equal(viewerIdleNote(false),'viewerWaiting');
  assert.equal(viewerIdleNote(undefined),'viewerWaiting');
  assert.equal(viewerIdleNote(true),'viewerPaused');
  for(const locale of ['en','ru','he'] as const){
    const tx=translator(locale);
    for(const key of ['viewerWaiting','viewerPaused'] as const)
      assert.doesNotMatch(tx(key),/Continue|Продолж|המשך|Start|Начать/,`${locale} ${key}`);
  }
  assert.equal(translator('ru')('viewerWaiting'),'Перевод появится здесь, когда начнётся запись.');
});

test('the phone starts, pauses and finishes the recording like the window',()=>{
  const ready={phase:'listening',finished:false,paused:true,desktop_mode:true,recording_started:false,status_code:'ready_to_start'};
  assert.deepEqual(viewerControls(ready),{toggle:'startRecording',toggleBlocked:false,finish:true,finishEnabled:false,next:false});
  assert.equal(viewerControls({...ready,paused:false,recording_started:true,status_code:'listening'}).toggle,'pause');
  assert.equal(viewerControls({...ready,paused:false,recording_started:true}).finishEnabled,true);
  assert.equal(viewerControls({...ready,recording_started:true,status_code:'paused'}).toggle,'continue');
  assert.equal(viewerControls({...ready,input_source:'phone',phone_status:'not_found'}).toggleBlocked,true);
  assert.equal(viewerControls({...ready,input_source:'phone',phone_status:'ready'}).toggleBlocked,false);
  assert.equal(viewerControls({...ready,phase:'loading'}).toggleBlocked,true);
  assert.deepEqual(viewerControls({...ready,stopping:true}),{toggle:null,toggleBlocked:false,finish:false,finishEnabled:false,next:false});
  assert.equal(viewerControls({...ready,finished:true,can_start_new:true}).next,true);
  assert.equal(viewerControls({...ready,finished:true,can_start_new:false}).next,false);
});

test('the phone link fields are checked like the rest of the snapshot',()=>{
  const base={phase:'listening',groups:[],status:'ok',paused:false,finished:false,direction:'he-ru'};
  const parsed=parseLiveState({...base,phone_view:true,phone_view_status:'on',phone_view_url:'http://100.1.2.3:8794/x/phone/',viewer:true});
  assert.equal(parsed.phone_view_url,'http://100.1.2.3:8794/x/phone/');
  assert.equal(parseLiveState({...base,phone_view_url:null}).phone_view_url,null);
  for(const bad of [{phone_view:'yes'},{phone_view_status:1},{phone_view_url:5},{viewer:'1'}])
    assert.throws(()=>parseLiveState({...base,...bad}),/Invalid local API snapshot/,JSON.stringify(bad));
});
