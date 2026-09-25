'use strict';
const $=id=>document.getElementById(id),cards=new Map();let following=true,generation=null,finished=false,lastSignature='';
function setText(node,value){if(node.textContent!==value)node.textContent=value;}
function direction(text){return /[א-ת]/.test(text)&&!/[А-Яа-яЁё]/.test(text)?'rtl':'ltr';}
function applyTextSize(value,keepPosition=false){
 const n=Number(value);const size=Number.isFinite(n)?Math.max(14,Math.min(28,Math.round(n))):18;
 const headerBottom=document.querySelector('header').getBoundingClientRect().bottom;
 const anchor=keepPosition?[...document.querySelectorAll('.block')].find(el=>el.getBoundingClientRect().bottom>headerBottom):null;
 const before=anchor?.getBoundingClientRect().top;
 document.documentElement.style.setProperty('--reading-size',size+'px');
 $('text-size').value=size;$('text-size-value').textContent=size;
 if(anchor){window.scrollBy(0,anchor.getBoundingClientRect().top-before);previousScroll=window.scrollY;}
 const last=[...document.querySelectorAll('.block')].at(-1);
 if(last){const target=last.querySelector('.translation');lastSignature=last.dataset.id+':'+Math.ceil(target.getBoundingClientRect().height/parseFloat(getComputedStyle(target).lineHeight));}
}
try{const saved=localStorage.getItem('hebrew-live-text-size');if(saved!==null)applyTextSize(saved);}catch{}
$('text-size').addEventListener('input',e=>{applyTextSize(e.target.value,true);try{localStorage.setItem('hebrew-live-text-size',e.target.value);}catch{}});
function groupCard(id){
 const el=document.createElement('section');el.className='group';el.dataset.id=id;
 const content=document.createElement('div');el.append(content);
 $('blocks').append(el);return {el,content,units:new Map(),finalUnit:null};
}
function unitCard(group,b){
 const el=document.createElement('article');el.className='block';el.dataset.id=b.id;
 const source=document.createElement('div');source.className='source';source.dir=b.direction==='he-ru'?'rtl':b.direction==='ru-he'?'ltr':direction(b.source);source.textContent=b.source;source.setAttribute('aria-label','Распознанная речь');
 const target=document.createElement('div');target.className='translation';
 const status=document.createElement('div');status.className='block-status';
 el.append(source,target,status);group.content.append(el);return {el,source,target,status};
}
function readingLine(){
 const top=document.querySelector('header').getBoundingClientRect().bottom;
 const bottom=innerHeight-document.querySelector('footer').offsetHeight;
 return top+Math.max(0,bottom-top)*.60;
}
function followTranslation(target,force=false){
 if(!target)return;
 const delta=target.getBoundingClientRect().bottom-readingLine();
 if(force||delta>0){window.scrollBy(0,delta);previousScroll=window.scrollY;}
}
function latestTranslation(){return [...document.querySelectorAll('.block>.translation')].at(-1);}
window.addEventListener('resize',()=>{if(following)followTranslation(latestTranslation());});
document.querySelector('details').addEventListener('toggle',()=>{if(following)followTranslation(latestTranslation());});
function render(s){
 updateTiming(s);
 updateModels(s);
 if(generation!==s.generation){$('blocks').replaceChildren();cards.clear();generation=s.generation;following=true;}
 let newest=null;let appended=false;
 for(const g of s.groups||[]){
  let c=cards.get(g.id);if(!c){c=groupCard(g.id);cards.set(g.id,c);}
  c.el.classList.toggle('complete',g.complete);
  if(g.final?.sequential&&g.final.warning&&!c.warning){c.warning=document.createElement('p');c.warning.textContent=g.final.warning;c.warning.setAttribute('role','status');c.el.append(c.warning);}
  for(const b of g.blocks){
   let u=c.units.get(b.id);if(!u){u=unitCard(c,{...b,direction:g.direction});c.units.set(b.id,u);appended=true;}
   // Never replace a published prefix, even if the server sends a stale snapshot.
   const old=u.target.textContent;if(b.translation.startsWith(old)&&b.translation!==old){
    u.target.append(document.createTextNode(b.translation.slice(old.length)));
   }
   u.target.dir=g.direction?(g.direction==='ru-he'?'rtl':'ltr'):direction(b.translation);
   setText(u.status,b.issue?'Перевод не завершён':b.complete?'':'Перевожу…');newest=u;
  }
  if(g.live?.current){
   const current=g.live.current;
   let u=c.units.get('live');
   if(!u){u=unitCard(c,{id:g.id+':live',source:current.source,direction:g.direction});c.units.set('live',u);appended=true;}
   setText(u.source,current.source||'');
   setText(u.target,current.translation||'');
   u.target.dir=g.direction==='ru-he'?'rtl':'ltr';
   setText(u.status,g.live.issue||(!current.translation?'Перевожу…':''));
   newest=u;
  }
  if((g.final||g.final_progress||g.correction)&&!(g.final||g.final_progress||g.correction).sequential){
   const final=g.final||g.final_progress||g.correction;
   if(!c.finalUnit){
    const label=document.createElement('div');label.className='label';label.textContent=final.correction_of?.length?'УТОЧНЕНИЕ РАСПОЗНАВАНИЯ':final.phrase?'':'ПОЛНЫЙ ПЕРЕВОД';c.content.append(label);
    c.finalUnit=unitCard(c,{id:g.id+':final',source:final.source,direction:g.direction});if(!final.phrase)c.finalUnit.el.classList.add('final-result');
    appended=true;
   }
   const oldFinal=c.finalUnit.target.textContent;
   if(final.translation.startsWith(oldFinal)&&final.translation!==oldFinal)c.finalUnit.target.append(document.createTextNode(final.translation.slice(oldFinal.length)));
   c.finalUnit.target.dir=g.direction?(g.direction==='ru-he'?'rtl':'ltr'):direction(final.translation);
   setText(c.finalUnit.status,final.issue?'Перевод не завершён':final.source_warning|| (final.incomplete?'Фраза продолжается':g.complete?'':'Перевожу…'));
   newest=c.finalUnit;
  }
 }
 setText($('device'),(s.input_kind||'Микрофон')+': '+(s.device||'подключается…'));
 const db=s.level>0?20*Math.log10(s.level):-60;$('level').value=Math.max(0,Math.min(60,db+60));setText($('db'),s.level>0?db.toFixed(0)+' dBFS':'— dBFS');
 const names=s.models||{};const short=v=>(v||'').split('/').pop().replace('ivrit-ai-whisper-large-v3-turbo-mlx','ivrit.ai Whisper Turbo');
 setText($('model-summary'),names['Распознавание']?short(names['Распознавание'])+' → '+short(names['Перевод'])+' · подробнее':'Модели и сессия');
 setText($('models'),Object.entries(s.models||{}).map(([k,v])=>k+': '+v).join('\n'));setText($('audio-info'),s.rate?s.rate+' Гц · '+s.channels+' канал':'');setText($('topic'),'Тема: '+(s.topic==='none'?'не задана':s.topic||'не задана'));setText($('session'),s.session||'');
 $('empty').hidden=cards.size>0;setText($('status'),s.status);setText($('direction'),s.direction==='he-ru'?'Иврит → Русский':'Русский → Иврит');setText($('pause'),s.paused?'Продолжить':'Пауза');$('pause').setAttribute('aria-pressed',String(s.paused));setText($('lag'),s.first_text_delay!=null?'Первые слова полного: '+s.first_text_delay.toFixed(1)+' с':s.lag?'После конца порции: '+s.lag.toFixed(1)+' с':'');
 setText($('stop'),s.stopping?'Отменить очередь':'Завершить');finished=s.finished;
 document.querySelectorAll('[data-action]').forEach(b=>b.disabled=finished);
 // Geometry, not token arrival, controls following. Never move history while
 // the user reads it; no smooth scrolling or scroll-to-bottom on every poll.
 if(following&&newest){
  const lines=Math.ceil(newest.target.getBoundingClientRect().height/parseFloat(getComputedStyle(newest.target).lineHeight));
  const sig=newest.el.dataset.id+':'+lines;
  if(appended||sig!==lastSignature){
   followTranslation(newest.target);
  }
  lastSignature=sig;
 }
 $('latest').hidden=following||!cards.size;setText($('connection'),finished?'Сессия завершена · текст остаётся в этой вкладке':'Все данные остаются на этом Mac');
}
async function action(name){try{const r=await fetch('action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:name})});if(!r.ok)throw Error('action');}catch{setText($('connection'),'Команда не принята · проверь терминал');}}
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>action(b.dataset.action)));
let previousScroll=window.scrollY;
window.addEventListener('scroll',()=>{if(window.scrollY<previousScroll-1)following=false;previousScroll=window.scrollY;$('latest').hidden=following||cards.size===0;},{passive:true});
window.addEventListener('wheel',e=>{if(e.deltaY<0)following=false;},{passive:true});
window.addEventListener('keydown',e=>{if(e.target.matches('input,textarea,select,[contenteditable]'))return;if(['ArrowUp','PageUp','Home'].includes(e.key))following=false;});
$('latest').onclick=()=>{following=true;$('latest').hidden=true;if(!$('session-files').hidden){$('session-files').scrollIntoView({block:'center'});previousScroll=window.scrollY;}else followTranslation(latestTranslation(),true);$('latest').hidden=true;};
window.addEventListener('keydown',e=>{if(e.repeat||e.target.matches('input,textarea,select,[contenteditable]'))return;let name=null;if(e.code==='Space'&&e.target.tagName!=='BUTTON')name='pause';if(e.altKey&&e.code==='KeyL')name='clear';if(e.altKey&&e.code==='KeyT')name='direction';if(e.key==='q'||e.key==='Q')name='stop';if(e.key==='End'){e.preventDefault();following=true;$('latest').click();}if(name&&!finished){e.preventDefault();action(name);}});
let filesPrepared=false;
async function prepareFiles(s){
 if(filesPrepared||!s.exports?.length)return;filesPrepared=true;
 const panel=$('session-files');panel.hidden=false;setText($('files-status'),'Подготавливаю ссылки…');
 try{
  for(const file of s.exports){
   const response=await fetch('export-'+file.id,{cache:'no-store'});if(!response.ok)throw Error('export');
   const blob=await response.blob();const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=file.name;a.textContent=file.label+' · '+file.name;a.className='download';$('file-links').append(a);
  }
  setText($('files-status'),'Готово. Ссылки работают, пока открыта эта вкладка. Оригиналы также сохранены в папке сессии.');
 }catch{setText($('files-status'),'Не все ссылки удалось подготовить. Файлы сохранены в папке: '+(s.session||''));}
 if(following)panel.scrollIntoView({block:'end'});
 $('latest').hidden=false;setText($('latest'),'К сохранённым файлам ↓');
 await fetch('action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'exports_ready'})}).catch(()=>{});
}
async function poll(){try{const r=await fetch('state',{cache:'no-store'});if(!r.ok)throw Error('state');const s=await r.json();render(s);if(s.finished)await prepareFiles(s);}catch{if(!finished)setText($('connection'),'Связь с программой потеряна · проверь терминал');}if(!finished)setTimeout(poll,150);}
poll();

const timingFields=[['first_seconds','Первый снимок',1,6,.5,'Накопление речи перед распознаванием'],['interval_seconds','Между обновлениями',1,8,.5,'Новая речь после предыдущего блока'],['preview_limit','Предварительных блоков',1,3,1,'В режиме последовательных блоков лимит не действует'],['fragment_seconds','Длина фрагмента',4,15,.5,'Когда готовить полный перевод'],['silence_seconds','Пауза в речи',.45,2.5,.01,'Тишина для завершения фразы']];
let timingInitialized=false,timingDefaults={first_seconds:1.5,interval_seconds:1,preview_limit:0,fragment_seconds:4,silence_seconds:.6};
for(const [key,label,min,max,step,hint] of timingFields){
 const row=document.createElement('label'),copy=document.createElement('span'),title=document.createElement('strong');title.textContent=label;
 const small=document.createElement('small');small.textContent=hint;copy.append(title,small);
 const control=document.createElement('span');control.className='timing-value';
 const input=document.createElement('input');input.type='number';input.id='timing-'+key;input.step=key==='preview_limit'?'1':'any';input.required=true;input.value=timingDefaults[key];input.disabled=true;input.setAttribute('aria-label',label);
 const unit=document.createElement('span');unit.textContent=key==='preview_limit'?'шт.':'с';
 const baseline=document.createElement('small');baseline.id='default-'+key;baseline.textContent='По умолчанию: '+timingDefaults[key];
 control.append(input,unit,baseline);row.append(copy,control);$('timing-fields').append(row);
}
function fillTiming(values){for(const [key] of timingFields)$('timing-'+key).value=values[key];}
function updateTiming(s){
 const supported=!!s.timing;
 if(supported){timingDefaults=s.timing_defaults||timingDefaults;if(!timingInitialized){fillTiming(s.timing);timingInitialized=true;}}
 else if(!timingInitialized){timingDefaults.first_seconds=1.5;fillTiming(timingDefaults);setText($('timing-status'),'Показаны исходные значения. Перезапусти приложение, чтобы менять их здесь.');}
 for(const [key] of timingFields)setText($('default-'+key),'По умолчанию: '+timingDefaults[key]);
 for(const el of $('timing-form').elements)el.disabled=!!s.finished||!supported;
 if(supported&&s.mode===undefined)setText($('timing-status'),'Перезапусти приложение для переключения режимов перевода.');
 $('timing-preview_limit').disabled=true;
 $('timing-preview_limit').closest('label').hidden=true;
 const label=$('timing-fragment_seconds').closest('label');
 const intervalLabel=$('timing-interval_seconds').closest('label');
 setText(intervalLabel.querySelector('strong'),'Интервал распознавания');
 setText(intervalLabel.querySelector('small'),'Как часто отправлять новый снимок речи в распознаватель');
 setText(label.querySelector('strong'),'Ожидание связной части');
 setText(label.querySelector('small'),'После этого возможна выдача незавершённой части. Распознавание и перевод добавляют время');
}
async function saveTiming(values){try{const r=await fetch('action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'settings',values,mode:'phrases'})});if(!r.ok)throw Error();setText($('timing-status'),'Принято: новые значения будут действовать со следующего фрагмента.');}catch{setText($('timing-status'),'Не удалось применить. Проверь значения и связь с программой.');}}
$('timing-form').addEventListener('submit',e=>{e.preventDefault();const values=Object.fromEntries(timingFields.map(([key])=>[key,Number($('timing-'+key).value)]));saveTiming(values);});
$('timing-reset').addEventListener('click',()=>{if(timingDefaults){fillTiming(timingDefaults);saveTiming(timingDefaults);}});


let modelsInitialized=false;
function updateModels(s){
 if(s.model_options&&s.model_selection&&!modelsInitialized){for(const [kind,id] of [['asr','asr-choice'],['translation','translation-choice']]){for(const [value,label] of Object.entries(s.model_options[kind]||{})){const option=document.createElement('option');option.value=value;option.textContent=label;$(id).append(option);}$(id).value=s.model_selection[kind];}modelsInitialized=true;}
 for(const id of ['model-apply','asr-choice','translation-choice'])$(id).disabled=!modelsInitialized||!!s.model_switching||!!s.finished;
 if(s.model_switching)$('pause').disabled=true;else $('pause').disabled=!!s.finished;
 if(s.model_message)setText($('model-status'),s.model_message);
}
$('model-apply').addEventListener('click',async()=>{try{$('model-apply').disabled=true;const r=await fetch('action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'models',values:{asr:$('asr-choice').value,translation:$('translation-choice').value}})});if(!r.ok)throw Error();setText($('model-status'),'Запрос принят. Завершаю речь и загружаю модели…');}catch{setText($('model-status'),'Не удалось переключить модели. Проверь состояние приложения.');}});
