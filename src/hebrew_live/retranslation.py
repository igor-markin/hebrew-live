"""Opt-in growing-audio experiment. No source-word ownership or prompt background.

Audio ranges use the segmenter's exact 16 kHz sample coordinates. Text remains
attached to the whole open range. The draft policy may replace complete visible drafts during speech.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict, replace
import hashlib
import json
from pathlib import Path
import re
import time
from types import SimpleNamespace
import numpy as np

_PROMPT_HASH = hashlib.sha256(Path(__file__).with_name('translation.py').read_bytes()).hexdigest()

def common_prefix(left, right):
    """Exact adjacent prefix, including punctuation, at word boundaries."""
    result=[]
    for old,new in zip(re.findall(r'\S+\s*',left),re.findall(r'\S+\s*',right)):
        if old.rstrip()!=new.rstrip():break
        result.append(new)
    return ''.join(result).rstrip()

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


class RetranslationProcessor:

    def __init__(self, engine, updates, log, cancel):
        self.engine, self.updates, self.log, self.cancel = engine, updates, log, cancel
        self.counter = self.export_counter = 0
        self.floor = 0
        self.mt_counter = 0
        self.catchup_inbox = None
        self.catchup_parent = None
        self.reset()

    def reset(self):
        self.audio = None
        self.last = self.settings = self.part = None
        self.source = self.draft = ''
        self.visible = None
        self.last_status = 'empty'
        self.closed = False
        self.deferred_tail = False
        self.published_job = (0, 0)

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
        self.log.event('live_publication', segment=self.sid, **value,
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
        # For an already processed draft, control alone is not new evidence.
        self.finish(reason, valid=False)
        self.reset()
        if reason == 'direction':self.floor = 0

    def process(self, f):
        if self.cancel.is_set(): return
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
                            ('asr_path','backend','translation_size','direction','language','topic')})
        return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

    def mt_event(self, name, job, **extra):
        self.log.event(name,job_id=job.id,job_version=job.version,segment=job.group,
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
        if not valid:self.mt_event('mt_discarded',job,reason='cancelled_or_stale')
        return valid

    def request_mt(self, text, closing):
        parent=self.catchup_parent
        if parent is None:self.mt_counter+=1
        job=DraftMT(parent.id if parent else self.mt_counter,parent.version+1 if parent else 1,
                    self.sid,self.settings,self.last.id,self.last.revision,text,self.start,self.end,
                    self.last.end,self.last.offset,self.fingerprint(),
                    'closing' if closing else 'refresh' if self.visible and self.visible['current']['translation'] else 'first',
                    closing,parent.first_ready_at if parent else time.monotonic(),bool(parent))
        if parent:self.mt_event('mt_superseded',parent,replacement_version=job.version)
        self.mt_event('mt_requested',job)
        return job

    def recognize(self, final, closing):
        if self.cancel.is_set():return
        self.deferred_tail = False
        e = self.engine
        began = time.monotonic()
        text = e.recognize(self.audio, 0., preliminary=not final, mode='phrases')
        self.last_status = getattr(e, 'recognition_status', None) or ('accepted' if text else 'empty')
        self.log.event('live_asr', segment=self.sid, fragment=self.last.id, revision=self.last.revision,
                       seconds=time.monotonic()-began, input_seconds=len(self.audio)/16000,
                       start=self.start/16000, end=self.end/16000, status=self.last_status,
                       final=final, closing=closing, source=text)
        if self.last_status != 'accepted' or not text.strip():
            self.last_status = self.last_status if self.last_status != 'accepted' else 'empty'
            if closing and self.catchup_parent:
                self.mt_event('mt_discarded',self.catchup_parent,reason='closing_asr_'+self.last_status)
            if closing: self.finish(closing, valid=False)
            return
        text = text.strip()
        if not self.visible or not self.visible['current']['translation']:
            self.publish(text, '')  # Source immediately; no unmatched Russian text.
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
                               queue_wait=max(0.,time.monotonic()-newer.queued_at),catchup=True)
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
        self.execute_mt(job,decision=reason)

    def execute_mt(self, job, decision):
        if not self.job_current(job):return
        text=job.source;closing=job.closing;e=self.engine
        self.mt_event('mt_started',job,decision=decision,wait_seconds=time.monotonic()-job.first_ready_at)
        e.translation_context = []
        output = ''; end_reason = None; issue = None
        began = time.monotonic()
        from .cli import repetition_loop
        for piece, end_reason in e.translate(text):
            if self.cancel.is_set():
                self.mt_event('mt_discarded',job,reason='cancelled');return
            output += piece
            if repetition_loop(output): issue = 'Повтор генерации'; break
        if end_reason == 'repetition': issue = issue or 'Повтор генерации'
        elif end_reason != 'stop': issue = issue or 'Перевод не завершён'
        if not output.strip(): issue = issue or 'Пустой перевод'
        self.log.event('live_mt', segment=self.sid, source=text, translation=output,
                       seconds=time.monotonic()-began, finish_reason=end_reason, issue=issue)
        self.mt_event('mt_finished',job,seconds=time.monotonic()-began,finish_reason=end_reason,issue=issue)
        if not self.job_current(job):return
        if issue:
            self.source = self.draft = ''  # Failed work is never cache evidence.
            if closing: self.finish(closing, valid=False)
            return
        output = output.strip()
        self.source, self.draft = text, output
        if closing:
            self.finish(closing, valid=True,job=job)
        else:
            self.publish(text, output,job=job)
