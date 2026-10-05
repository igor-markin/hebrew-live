"""Opt-in growing-audio experiment. No source-word ownership or prompt background.

Audio ranges use the segmenter's exact 16 kHz sample coordinates. Text remains
attached to the whole open range. The draft policy may replace complete visible drafts during speech.
"""
from copy import deepcopy
from collections import deque
from dataclasses import dataclass, asdict, replace
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
from types import SimpleNamespace
import numpy as np

_PROMPT_HASH = hashlib.sha256(Path(__file__).with_name('translation.py').read_bytes()).hexdigest()
STREAM_PREVIEW_INTERVAL = 0.1

def common_prefix(left, right):
    """Exact adjacent prefix, including punctuation, at word boundaries."""
    result=[]
    for old,new in zip(re.findall(r'\S+\s*',left),re.findall(r'\S+\s*',right)):
        if old.rstrip()!=new.rstrip():break
        result.append(new)
    return ''.join(result).rstrip()

def streamable_prefix(value):
    """Only show complete words while an unfinished translation is growing."""
    if value.rstrip().endswith(('.', '!', '?', '…', '。', '！', '？')):
        return value.strip()
    match = re.search(r'\s+\S*$', value)
    return value[:match.start()].strip() if match else ''

@dataclass(frozen=True)
class DraftMT:
    id: int
    version: int
    group: int
    settings: object
    fragment: int
    revision: int
    source: str
    start: int
    end: int
    captured_at: float
    captured_offset: float
    fingerprint: str
    kind: str
    closing: str | None
    first_ready_at: float
    catchup_used: bool = False

@dataclass(frozen=True)
class MTResult:
    output: str
    end_reason: str | None
    issue: str | None
    seconds: float
    preview: bool


