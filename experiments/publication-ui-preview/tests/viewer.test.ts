import assert from 'node:assert/strict';
import test from 'node:test';
import {isViewerPath,phoneViewNote} from '../src/viewer.ts';
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
    for(const key of ['phoneView','phoneViewHintOff','phoneViewStarting','phoneViewHint','phoneViewNoTailscale','phoneViewPortBusy','phoneViewFailed','phoneViewCopy','phoneViewCopied','viewerNote'] as const)
      assert.notEqual(tx(key),key,`${locale} ${key}`);
  }
  assert.equal(translator('ru')('phoneView'),'Перевод на телефоне');
});

test('the phone link fields are checked like the rest of the snapshot',()=>{
  const base={phase:'listening',groups:[],status:'ok',paused:false,finished:false,direction:'he-ru'};
  const parsed=parseLiveState({...base,phone_view:true,phone_view_status:'on',phone_view_url:'http://100.1.2.3:8794/x/phone/',viewer:true});
  assert.equal(parsed.phone_view_url,'http://100.1.2.3:8794/x/phone/');
  assert.equal(parseLiveState({...base,phone_view_url:null}).phone_view_url,null);
  for(const bad of [{phone_view:'yes'},{phone_view_status:1},{phone_view_url:5},{viewer:'1'}])
    assert.throws(()=>parseLiveState({...base,...bad}),/Invalid local API snapshot/,JSON.stringify(bad));
});
