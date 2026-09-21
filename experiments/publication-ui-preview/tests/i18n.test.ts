import assert from 'node:assert/strict';
import test from 'node:test';
import {beginLocaleRequest,directionParts,htmlLanguage,isRtlLanguage,issueText,languageName,reconcileLocale,rollbackLocale,translator} from '../src/i18n.ts';

test('interface dictionaries cover English, Russian, and Hebrew without fallback',()=>{
  assert.equal(translator('en')('settings'),'Settings');
  assert.equal(translator('ru')('settings'),'Настройки');
  assert.equal(translator('he')('settings'),'הגדרות');
  assert.equal(translator('en')('deleteSession',{label:'20.09'}),'Delete session 20.09');
});

test('translation directions preserve compound target codes and writing direction',()=>{
  assert.deepEqual(directionParts('he-zh-tw'),['he','zh-tw']);
  assert.equal(htmlLanguage('zh-tw'),'zh-Hant');
  assert.equal(isRtlLanguage('ur'),true);
  assert.equal(isRtlLanguage('en'),false);
  assert.match(languageName('en','zh-tw','Chinese (Traditional)'),/Chinese/i);
});

test('known backend issues are localized without translating user speech',()=>{
  assert.equal(issueText('en','Ошибка перевода'),'Translation error');
  assert.equal(issueText('he','Повтор генерации'),'יצירה חוזרת');
  assert.equal(issueText('en','Распознан текст на другом языке; перевод пропущен'),'Non-Hebrew text was recognized; translation was skipped.');
  assert.equal(issueText('en','Ошибка перевода: local failure'),'Translation error: local failure');
  assert.equal(issueText('en','model detail'),'model detail');
});

test('locale request ignores stale polls, commits confirmation, and rolls back failure',()=>{
  const request={value:'he' as const,previous:'en' as const};
  assert.deepEqual(beginLocaleRequest('en','en','he',null),request);
  assert.equal(beginLocaleRequest('he','en','ru',request),null);
  assert.deepEqual(reconcileLocale('en',request),{locale:'he',request});
  assert.deepEqual(reconcileLocale('he',request),{locale:'he',request:null});
  assert.equal(rollbackLocale('ru',request),'ru');
  assert.equal(rollbackLocale(undefined,request),'en');
});
