import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {TEXT_SCALE,TEXT_SIZES,textSize,translationPixels} from '../src/textSize.ts';
import {translator} from '../src/i18n.ts';

test('an unknown or missing saved size is the normal one',()=>{
  assert.equal(textSize(null),'normal');
  assert.equal(textSize('huge'),'normal');
  assert.equal(textSize('small'),'small');
});

test('sizes go from smaller to larger and normal keeps the earlier 20 px translation',()=>{
  const scales=TEXT_SIZES.map(size=>TEXT_SCALE[size]);
  assert.deepEqual([...scales].sort((a,b)=>a-b),scales);
  assert.equal(translationPixels('normal'),20);
  assert.ok(translationPixels('smallest')<translationPixels('small'));
});

test('every size has a label in every interface language',()=>{
  for(const locale of ['en','ru','he'] as const){
    const tx=translator(locale);
    assert.notEqual(tx('textSize'),'textSize');
    for(const size of TEXT_SIZES)assert.ok(tx('textSizeOption',{name:tx(`textSize_${size}`),px:String(translationPixels(size))}).includes(String(translationPixels(size))));
  }
});

test('conversation text follows the chosen scale',()=>{
  const css=readFileSync(new URL('../src/live.css',import.meta.url),'utf8');
  for(const rule of ['.bubble-copy>.translation','.bubble-copy>.bubble-hebrew','.bubble-history .translation','.ticker-paragraph','.bubble-source p']){
    const at=css.indexOf(rule+' {');
    assert.ok(at>=0,rule);
    assert.match(css.slice(at,css.indexOf('}',at)),/font-size:calc\(\d+px \* var\(--reading-scale\)\)/,rule);
  }
  for(const size of TEXT_SIZES)assert.ok(css.includes(`html[data-text-size="${size}"]{--reading-scale:${TEXT_SCALE[size]}}`),size);
});
