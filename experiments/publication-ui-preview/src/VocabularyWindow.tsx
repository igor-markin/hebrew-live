import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import type {FormEvent,KeyboardEvent} from 'react';
import {translator} from './i18n';
import type {TextKey,UiLocale} from './i18n';
import {initialDark,parseVocabulary,shortHebrew} from './liveState';
import type {VocabularyEntry,VocabularyList} from './liveState';
import {filterVocabulary,parseVocabularyFile,vocabularyCsv} from './vocabularyFile';
import './vocabulary.css';

const timeoutSignal=()=>AbortSignal.timeout(6000);
const emptyEntry:VocabularyEntry={he:'',ru:'',en:''};
const FIELDS:[keyof VocabularyEntry,TextKey][]=[['he','vocabularyHebrew'],['ru','vocabularyRussian'],['en','vocabularyEnglish']];

function storedLocale():UiLocale {
  const lang=document.documentElement.lang;
  return lang==='ru'||lang==='he'?lang:'en';
}

/** The owner's vocabulary in a window of its own: the whole list as a table with search, editing
 * in the row, and loading and saving the list as a file. The engine re-reads the file, so changes
 * apply from the next phrase. */
export default function VocabularyWindow() {
  const [locale,setLocale]=useState<UiLocale>(storedLocale);
  const tx=useMemo(()=>translator(locale),[locale]);
  const [list,setList]=useState<VocabularyList|null>(null);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [busy,setBusy]=useState(false);
  const [query,setQuery]=useState('');
  const [form,setForm]=useState<VocabularyEntry>(emptyEntry);
  const [editing,setEditing]=useState<{previous:string;value:VocabularyEntry}|null>(null);
  const fileInput=useRef<HTMLInputElement>(null);
  const editingRef=useRef(editing);editingRef.current=editing;

  useEffect(()=>{
    const theme=()=>{document.documentElement.dataset.theme=localStorage.getItem('hebrew-live-theme')==='dark'?'dark':'light';};
    // The server's saved theme comes first; a later switch in the live window arrives as `storage`.
    document.documentElement.dataset.theme=initialDark(document.documentElement.dataset.theme,localStorage.getItem('hebrew-live-theme'))?'dark':'light';
    window.addEventListener('storage',theme);
    void (async()=>{
      try{
        const response=await fetch('../state',{signal:timeoutSignal()});
        const value=(await response.json() as {ui_locale?:unknown}).ui_locale;
        if(value==='en'||value==='ru'||value==='he')setLocale(value);
      }catch{/* the window stays in the language it opened with */}
    })();
    return ()=>window.removeEventListener('storage',theme);
  },[]);
  useEffect(()=>{
    document.documentElement.lang=locale;document.documentElement.dir=locale==='he'?'rtl':'ltr';
    document.title=`${tx('vocabulary')} · Hebrew Live`;
  },[locale,tx]);

  const load=useCallback(async()=>{
    try{
      const response=await fetch('../vocabulary',{signal:timeoutSignal()});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      setList(parseVocabulary(await response.json()));setError('');
    }catch{setError(tx('vocabularyLoadError'));}
  },[tx]);
  useEffect(()=>{
    void load();
    // the list may change in the file or in another window: read it again when this one comes forward
    const again=()=>{if(document.visibilityState==='visible'&&!editingRef.current)void load();};
    window.addEventListener('focus',again);document.addEventListener('visibilitychange',again);
    return ()=>{window.removeEventListener('focus',again);document.removeEventListener('visibilitychange',again);};
  },[load]);

  const failure=(code:unknown)=>{
    const keys:Record<string,TextKey>={empty_hebrew:'vocabularyEmptyHebrew',not_hebrew:'vocabularyNotHebrew',no_translation:'vocabularyNoTranslation',
      too_long:'vocabularyTooLong',too_many:'vocabularyTooMany',damaged:'vocabularyDamaged'};
    return tx(keys[String(code)]||'vocabularyError',{limit:list?.limit??500});
  };
  const send=async(body:object)=>{
    setBusy(true);setError('');setNotice('');
    try{
      const response=await fetch('../action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(20000)});
      const data:unknown=await response.json().catch(()=>({}));
      if(!response.ok){
        const {error:code,index}=data as {error?:unknown;index?:unknown};
        setError(typeof index==='number'?tx('vocabularyImportBad',{row:index+1,reason:failure(code)}):failure(code));
        return null;
      }
      const next=parseVocabulary(data);setList(next);return next;
    }catch{setError(tx('vocabularyError'));return null;}
    finally{setBusy(false);}
  };
  const checked=(value:VocabularyEntry)=>{
    if(!value.he.trim()){setError(tx('vocabularyEmptyHebrew'));return false;}
    if(!value.ru.trim()&&!value.en.trim()){setError(tx('vocabularyNoTranslation'));return false;}
    return true;
  };
  const add=async(event:FormEvent)=>{
    event.preventDefault();
    if(checked(form)&&await send({action:'vocabulary_set',value:form}))setForm(emptyEntry);
  };
  const save=async()=>{
    if(!editing||!checked(editing.value))return;
    if(await send({action:'vocabulary_set',value:editing.value,previous:editing.previous}))setEditing(null);
  };
  const remove=(he:string)=>{if(window.confirm(tx('vocabularyDeleteConfirm',{word:he})))void send({action:'vocabulary_delete',he});};
  const rowKeys=(event:KeyboardEvent)=>{
    if(event.key==='Enter'){event.preventDefault();void save();}
    if(event.key==='Escape'){event.preventDefault();setEditing(null);setError('');}
  };
  const chooseFile=async(file:File|undefined)=>{
    if(fileInput.current)fileInput.current.value='';
    if(!file)return;
    let entries:VocabularyEntry[];
    try{entries=parseVocabularyFile(await file.text());}catch{setError(tx('vocabularyImportUnreadable'));return;}
    if(!window.confirm(tx('vocabularyImportConfirm',{count:entries.length,file:file.name})))return;
    const next=await send({action:'vocabulary_import',entries});
    if(next)setNotice(tx('vocabularyImported',{count:next.entries.length}));
  };
  const exportFile=()=>{
    if(!list)return;
    const link=document.createElement('a');
    link.href=URL.createObjectURL(new Blob([vocabularyCsv(list.entries)],{type:'text/csv;charset=utf-8'}));
    link.download=`hebrew-live-vocabulary-${new Date().toISOString().slice(0,10)}.csv`;
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(link.href),10000);
  };

  const blocked=busy||!list||list.damaged;
  const shown=list?filterVocabulary(list.entries,query):[];
  const position=new Map(list?.entries.map((entry,index)=>[entry.he,index+1]));
  const input=(key:keyof VocabularyEntry,value:VocabularyEntry,change:(next:VocabularyEntry)=>void,label:TextKey,onKeyDown?:(event:KeyboardEvent)=>void)=>
    <input value={value[key]} dir={key==='he'?'rtl':'auto'} lang={key} aria-label={tx(label)} placeholder={tx(label)} maxLength={list?.lengths[key]??120}
      disabled={busy} onKeyDown={onKeyDown} onChange={event=>change({...value,[key]:event.target.value})}/>;

  return <main className="vocab-window">
    <header className="vocab-header">
      <h1>{tx('vocabulary')}</h1>
      {list&&<span className="vocab-count">{tx('vocabularyCount',{count:list.entries.length,limit:list.limit})}</span>}
      <input className="vocab-search" type="search" value={query} placeholder={tx('vocabularySearch')} aria-label={tx('vocabularySearch')} onChange={event=>setQuery(event.target.value)}/>
      <button type="button" disabled={blocked} onClick={()=>fileInput.current?.click()}>{tx('vocabularyImport')}</button>
      <button type="button" disabled={!list||!list.entries.length} onClick={exportFile}>{tx('vocabularyExport')}</button>
      <input ref={fileInput} type="file" hidden accept=".csv,.tsv,.txt,.json,text/csv,text/tab-separated-values,application/json" onChange={event=>void chooseFile(event.target.files?.[0])}/>
    </header>
    <div className="vocab-notes">
      <p>{tx('vocabularyHint')} {tx('vocabularyOrder')}</p>
      <p className={shortHebrew(form.he)||(editing&&shortHebrew(editing.value.he))?'vocab-warn':''}>{tx('vocabularyShort')}</p>
      {list&&!list.enabled&&<p className="vocab-warn">{tx('vocabularyOff')}</p>}
      {list?.damaged&&<p className="vocab-error" role="alert">{tx('vocabularyDamaged')}</p>}
      {error&&<p className="vocab-error" role="alert">{error}</p>}
      {notice&&<p className="vocab-notice" role="status">{notice}</p>}
    </div>
    <form className="vocab-add" onSubmit={event=>void add(event)}>
      {FIELDS.map(([key,label])=><label key={key}>{input(key,form,setForm,label)}</label>)}
      <button type="submit" className="vocab-primary" disabled={blocked}>{tx('vocabularyAdd')}</button>
    </form>
    <div className="vocab-table-wrap">
      {!list?(!error&&<p className="vocab-empty">{tx('vocabularyLoading')}</p>):!list.entries.length?<p className="vocab-empty">{tx('vocabularyEmpty')}</p>:<>
        {query.trim()&&<p className="vocab-found">{shown.length?tx('vocabularyFound',{count:shown.length}):tx('vocabularyNothingFound')}</p>}
        <table className="vocab-table">
          <thead><tr><th className="vocab-number">№</th>{FIELDS.map(([key,label])=><th key={key}>{tx(label)}</th>)}<th className="vocab-actions"><span className="vocab-hidden">{tx('vocabularyActions')}</span></th></tr></thead>
          <tbody>{shown.map(entry=>{
            const open=editing?.previous===entry.he;
            return <tr key={entry.he} className={open?'vocab-editing':''}>
              <td className="vocab-number">{position.get(entry.he)}</td>
              {FIELDS.map(([key,label])=><td key={key} lang={key} dir={key==='he'?'rtl':'auto'}>
                {open&&editing?input(key,editing.value,value=>setEditing({previous:entry.he,value}),label,rowKeys):entry[key]}</td>)}
              <td className="vocab-actions">{open?<>
                <button type="button" className="vocab-primary" disabled={busy} onClick={()=>void save()}>{tx('vocabularySave')}</button>
                <button type="button" disabled={busy} onClick={()=>{setEditing(null);setError('');}}>{tx('vocabularyCancel')}</button>
              </>:<>
                <button type="button" disabled={blocked} onClick={()=>{setEditing({previous:entry.he,value:entry});setError('');setNotice('');}}>{tx('vocabularyEdit')}</button>
                <button type="button" disabled={blocked} onClick={()=>remove(entry.he)}>{tx('vocabularyDelete')}</button>
              </>}</td>
            </tr>;})}</tbody>
        </table>
      </>}
    </div>
  </main>;
}
