import assert from 'node:assert/strict';
import test from 'node:test';
import {filterVocabulary,parseVocabularyFile,vocabularyCsv} from '../src/vocabularyFile.ts';

test('the app\'s own vocabulary.json and a plain JSON list are read',()=>{
  const file=JSON.stringify({version:1,entries:[{he:' סולמית ',ru:'решётка (#)',en:''},{he:'כוכבית',ru:'звёздочка'}]});
  assert.deepEqual(parseVocabularyFile(file),[{he:'סולמית',ru:'решётка (#)',en:''},{he:'כוכבית',ru:'звёздочка',en:''}]);
  assert.deepEqual(parseVocabularyFile('[{"he":"חיפה","en":"Haifa"}]'),[{he:'חיפה',ru:'',en:'Haifa'}]);
});

test('a table from a spreadsheet is read with or without a header row',()=>{
  const csv='\uFEFFhe,ru,en\r\nסולמית,"решётка, знак #",hash\r\nכוכבית,звёздочка,\r\n';
  assert.deepEqual(parseVocabularyFile(csv),[{he:'סולמית',ru:'решётка, знак #',en:'hash'},{he:'כוכבית',ru:'звёздочка',en:''}]);
  assert.deepEqual(parseVocabularyFile('Иврит;Русский\nקופת חולים;больничная касса\n'),[{he:'קופת חולים',ru:'больничная касса',en:''}]);
  assert.deepEqual(parseVocabularyFile('שלוחה\tдобавочный\n\nמד"א\tскорая\n'),[{he:'שלוחה',ru:'добавочный',en:''},{he:'מד"א',ru:'скорая',en:''}]);
});

test('a file without entries is refused',()=>{
  assert.throws(()=>parseVocabularyFile(''));
  assert.throws(()=>parseVocabularyFile('{"version":1}'));
  assert.throws(()=>parseVocabularyFile('he,ru,en\n'));
});

test('the exported table reads back as the same list',()=>{
  const entries=[{he:'מד"א',ru:'МАДА, скорая',en:''},{he:'כוכבית',ru:'звёздочка "*"',en:'star'}];
  const csv=vocabularyCsv(entries);
  assert.ok(csv.startsWith('\uFEFFhe,ru,en\r\n'));
  assert.deepEqual(parseVocabularyFile(csv),entries);
});

test('search finds Hebrew without vowel marks and translations in any case',()=>{
  const entries=[{he:'קופת חולים',ru:'больничная касса',en:''},{he:'שלוחה',ru:'добавочный номер',en:'Extension'}];
  assert.deepEqual(filterVocabulary(entries,'  '),entries);
  assert.deepEqual(filterVocabulary(entries,'קוּפַּת').map(entry=>entry.he),['קופת חולים']);
  assert.deepEqual(filterVocabulary(entries,'extension').map(entry=>entry.he),['שלוחה']);
  assert.deepEqual(filterVocabulary(entries,'КАССА').map(entry=>entry.he),['קופת חולים']);
});
