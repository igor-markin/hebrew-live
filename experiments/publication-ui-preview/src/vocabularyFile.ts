import type {VocabularyEntry} from './liveState';

/** The vocabulary window's own hash: the live page opens itself there in a second window. */
export const VOCABULARY_HASH='#vocabulary';

const HEADER=new Set(['he','hebrew','иврит','עברית']);

function rows(text:string,delimiter:string):string[][] {
  // CSV as spreadsheets write it: quoted fields may hold the delimiter, quotes ("") and line breaks
  const out:string[][]=[];let row:string[]=[];let field='';let quoted=false;
  for(let index=0;index<text.length;index+=1){
    const char=text[index];
    if(quoted){
      if(char==='"'&&text[index+1]==='"'){field+='"';index+=1;}
      else if(char==='"')quoted=false;
      else field+=char;
    }else if(char==='"'&&field==='')quoted=true;
    else if(char===delimiter){row.push(field);field='';}
    else if(char==='\n'||char==='\r'){
      if(char==='\r'&&text[index+1]==='\n')index+=1;
      row.push(field);out.push(row);row=[];field='';
    }else field+=char;
  }
  if(field!==''||row.length)out.push([...row,field]);
  return out;
}

/** Entries of a file chosen in the vocabulary window: the app's own vocabulary.json, a JSON list,
 * or a table (CSV, semicolon CSV or TSV) with Hebrew, Russian and English columns in that order;
 * a first row of column names is skipped. Throws when nothing in the file looks like a vocabulary. */
export function parseVocabularyFile(raw:string):VocabularyEntry[] {
  const text=raw.replace(/^\uFEFF/,'');
  const trimmed=text.trim();
  const clean=(value:unknown)=>typeof value==='string'?value.trim():'';
  if(trimmed.startsWith('{')||trimmed.startsWith('[')){
    const value:unknown=JSON.parse(trimmed);
    const items=Array.isArray(value)?value:(value&&typeof value==='object'?(value as {entries?:unknown}).entries:null);
    if(!Array.isArray(items))throw new Error('No entries');
    const entries=items.filter(item=>item&&typeof item==='object').map(item=>{
      const record=item as Record<string,unknown>;return {he:clean(record.he),ru:clean(record.ru),en:clean(record.en)};
    }).filter(entry=>entry.he||entry.ru||entry.en);
    if(!entries.length)throw new Error('No entries');
    return entries;
  }
  const first=text.split(/\r?\n/,1)[0];
  const delimiter=first.includes('\t')?'\t':first.split(';').length>first.split(',').length?';':',';
  const table=rows(text,delimiter).map(row=>row.map(cell=>cell.trim())).filter(row=>row.some(Boolean));
  if(table.length&&HEADER.has(table[0][0].toLowerCase()))table.shift();
  const entries=table.map(([he='',ru='',en=''])=>({he,ru,en}));
  if(!entries.length)throw new Error('No entries');
  return entries;
}

/** The list as a table that Numbers and Excel open with Hebrew and Cyrillic intact (UTF-8 with a BOM). */
export function vocabularyCsv(entries:VocabularyEntry[]):string {
  const cell=(value:string)=>/[",\n\r]/.test(value)?`"${value.replace(/"/g,'""')}"`:value;
  return '\uFEFF'+['he,ru,en',...entries.map(entry=>[entry.he,entry.ru,entry.en].map(cell).join(','))].join('\r\n')+'\r\n';
}

/** Entries whose Hebrew or translations contain the query; Hebrew vowel marks are ignored. */
export function filterVocabulary(entries:VocabularyEntry[],query:string):VocabularyEntry[] {
  const plain=(value:string)=>value.normalize('NFC').replace(/[\u0591-\u05c7]/g,'').toLocaleLowerCase();
  const wanted=plain(query.trim());
  if(!wanted)return entries;
  return entries.filter(entry=>[entry.he,entry.ru,entry.en].some(value=>plain(value).includes(wanted)));
}
