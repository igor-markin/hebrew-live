import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {storedHidden,storedValue} from '../src/layout.ts';
import {translator} from '../src/i18n.ts';

const css=readFileSync(new URL('../src/live.css',import.meta.url),'utf8');
const live=readFileSync(new URL('../src/Live.tsx',import.meta.url),'utf8');
const compact=css.slice(css.indexOf('/* Compact window'));

test('only a stored «1» hides a part of the window',()=>{
  assert.equal(storedHidden('1'),true);
  for(const value of ['0','true','',null,undefined])assert.equal(storedHidden(value),false,String(value));
  assert.equal(storedHidden(storedValue(true)),true);
  assert.equal(storedHidden(storedValue(false)),false);
});

test('the menu buttons have labels in every interface language',()=>{
  for(const locale of ['en','ru','he'] as const){
    const tx=translator(locale);
    for(const key of ['hideMenu','showMenu','hideSessions'] as const)assert.notEqual(tx(key),key,`${locale} ${key}`);
  }
});

test('the menu stays on one line and its buttons do not wrap their words',()=>{
  assert.ok(compact.length>100,'compact window rules');
  assert.match(compact,/\.live-toolbar \{flex-wrap:nowrap/);
  assert.match(compact,/\.live-toolbar button,\.live-settings summary \{[^}]*white-space:nowrap/);
  assert.match(compact,/\.live-status strong,\.live-status small \{[^}]*text-overflow:ellipsis/);
  assert.match(compact,/@container \(max-width:\d+px\)\{\.live-toolbar \.button-label\{display:none\}\}/);
  assert.equal((live.match(/className="button-label"/g)||[]).length,3,'help, quit and settings shrink to icons');
});

test('a hidden session list frees its place on a wide window',()=>{
  assert.match(compact,/\.messenger-shell\.sessions-hidden \{padding-left:24px\}/);
  assert.match(compact,/\.messenger-shell\.sessions-hidden \.session-sidebar \{display:none\}/);
  assert.ok(live.includes("sessionsHidden&&!narrow?'sessions-hidden':''"));
});

test('the live view has no page title; a saved conversation keeps its name and the way back',()=>{
  assert.ok(!/<strong>\{[^}]*tx\('liveTitle'\)/.test(live),'no «Live translation» heading');
  assert.ok(live.includes("{selected&&<div className=\"conversation-title\">"));
  assert.ok(live.includes("tx('backToLive')"));
});

test('both choices are saved with the preferences, not only in this window',()=>{
  for(const action of ['menu_hidden','sessions_hidden'])assert.ok(live.includes(`act('${action}',value)`),action);
  assert.ok(live.includes("'menu_hidden','sessions_hidden'"),'allowed while recording, like the text size');
});