class RetranslationProcessor:

    _GROUP_FIELDS=('audio','last','settings','part','source','draft','visible',
                   'last_status','closed','deferred_tail','published_job',
                   '_mt_first_requested','_mt_closing_pending','sid','start','end')

    def __init__(self, engine, updates, log, cancel, async_mt=None):
        self.engine, self.updates, self.log, self.cancel = engine, updates, log, cancel
        self.counter = self.export_counter = 0
        self.floor = 0
        self.mt_counter = 0
        self.catchup_inbox = None
        self.catchup_parent = None
        self.text_only_draft = os.environ.get('HEBREW_LIVE_TEXT_ONLY_DRAFT','0') == '1'
        self.async_mt=bool(getattr(engine,'independent_mt',False)) if async_mt is None else async_mt
        if self.async_mt:
            self._mt_condition=threading.Condition()
            self._mt_pending=deque()
            self._mt_results=queue.Queue()
            self._mt_outstanding=0
            self._mt_active=False
            self._mt_stop=False
            self._mt_failure=None
            self._mt_latest={}
            self._mt_group_states={}
            self._mt_group_counts={}
            self._mt_worker=threading.Thread(target=self._mt_loop,name='translation',daemon=True)
            self._mt_worker.start()
        self.reset()

    def reset(self):
        if (self.async_mt and getattr(self,'last',None) is not None and
                self._mt_group_counts.get(self.sid,0)):
            self._mt_group_states[self.sid]=self._capture_group(detach=True)
        self.audio = None
        self.last = self.settings = self.part = None
        self.source = self.draft = ''
        self.visible = None
        self.last_status = 'empty'
        self.closed = False
        self.deferred_tail = False
        self.published_job = (0, 0)
        self._mt_first_requested=False
        self._mt_closing_pending=False

    def _capture_group(self, detach=False):
        state={key:getattr(self,key,None) for key in self._GROUP_FIELDS}
        if detach:
            state['audio']=None
            if state['last'] is not None:
                f=state['last']
                state['last']=SimpleNamespace(id=f.id,revision=f.revision,end=f.end,offset=f.offset)
        return state

    def _restore_group(self,state):
        for key,value in state.items():setattr(self,key,value)

    def _mt_loop(self):
        while True:
            with self._mt_condition:
                while not self._mt_pending and not self._mt_stop:
                    self._mt_condition.wait()
                if self._mt_stop:return
                job=self._mt_pending.popleft()
                self._mt_active=True
                obsolete=(job.kind=='refresh' and self._mt_latest.get(job.group)!=(job.id,job.version))
            result=None;failure=None
            try:
                if obsolete:self.mt_event('mt_skipped_superseded_refresh',job,reason='newer_mt_queued')
                elif not self.cancel.is_set():result=self._generate_mt(job,'independent_worker')
            except BaseException as exc:
                failure=exc
                self.updates.put(('live_stream_clear',job.group,{}))
            finally:
                self._mt_results.put((job,result,failure))
                with self._mt_condition:
                    if failure is not None:
                        self._mt_failure=failure
                        self._mt_stop=True
                    self._mt_active=False
                    self._mt_condition.notify_all()

    def _queue_mt(self,job):
        while True:
            self.poll_mt()
            with self._mt_condition:
                # A queued refresh has no unique speech: a newer ASR version
                # covers its entire range. First and closing jobs are retained.
                dropped=[old for old in self._mt_pending
                         if old.group==job.group and old.kind=='refresh']
                if dropped:
                    self._mt_pending=deque(old for old in self._mt_pending if old not in dropped)
                    for old in dropped:
                        self._mt_outstanding-=1
                        self._mt_group_counts[old.group]-=1
                if len(self._mt_pending)<8:
                    self._mt_pending.append(job)
                    self._mt_outstanding+=1
                    self._mt_group_counts[job.group]=self._mt_group_counts.get(job.group,0)+1
                    self._mt_latest[job.group]=(job.id,job.version)
                    self._mt_first_requested=True
                    if job.closing:
                        self._mt_closing_pending=True
                        self.floor=max(self.floor,self.end)
                    self._mt_condition.notify()
                    break
            for old in dropped:self.mt_event('mt_skipped_superseded_refresh',old,reason='newer_mt_queued')
            self.poll_mt(wait=True)
        for old in dropped:self.mt_event('mt_skipped_superseded_refresh',old,reason='newer_mt_queued')
        self.mt_event('mt_queued',job,queue_depth=self._mt_outstanding)

    def poll_mt(self,wait=False):
        if not self.async_mt:return
        while True:
            try:item=self._mt_results.get(timeout=.05) if wait else self._mt_results.get_nowait()
            except queue.Empty:return
            job,result,failure=item
            try:
                if failure:
                    if hasattr(self.log,'note_unprocessed'):
                        with self._mt_condition:pending=list(self._mt_pending)
                        with self._mt_results.mutex:
                            pending += [entry[0] for entry in self._mt_results.queue]
                        for affected in (job,*pending):
                            self.log.note_unprocessed(affected.settings.part,
                                affected.start/16000,affected.end/16000,'translation_worker_failed')
                    raise failure
                if result is not None:self._commit_mt(job,result)
            finally:
                self._mt_outstanding-=1
                count=self._mt_group_counts[job.group]-1
                if count:
                    self._mt_group_counts[job.group]=count
                else:
                    self._mt_group_counts.pop(job.group,None)
                    self._mt_group_states.pop(job.group,None)
                    self._mt_latest.pop(job.group,None)
            if wait:return

    def drain_mt(self):
        if not self.async_mt:return
        while self._mt_outstanding and not self.cancel.is_set():
            self.poll_mt(wait=True)
            if self._mt_failure is not None and self._mt_results.empty():raise self._mt_failure

    def shutdown_mt(self):
        if not self.async_mt:return
        with self._mt_condition:
            self._mt_stop=True
            self._mt_condition.notify_all()
        self._mt_worker.join(1.)

    def publish(self, source, target, stage='open', issue=None, reason=None, job=None):
        if self.cancel.is_set(): return
        if job is not None and not self.job_current(job):return
        start,end=(job.start,job.end) if job else (self.start,self.end)
        captured,offset=(job.captured_at,job.captured_offset) if job else (self.last.end,self.last.offset)
        previous = self.visible
        snapshot = dict(source=source, translation=target, fragment=job.fragment if job else self.last.id,
                        revision=job.revision if job else self.last.revision,
                        source_status='accepted' if job else self.last_status)
        if stage == 'unavailable' and previous:
            snapshot = deepcopy(previous['current'])
        history = [deepcopy(previous['current'])] if (previous and any(previous['current'][key] != snapshot[key] for key in ('source','translation'))) else []
        if previous and not history:
            history = deepcopy(previous['history'])
        value = dict(current=snapshot, history=history, stage=stage, issue=issue,
                     reason=reason, start=start/16000, end=end/16000)
        if value == previous: return
        self.visible = deepcopy(value)
        if job:self.published_job=(job.id,job.version)
        self.updates.put(('context', self.sid, self.settings))
        self.updates.put(('live_publication', self.sid, value))
        self.log.event('live_publication', part=self.settings.part,segment=self.sid, **value,
                       audio_lag=max(0., time.monotonic()-captured+offset-end/16000),
                       from_start=time.monotonic()-captured+offset-start/16000)
        if job:self.mt_event('mt_published',job,new_content=not previous or previous['current']['translation']!=target)
        # Every visible version has its own durable paired record. Group links
        # preserve revisions; original WAV writing is entirely outside this worker.
        self.export_counter += 1
        record = SimpleNamespace(id=6_000_000+self.export_counter, start=start/16000,
                                 offset=end/16000, audio=(), prefix=0.)
        label = f'[Группа {self.sid}; версия {self.export_counter}; {stage}]\n'
        if self.part:
            self.part.text('source', record, label+source)
            self.part.text('target', record, label+(target or '[Перевод ещё не показан]')+
                           ('\n['+issue+']' if issue else ''))

    def finish(self, reason, valid=False, job=None):
        if self.last is None or self.closed: return
        technical = reason in ('window', 'audio_gap', 'budget')
        if valid and self.last_status == 'accepted' and self.draft:
            self.publish(self.source, self.draft, 'technical' if technical else 'closed', reason=reason,job=job)
        else:
            current = self.visible['current'] if self.visible else {'source':'', 'translation':''}
            self.publish(current['source'], current['translation'], 'unavailable',
                         issue=('Распознан текст на другом языке; перевод пропущен' if getattr(self.engine,'recognition_issue',None)=='non-Hebrew transcript' else 'Завершённая версия недоступна; ранний текст не подтверждён'), reason=reason)
        self.floor = max(self.floor, self.end)
        self.closed = True

    def flush(self, reason='eof'):
        # Unlike an already processed draft, a deferred tail has never reached
        # ASR. Drain it at a real boundary even when no further snapshot arrives.
        if self.deferred_tail and not self.cancel.is_set():
            self.recognize(final=True, closing=reason)
        self.drain_mt()
        # For an already processed draft, control alone is not new evidence.
        self.finish(reason, valid=False)
        self.reset()
        if reason == 'direction':self.floor = 0

    def process(self, f):
        if self.cancel.is_set(): return
        self.poll_mt()
        if self.async_mt and self._mt_closing_pending:
            self.reset()
        incoming_end = round(f.offset*16000)
        incoming_start = incoming_end-len(f.audio)
        if self.settings and self.settings != f.settings:
            self.flush('settings')
        if self.closed: self.reset()
        left = max(incoming_start, self.floor)
        if incoming_end <= left: return  # Already owned acoustic overlap.
        if self.audio is not None and left > self.end:
            self.flush('audio_gap')
        data = np.asarray(f.audio, dtype=np.float32)
        if self.audio is None:
            self.counter += 1; self.sid = 3_000_000+self.counter
            self.start = left
            self.audio = data[left-incoming_start:].copy()
        elif incoming_end > self.end:
            # Existing samples are immutable; copy only genuinely new audio.
            overlap_start = max(self.start, incoming_start)
            overlap_end = min(self.end, incoming_end)
            if overlap_end > overlap_start and not np.array_equal(
                    self.audio[overlap_start-self.start:overlap_end-self.start],
                    data[overlap_start-incoming_start:overlap_end-incoming_start]):
                raise ValueError('Retranslation acoustic overlap changed')
            self.audio = np.concatenate((self.audio, data[self.end-incoming_start:]))
        self.end = self.start+len(self.audio)
        self.last, self.settings = f, f.settings
        self.part = self.log.parts[f.settings.part] if hasattr(self.log, 'parts') else None
        if hasattr(self.log, 'bind'): self.log.bind(f.settings.part)
        e = self.engine
        e.language, e.direction, e.topic = f.settings.language, f.settings.direction, f.settings.topic
        # Bound growing work. This is an explicit technical split, not a pause.
        # Keep a remainder and process it on the next real snapshot/final below.
        max_seconds=self.settings.draft_max_audio_seconds
        if getattr(e,'backend',None)=='fast':max_seconds=min(max_seconds,20.0)
        limit=round(max_seconds*16000)
        while len(self.audio) > limit:
            remainder = self.audio[limit:].copy()
            full_end = self.end
            self.audio = self.audio[:limit]
            self.end = self.start+len(self.audio)
            self.recognize(final=True, closing='budget')
            next_start = self.end
            self.reset()
            self.counter += 1; self.sid = 3_000_000+self.counter
            self.audio = remainder; self.start = next_start; self.end = full_end
            self.last, self.settings = f, f.settings
            self.part = self.log.parts[f.settings.part] if hasattr(self.log, 'parts') else None
            self.deferred_tail = True
        closing = f.reason if f.final and f.reason != 'window' else None
        if len(self.audio) == limit and not closing: closing = 'budget'
        if self.deferred_tail and not closing:
            from .tuning import DEFAULTS
            minimum=round((self.settings.timing or DEFAULTS)[0]*16000)
            if len(self.audio) < minimum:
                self.log.event('live_tail_deferred',segment=self.sid,start=self.start/16000,
                               end=self.end/16000,samples=len(self.audio),
                               minimum_samples=minimum,fragment=f.id,revision=f.revision)
                return
        self.recognize(final=f.final or bool(closing), closing=closing)

    def fingerprint(self):
        values=dict(settings=asdict(self.settings),prompt=_PROMPT_HASH,
                    engine={key:str(getattr(self.engine,key,None)) for key in
                            ('asr_path','backend','translation_size')})
        return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

    def mt_event(self, name, job, **extra):
        self.log.event(name,part=job.settings.part,job_id=job.id,job_version=job.version,segment=job.group,
                       epoch=job.settings.generation,fragment=job.fragment,revision=job.revision,
                       source_hash=hashlib.sha256(job.source.encode()).hexdigest(),
                       source_start=job.start/16000,source_end=job.end/16000,
                       captured_at=job.captured_at,captured_offset=job.captured_offset,
                       fingerprint=job.fingerprint,kind=job.kind,first_ready_at=job.first_ready_at,
                       catchup_used=job.catchup_used,**extra)

    def job_current(self, job):
        valid=(not self.cancel.is_set() and self.settings==job.settings and
               self.sid==job.group and not self.closed and self.fingerprint()==job.fingerprint and
               (job.id,job.version)>=self.published_job)
        if valid and self.async_mt and job.kind=='refresh':
            with self._mt_condition:
                valid=self._mt_latest.get(job.group)==(job.id,job.version)
        if (valid and self.async_mt and job.kind!='closing' and self.visible and
                self.visible['end']>job.end/16000+1e-6 and
                self.visible['current']['source']!=job.source):
            valid=False
        if not valid:self.mt_event('mt_discarded',job,reason='cancelled_or_stale')
        return valid

    def request_mt(self, text, closing):
        parent=self.catchup_parent
        if parent is None:self.mt_counter+=1
        job=DraftMT(parent.id if parent else self.mt_counter,parent.version+1 if parent else 1,
                    self.sid,self.settings,self.last.id,self.last.revision,text,self.start,self.end,
                    self.last.end,self.last.offset,self.fingerprint(),
                    'closing' if closing else 'refresh' if self._mt_first_requested or self.visible and self.visible['current']['translation'] else 'first',
                    closing,parent.first_ready_at if parent else time.monotonic(),bool(parent))
        if parent:self.mt_event('mt_superseded',parent,replacement_version=job.version)
        self.mt_event('mt_requested',job)
        return job

    def recognize(self, final, closing):
        if self.cancel.is_set():return
        self.deferred_tail = False
        e = self.engine
        began = time.monotonic()
        align_words = final or not self.text_only_draft or getattr(e,'backend',None) not in ('turbo','multilingual')
        text = e.recognize(self.audio, 0., preliminary=not final, mode='phrases', align_words=align_words)
        self.last_status = getattr(e, 'recognition_status', None) or ('accepted' if text else 'empty')
        self.log.event('live_asr', segment=self.sid, fragment=self.last.id, revision=self.last.revision,
                       seconds=time.monotonic()-began, input_seconds=len(self.audio)/16000,
                       start=self.start/16000, end=self.end/16000, status=self.last_status,
                       final=final, closing=closing, source=text,word_alignment=align_words)
        if self.last_status != 'accepted' or not text.strip():
            self.last_status = self.last_status if self.last_status != 'accepted' else 'empty'
            if closing and self.catchup_parent:
                self.mt_event('mt_discarded',self.catchup_parent,reason='closing_asr_'+self.last_status)
            if closing: self.finish(closing, valid=False)
            return
        text = text.strip()
        if not self.visible or (not self.visible['current']['translation'] and
                                not (self.async_mt and self._mt_outstanding)):
            self.publish(text, '')  # Keep a pending first pair stable until its translation arrives.
        job=self.request_mt(text,closing)
        if text == self.source and self.draft:
            self.log.event('live_mt_cached', segment=self.sid, source=text)
            self.mt_event('mt_cached',job,new_content=False)
            if closing: self.finish(closing, valid=True,job=job)
            return
        if (self.settings.draft_catchup_enabled and job.kind=='refresh' and
                not job.catchup_used and self.catchup_inbox is not None):
            newer,reason=self.catchup_inbox.take_draft_catchup(self.last,self.start,self.end)
            if newer is not None:
                job=replace(job,catchup_used=True)
                self.mt_event('mt_deferred_for_asr',job,asr_fragment=newer.id,asr_revision=newer.revision)
                self.log.event('asr_job_start',segment=newer.id,revision=newer.revision,
                               queue_wait=max(0.,time.monotonic()-newer.queued_at),
                               capture_age=max(0.,time.monotonic()-newer.end),catchup=True)
                self.catchup_parent=job
                try:self.process(newer)
                finally:self.catchup_parent=None
                if self.cancel.is_set():
                    self.mt_event('mt_discarded',job,reason='cancelled');return
                if self.closed or self.last_status=='accepted':return
                # A rejected preliminary does not validate the pending source.
                # Its original range and capture clock remain attached to MT.
                self.execute_mt(job,decision='catchup_asr_not_accepted')
                return
        else:
            reason='disabled' if not self.settings.draft_catchup_enabled else 'not_eligible_or_already_used'
        # Keep the first translation and every closing translation. When newer
        # audio is already queued, an intermediate refresh would only occupy
        # the single ASR/MT worker while the next spoken words wait unread.
        if (job.kind=='refresh' and not job.catchup_used and self.catchup_inbox is not None and
                self.visible is not None and job.end/16000-self.visible['end'] < 4. and
                self.catchup_inbox.newer_audio_waiting(self.last)):
            self.mt_event('mt_skipped_superseded_refresh',job,reason='newer_audio_queued')
            return
        if self.async_mt:
            self._queue_mt(job)
            return
        self.execute_mt(job,decision=reason)

    def execute_mt(self, job, decision):
        if not self.job_current(job):return
        result=self._generate_mt(job,decision)
        if result is not None:self._commit_mt(job,result)

    def _generate_mt(self,job,decision):
        text=job.source;e=self.engine
        self.mt_event('mt_started',job,decision=decision,wait_seconds=time.monotonic()-job.first_ready_at)
        if not self.async_mt:e.translation_context = []
        output = ''; end_reason = None; issue = None
        began = time.monotonic()
        last_preview_at = began-STREAM_PREVIEW_INTERVAL
        preview = ''
        first_token = False
        def clear_preview():
            if preview:self.updates.put(('live_stream_clear',job.group,{}))
        from .cli import repetition_loop
        try:
            pieces=e.translate_for(text,job.settings) if self.async_mt else e.translate(text)
            for piece, end_reason in pieces:
                if self.cancel.is_set():
                    clear_preview()
                    self.mt_event('mt_discarded',job,reason='cancelled');return None
                output += piece
                if repetition_loop(output): issue = 'Повтор генерации'; break
                now = time.monotonic()
                if piece and not first_token:
                    self.mt_event('mt_first_token',job,seconds=now-began)
                    first_token = True
                current=True
                if self.async_mt and job.kind=='refresh':
                    with self._mt_condition:
                        current=self._mt_latest.get(job.group)==(job.id,job.version)
                if current and end_reason != 'stop' and now-last_preview_at >= STREAM_PREVIEW_INTERVAL:
                    candidate = streamable_prefix(output)
                    if candidate and candidate != preview:
                        self.updates.put(('live_stream',job.group,dict(
                            source=text,translation=candidate,start=job.start/16000,end=job.end/16000,
                            preview_id=f'{job.id}:{job.version}',preview_emitted_at=now)))
                        if not preview:
                            self.mt_event('mt_first_preview',job,seconds=now-began,
                                          audio_lag=max(0.,now-job.captured_at+job.captured_offset-job.end/16000))
                        preview = candidate
                        last_preview_at = now
        except BaseException:
            clear_preview()
            raise
        if end_reason == 'repetition': issue = issue or 'Повтор генерации'
        elif end_reason != 'stop': issue = issue or 'Перевод не завершён'
        if not output.strip(): issue = issue or 'Пустой перевод'
        return MTResult(output,end_reason,issue,time.monotonic()-began,bool(preview))

    def _commit_mt(self,job,result):
        current=None
        if self.async_mt and job.group!=getattr(self,'sid',None):
            state=self._mt_group_states.get(job.group)
            if state is None:
                self.mt_event('mt_discarded',job,reason='group_not_found')
                if result.preview:self.updates.put(('live_stream_clear',job.group,{}))
                return
            current=self._capture_group()
            self._restore_group(state)
        try:
            self.log.event('live_mt',part=job.settings.part,segment=job.group,source=job.source,
                           translation=result.output,seconds=result.seconds,
                           finish_reason=result.end_reason,issue=result.issue)
            self.mt_event('mt_finished',job,seconds=result.seconds,
                          finish_reason=result.end_reason,issue=result.issue)
            if not self.job_current(job):return
            if result.issue:
                self.source = self.draft = ''  # Failed work is never cache evidence.
                if job.closing: self.finish(job.closing, valid=False)
                return
            output=result.output.strip()
            self.source, self.draft = job.source, output
            if job.closing:
                self.finish(job.closing, valid=True,job=job)
            else:
                self.publish(job.source, output,job=job)
        finally:
            # A durable publication normally replaces the preview. Clear it
            # explicitly when publication is unchanged or fails halfway through.
            if result.preview:self.updates.put(('live_stream_clear',job.group,{}))
            if current is not None:
                self._mt_group_states[job.group]=self._capture_group(detach=True)
                self._restore_group(current)
