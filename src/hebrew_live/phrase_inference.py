"""Serial ASR/translation worker for phrase mode; UI remains append-only."""
import time,re
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from .phrase_buffer import PhraseBuffer,Unit,lexical,align_words,edge_allowed

@dataclass(frozen=True)
class TranslationJob:
    unit: Unit
    sid: int
    settings: object
    anchor: object
    part: object
    ready_at: float

class PhraseProcessor:
    def __init__(self,engine,updates,log,cancel):
        self.engine=engine;self.updates=updates;self.log=log;self.cancel=cancel
        self.buffer=PhraseBuffer();self.last=None;self.settings=None;self.counter=0;self.part=None
        self.last_now=0.;self.key=None
        self.published=[]
        self.jobs=deque()
        # Benchmark opt-in only. Audio seconds and monotonic seconds stay separate.
        self.budgets=getattr(engine,'phrase_deadline_budgets',None)
        if self.budgets and not (0<self.budgets[0]<self.budgets[1]):raise ValueError('Invalid deadline budgets')
        self.clock=getattr(engine,'phrase_clock',time.monotonic)
        self.deadline_barrier=lambda:False
        self.timer_suspended=False;self.audio_origin=None;self.hypothesis=0;self.word_id=0
        self.timer_key=None;self.served=set();self.scheduled=None

    def annotate_words(self,previous):
        if not self.budgets:return
        observed=self.clock();pending=self.buffer.pending
        # Temporal one-to-one identity survives lexical revisions. Lexical
        # confirmation itself is still determined by PhraseBuffer's alignment.
        matches=align_words([dict(w,word='_') for w in previous],
                            [dict(w,word='_') for w in pending])
        for i,w in enumerate(pending):
            old=previous[matches[i]] if i in matches else None
            if old is None:
                self.word_id+=1;w['word_id']=self.word_id
                w['origin_at']=self.audio_origin+w['start']
                w['first_confirmed_at']=None;w['stable_since']=None
            else:
                w['word_id']=old['word_id']
                w['origin_at']=min(old['origin_at'],self.audio_origin+w['start'])
                w['first_confirmed_at']=old.get('first_confirmed_at')
                same=lexical(old['word'])==lexical(w['word'])
                w['stable_since']=old.get('stable_since') if same and old.get('word_stable') else None
            if w.get('word_stable'):
                if w['first_confirmed_at'] is None:w['first_confirmed_at']=observed
                if w['stable_since'] is None:w['stable_since']=observed
            else:w['stable_since']=None
        # Even a complete revision of the oldest audio must not restart its age.
        if previous and pending:
            pending[0]['origin_at']=min(pending[0]['origin_at'],previous[0]['origin_at'])
        self.hypothesis+=1
        self.log.event('phrase_hypothesis',observed_at=observed,hypothesis=self.hypothesis,
                       audio_now=self.last_now,words=deepcopy(pending))

    def next_deadline(self):
        if not self.budgets or self.timer_suspended or self.cancel.is_set() or self.deadline_barrier() or not self.buffer.pending:return None
        head=self.buffer.pending[0]
        key=(head['word_id'],self.hypothesis)
        if key!=self.timer_key:self.timer_key=key;self.served=set()
        stage=next((i for i in range(2) if i not in self.served),None)
        if stage is None:return None
        due=head['origin_at']+self.budgets[stage]
        scheduled=(key,stage,due)
        if scheduled!=self.scheduled:
            self.log.event('phrase_deadline_scheduled',word_id=head['word_id'],origin_at=head['origin_at'],
                           deadline_at=due,stage=('soft','hard')[stage])
            self.scheduled=scheduled
        return due

    def service_deadlines(self):
        while True:
            due=self.next_deadline()
            if due is None or self.clock()<due:return
            observed=self.clock();head=self.buffer.pending[0]
            origin=head['origin_at'];identity=head['word_id']
            stage=1 if observed>=origin+self.budgets[1] else 0
            due=origin+self.budgets[stage]
            self.served.update(range(stage+1))
            policy=('soft','hard')[stage]
            pause=(self.settings.timing or (1.5,1,0,4,.6))[4]
            # No elapsed wall time is passed as audio time or inferred silence.
            units=self.buffer.take(self.last_now,pause=pause,deadline_policy=policy)
            decision=self.clock()
            if units:reason=units[0].reason
            elif not head.get('word_stable'):reason='no_stable_prefix'
            else:reason='blocked_open_edge' if not any(edge_allowed(self.buffer.pending,i)
                    for i in range(2,len(self.buffer.pending)+1)) else 'insufficient_context'
            ids=[self.enqueue(unit) for unit in units]
            self.log.event('phrase_deadline_decision',word_id=identity,origin_at=origin,
                           deadline_at=due,deadline_observed_at=observed,decision_at=decision,
                           decision_reason=reason,stage=policy,units=ids,
                           service_overrun=max(0.,observed-due),hypothesis=self.hypothesis)
            # A blocked hard decision has no next deadline until new evidence.
            # A released tail keeps its own origin; reconsider it immediately if due.


    def emit(self,kind,sid,value):
        self.updates.put((kind,sid,value));self.log.event(kind,segment=sid,**value)

    def flush(self,reason='eof'):
        self.timer_suspended=True
        if self.last is not None and self.buffer.pending:
            for unit in self.buffer.take(self.last_now,force=reason):self.enqueue(unit)
        self.drain()
        self.buffer=PhraseBuffer();self.key=None;self.settings=None;self.last=None
        self.published=[]
        self.audio_origin=None;self.timer_key=None;self.served=set();self.scheduled=None
        self.timer_suspended=False

    def process(self,f,defer=False):
        if not f.final and time.monotonic()-f.end>5:
            self.log.event('phrase_snapshot_stale',segment=f.id,lag=time.monotonic()-f.end)
            return
        key=(f.settings.part,f.settings.generation,f.settings.models,f.settings.timing)
        if self.key is not None and self.key!=key:self.flush('control_flush')
        self.service_deadlines()
        self.key=key;self.last=f;self.settings=f.settings
        if self.audio_origin is None:self.audio_origin=f.end-f.offset
        self.part=self.log.parts[f.settings.part] if hasattr(self.log,'parts') else None
        if hasattr(self.log,'bind'):self.log.bind(f.settings.part)
        e=self.engine;e.language=f.settings.language;e.direction=f.settings.direction;e.topic=f.settings.topic
        e.recognition_guard_due=False
        start=time.monotonic();text=e.recognize(f.audio,0.,preliminary=not f.final,mode=f.settings.mode)
        self.log.event('asr',segment=f.id,revision=f.revision,seconds=time.monotonic()-start,chars=len(text),lag=max(0,start-f.end),input_seconds=len(f.audio)/16000,crop_seconds=0,guard_due=False)
        now=f.offset;self.last_now=now
        window_start=now-len(f.audio)/16000
        status=getattr(e,'recognition_status',None) or ('rejected' if getattr(e,'recognition_issue',None) else 'accepted' if text else 'empty')
        words=getattr(e,'recognition_words',[]) if status=='accepted' else []
        self.log.event('phrase_asr_status',segment=f.id,status=status,reason=getattr(e,'recognition_issue',None),
                       start=max(0.,window_start+f.prefix),end=now,final=f.final)
        corrections=[]
        if f.final and words:
            absolute=[dict(w,start=w['start']+window_start,end=w['end']+window_start,fragment=f.id) for w in words]
            # Revisit only units fully inside this final acoustic window. The
            # correction is a new labelled entry; never rewrite a visible unit.
            for sid,unit in self.published:
                if unit.fragments!=[f.id] or unit.start<window_start-.01 or unit.end>now-.25:continue
                revised=[w for w in absolute if unit.start-.05<(w['start']+w['end'])/2<unit.end+.05]
                if not revised or abs(revised[0]['start']-unit.start)>.25 or abs(revised[-1]['end']-unit.end)>.25:continue
                source=' '.join(w['word'].strip() for w in revised)
                if lexical(source)!=lexical(unit.source):
                    corrections.append(Unit(source,revised,'asr_revision',unit.incomplete,(sid,)))
            self.published=[(sid,u) for sid,u in self.published if f.id not in u.fragments]
        if not text and not words:
            self.log.event('phrase_asr_unavailable',segment=f.id,reason=getattr(e,'recognition_issue',None))
            if f.final and self.part:
                self.log.event('unrecognized_audio',segment=f.id,start=max(0,now-len(f.audio)/16000+f.prefix),end=now)
        previous=deepcopy(self.buffer.pending) if self.budgets else None
        self.buffer.update(words,window_start,now,f.id,f.final,status=status)
        if self.budgets and status=="accepted":self.annotate_words(previous)
        timing=f.settings.timing or (1.5,1,0,4,.6)
        force=f.reason if f.reason in ('eof','pause','direction','models','clear','resume') else None
        for unit in self.buffer.take(now,f.quiet,timing[3],timing[4],f.final,force,
                                     deadline_policy="natural" if self.budgets else None):
            if self.cancel.is_set():break
            self.enqueue(unit)
        for unit in corrections:
            if self.cancel.is_set():break
            self.enqueue(unit)
        if not text and not words and f.final and not self.buffer.pending:
            start=max(self.buffer.watermark,window_start+f.prefix,0.)
            if now>start+.1:
                missing=Unit('[Речь не распознана]',[dict(word='',start=start,end=now,fragment=f.id)],'asr_unavailable',True)
                self.enqueue(missing)
                self.buffer.watermark=now
        self.service_deadlines()
        if not defer:self.drain()

    def enqueue(self,unit):
        self.counter+=1;sid=1_000_000+self.counter
        anchor=SimpleNamespace(end=self.last.end,offset=self.last.offset)
        job=TranslationJob(deepcopy(unit),sid,self.settings,anchor,self.part,time.monotonic())
        self.jobs.append(job)
        self.log.event('unit_ready',segment=sid,start=unit.start,end=unit.end,correction_of=unit.correction_of,ready_at=job.ready_at,origin_at=unit.words[0].get('origin_at'))
        if not unit.correction_of:self.published=(self.published+[(sid,job.unit)])[-64:]
        return sid

    def translate_next(self):
        self.service_deadlines()
        if not self.jobs:return
        job=self.jobs.popleft()
        if self.cancel.is_set():return
        previous=self.last,self.settings,self.part
        self.last,self.settings,self.part=job.anchor,job.settings,job.part
        if hasattr(self.log,'bind'):self.log.bind(job.settings.part)
        e=self.engine;e.language=job.settings.language;e.direction=job.settings.direction;e.topic=job.settings.topic
        self.log.event('mt_job_start',segment=job.sid,wait=time.monotonic()-job.ready_at)
        try:self.translate(job.unit,job.sid,track=False)
        finally:
            self.last,self.settings,self.part=previous
            if self.settings is not None and hasattr(self.log,'bind'):self.log.bind(self.settings.part)
        self.service_deadlines()

    def drain(self):
        self.service_deadlines()
        while self.jobs and not self.cancel.is_set():self.translate_next()
        if self.cancel.is_set():self.jobs.clear()

    def translate(self,unit,sid=None,track=True):
        if self.cancel.is_set():return
        from .cli import repetition_loop
        if sid is None:
            self.counter+=1;sid=1_000_000+self.counter
        self.updates.put(('context',sid,self.settings))
        f=SimpleNamespace(id=sid,start=unit.start,offset=unit.end,audio=(),prefix=0.,settings=self.settings)
        intervals=[dict(start=w['start'],end=w['end'],fragment=w['fragment']) for w in unit.words]
        self.log.event('phrase_unit',segment=sid,source=unit.source,start=unit.start,end=unit.end,fragments=unit.fragments,intervals=intervals,reason=unit.reason,incomplete=unit.incomplete,correction_of=unit.correction_of,unconfirmed=unit.unconfirmed)
        label=('Уточнение фрагмента '+', '.join(map(str,unit.correction_of))+':\n') if unit.correction_of else ''
        source_warning='Часть оригинала не подтверждена повторным распознаванием' if unit.unconfirmed else None
        if source_warning:label+='['+source_warning+']\n'
        if self.part:self.part.text('source',f,label+unit.source)
        e=self.engine;e.translation_context=[]
        output='';published='';reason=None;started=time.monotonic();issue=None;first_visible=False
        def payload(text):
            return dict(source=unit.source,translation=text,phrase=True,incomplete=unit.incomplete,correction_of=unit.correction_of,source_warning=source_warning)
        def mark_first():
            nonlocal first_visible
            if not first_visible:
                self.log.event('phrase_first_visible',segment=sid,seconds=time.monotonic()-started,audio_lag=time.monotonic()-self.last.end+self.last.offset-unit.end,from_start=time.monotonic()-self.last.end+self.last.offset-unit.start,correction=bool(unit.correction_of))
                first_visible=True
        try:
            if unit.reason=='asr_unavailable':
                issue='Речь не распознана';return
            self.emit('group_progress',sid,dict(payload(''),first_delay=None))
            self.log.event('phrase_source_visible',segment=sid,from_start=time.monotonic()-self.last.end+self.last.offset-unit.start,audio_lag=time.monotonic()-self.last.end+self.last.offset-unit.end,correction=bool(unit.correction_of))
            for piece,reason in e.translate(unit.source):
                if self.cancel.is_set():issue='Отменено';break
                output+=piece
                if repetition_loop(output):issue='Повтор генерации';break
                match=re.search(r'\s+\S*$',output)
                candidate=output[:match.start()].rstrip() if match else ''
                if candidate.startswith(published) and candidate!=published:
                    self.emit('group_progress',sid,dict(payload(candidate),first_delay=time.monotonic()-self.last.end+self.last.offset-unit.start if not published else None))
                    mark_first()
                    published=candidate
            if reason=='length':issue='Достигнут лимит перевода'
        except Exception as exc:
            issue='Ошибка перевода: '+str(exc)
            raise
        finally:
            if not issue and output.strip().startswith(published):published=output.strip()
            result=published or ('['+issue+']' if issue else '[Перевод отсутствует]')
            if self.part:self.part.text('target',f,label+result+(('\n['+issue+']') if issue and published else ''))
            if published:mark_first()
            self.emit('group_final',sid,dict(payload(result),issue=issue))
            self.log.event('phrase_terminal',segment=sid,start=unit.start,end=unit.end,
                           outcome='failed' if issue else 'published',issue=issue)
            self.log.event('translation',segment=sid,seconds=time.monotonic()-started,chars=len(result),lag=time.monotonic()-self.last.end+self.last.offset-unit.end,peak_memory=e.mx.get_peak_memory() if hasattr(e,'mx') else 0)
            self.updates.put(('lag',sid,time.monotonic()-self.last.end+self.last.offset-unit.end))
            if track and not unit.correction_of:self.published=(self.published+[(sid,unit)])[-64:]
