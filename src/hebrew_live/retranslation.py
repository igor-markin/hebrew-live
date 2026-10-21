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
TRUNCATION_MARKER = ' […]'
# Closing translations end a phrase, first ones put the earliest text on screen, and a
# refresh only re-covers audio that a newer ASR version will cover again.
MT_PRIORITY = {'closing': 0, 'first': 1, 'refresh': 2}
# A refresh is never interrupted once the visible text lags this far behind its audio.
INTERRUPT_LAG_LIMIT = 4.
# Continuous speech has no pause to close a group, so every snapshot re-recognised and
# re-translated the whole growing paragraph. A sentence end that two snapshots in a row
# agree on, with speech already after it, closes the group there instead.
SENTENCE_SPLIT_MIN_SECONDS = 3.
SENTENCE_MIN_WORDS = 3
SENTENCE_END = re.compile(r'[.?!…](?=\s+\S)')
# Sentence freezing with context (HEBREW_LIVE_SENTENCE_CONTEXT). A sentence decoded from its
# own short window loses the words at its edges ("הקישו אחת" became "הקישוחת"), so every
# decode also hears the audio before it in the same speaker turn, and a closing decode the
# first moments after it; only the words inside the sentence are kept.
CONTEXT_SNAPSHOT_SECONDS = 8.
CONTEXT_CLOSING_SECONDS = 15.
CONTEXT_RIGHT_SECONDS = 1.5
CONTEXT_WINDOW_SECONDS = 28.  # Whisper hears 30 s at most
MT_CONTEXT_SENTENCES = 2
MT_CONTEXT_CHARS = 400
# A technical cut looks this far back for a pause between words, never inside a number.
TECHNICAL_CUT_SEARCH_SECONDS = 6.
NUMBER_WORDS = frozenset('''אפס אחת אחד שתיים שתים שניים שנים שתי שני שלוש שלושה שלושת ארבע ארבעה
ארבעת חמש חמישה חמשת שש שישה ששת שבע שבעה שבעת שמונה שמונת תשע תשעה תשעת עשר עשרה עשרים
שלושים ארבעים חמישים שישים שבעים שמונים תשעים מאה מאות אלף אלפים כוכבית סולמית'''.split())


def number_word(word):
    bare = word.strip().strip('.,?!…"\'()-')
    return any(c.isdigit() for c in bare) or bare in NUMBER_WORDS or bare[1:] in NUMBER_WORDS and bare[:1] in 'וה'


def technical_cut(words, audio, limit):
    """Sample at which to close a group that reached `limit` samples: the best pause
    between two words of the last snapshot in the final seconds before the limit, a
    sentence end first, never between two parts of a number; failing that the quietest
    moment there; failing that the limit itself."""
    low = limit-round(TECHNICAL_CUT_SEARCH_SECONDS*16000)
    best = None
    for left, right in zip(words, words[1:]):
        cut = round((left['end']+right['start'])/2*16000)
        if not low <= cut <= limit or number_word(left['word']) and number_word(right['word']):
            continue
        mark = left['word'].strip()[-1:]
        score = (3 if mark in '.?!…' else 1 if mark in ',;:' else 0)+4*max(0., right['start']-left['end'])
        if best is None or score >= best[0]:
            best = (score, cut)
    if best is not None:
        return best[1]
    if words:
        return limit  # Words cover the window, but every gap there splits a number.
    frame = 1600
    if limit-low < frame*2 or len(audio) < limit:
        return limit
    rms = np.sqrt(np.convolve(np.square(audio[low:limit]), np.ones(frame)/frame, 'valid'))
    if not len(rms) or rms.min() >= .3*rms.mean():
        return limit
    return low+int(np.argmin(rms))+frame//2


def stable_sentence_end(previous, text):
    """Length of the longest prefix of `text` that ends a sentence, is followed by more
    words, and is unchanged since `previous`; 0 when there is none."""
    stable = len(common_prefix(previous, text))
    ends = [m.end() for m in SENTENCE_END.finditer(text) if m.end() <= stable]
    if not ends or len(text[:ends[-1]].split()) < SENTENCE_MIN_WORDS:
        return 0
    return ends[-1]


def word_boundary_sample(words, length, total):
    """Sample between the word that completes the first `length` characters of the
    joined word text and the next word; None when the words do not cover it."""
    joined = ''
    for index, word in enumerate(words):
        joined += word['word']
        if len(joined.strip()) >= length:
            if index + 1 >= len(words):
                return None
            cut = round((word['end'] + words[index + 1]['start']) / 2 * 16000)
            return cut if 0 < cut < total else None
    return None


def hold_last_word(text):
    """Drop the possibly cut last word of an unfinished snapshot; keep a lone word and a
    word that ends a sentence."""
    words = text.split()
    if len(words) < 2 or words[-1].endswith(('.', '!', '?', '…')):
        return text
    return ' '.join(words[:-1])


def next_mt_job(pending, prioritize=True):
    """Pop the next job: first of each group is eligible (per-group order is kept),
    lowest priority number wins, ties go to the oldest. Returns (job, jumped_over)."""
    if not prioritize:
        return pending.popleft(), 0
    heads = []
    seen = set()
    for job in pending:
        if job.group not in seen:
            seen.add(job.group)
            heads.append(job)
    best = min(heads, key=lambda job: MT_PRIORITY.get(job.kind, 2))
    jumped = list(pending).index(best)
    pending.remove(best)
    return best, jumped

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
    hint: str = ''
    context: tuple = ()

@dataclass(frozen=True)
class MTResult:
    output: str
    end_reason: str | None
    issue: str | None
    seconds: float
    preview: bool
    truncated: bool = False


class RetranslationProcessor:

    _GROUP_FIELDS=('audio','last','settings','part','source','draft','visible',
                   'last_status','closed','deferred_tail','published_job',
                   '_mt_first_requested','_mt_closing_pending','sid','start','end',
                   'previous_text','previous_words')

    def __init__(self, engine, updates, log, cancel, async_mt=None):
        self.engine, self.updates, self.log, self.cancel = engine, updates, log, cancel
        self.counter = self.export_counter = 0
        self.floor = 0
        self.mt_counter = 0
        self.catchup_inbox = None
        self.catchup_parent = None
        # Word times are unused by the draft path (text only), so skip alignment unless
        # HEBREW_LIVE_TEXT_ONLY_DRAFT=0 restores it.
        self.text_only_draft = os.environ.get('HEBREW_LIVE_TEXT_ONLY_DRAFT','1') != '0'
        self.async_mt=bool(getattr(engine,'independent_mt',False)) if async_mt is None else async_mt
        self.interruptible=os.environ.get('HEBREW_LIVE_MT_INTERRUPT','1')!='0'
        # The last word of a growing snapshot is cut by the window edge more often than
        # any other (plan 3.3). Off until measured on the corpus.
        self.hold_last_word=os.environ.get('HEBREW_LIVE_HOLD_LAST_WORD','0')=='1'
        # Closing groups at sentence ends; off by default until measured against main.
        self.sentence_split=os.environ.get('HEBREW_LIVE_SENTENCE_SPLIT','0')=='1'
        # Sentence freezing with context (also under the ticker view); turns sentence splits on. Off by default.
        self.sentence_context=os.environ.get('HEBREW_LIVE_SENTENCE_CONTEXT','0')=='1' or os.environ.get('HEBREW_LIVE_TICKER','0')=='1'
        self.sentence_split=self.sentence_split or self.sentence_context
        # Closed groups of the current speaker turn: audio and text for the context of
        # the next sentence. A pause or a settings change starts a new turn.
        self.turn=deque()
        self.turn_continues=False
        self.right_context=None
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
        self.previous_text=''
        self.previous_words=[]
        self.split_at=None
        self.split_text=''

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
                job,jumped=next_mt_job(self._mt_pending,self.interruptible)
                self._mt_active=True
                obsolete=(job.kind=='refresh' and self._mt_latest.get(job.group)!=(job.id,job.version))
            if jumped:self.mt_event('mt_prioritized',job,jumped_over=jumped)
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
            for item in self.turn:
                if item['group'] == self.sid and not self.draft.endswith(TRUNCATION_MARKER):
                    item['source'], item['translation'] = self.source, self.draft
        else:
            current = self.visible['current'] if self.visible else {'source':'', 'translation':''}
            recognition_issue = getattr(self.engine,'recognition_issue',None)
            if recognition_issue == 'non-Hebrew transcript':
                issue = 'Распознан текст на другом языке; перевод пропущен'
            elif self.visible is None and self.last_status in ('empty', 'rejected'):
                # No early text was ever shown, so nothing is "unconfirmed": the speech itself is missing.
                issue = 'Речь не распознана'
                if (recognition_issue not in ('repeated recognition', 'early repeated recognition')
                        and not self.cancel.is_set()):
                    self.log.event('unrecognized_audio', segment=self.sid, start=self.start/16000, end=self.end/16000)
            else:
                issue = 'Завершённая версия недоступна; ранний текст не подтверждён'
            self.publish(current['source'], current['translation'], 'unavailable', issue=issue, reason=reason)
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
        self.turn.clear();self.turn_continues = False
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
            if not self.turn_continues or self.turn and self.turn[-1]['end'] != left:
                self.turn.clear()
            self.turn_continues = False
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
            cut = technical_cut(self.previous_words, self.audio, limit) if self.sentence_context else limit
            if cut != limit:
                self.log.event('live_technical_cut', segment=self.sid, limit=(self.start+limit)/16000,
                               cut=(self.start+cut)/16000)
            self.split_group(cut, 'budget', f)
        closing = f.reason if f.final and f.reason != 'window' else None
        if closing:self.turn_continues = False  # a pause ends the speaker turn
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
        if self.split_at is not None and not self.cancel.is_set():
            cut, self.split_at = self.split_at, None
            self.log.event('live_sentence_split',segment=self.sid,start=self.start/16000,
                           cut=(self.start+cut)/16000,end=self.end/16000)
            self.split_group(cut, 'sentence', f)

    def split_group(self, cut, closing, f):
        """Close the group at sample `cut`; the rest becomes a new group that waits for
        the next snapshot."""
        remainder = self.audio[cut:].copy()
        full_end = self.end
        self.audio = self.audio[:cut]
        self.end = self.start+len(self.audio)
        text, self.split_text = self.split_text, ''
        if self.sentence_context:
            self.turn.append(dict(group=self.sid, start=self.start, end=self.end, audio=self.audio.copy(),
                                  source='', translation=''))
            while sum(len(item['audio']) for item in list(self.turn)[1:]) > CONTEXT_WINDOW_SECONDS*16000:
                self.turn.popleft()
            self.right_context = remainder[:round(CONTEXT_RIGHT_SECONDS*16000)]
            try:self.recognize(final=True, closing=closing, fallback=text)
            finally:self.right_context = None
        elif closing == 'sentence' and text:
            # Two snapshots already agree on this sentence: decoding its audio again
            # only changed words the reader had seen.
            self.log.event('live_asr', segment=self.sid, fragment=self.last.id, revision=self.last.revision,
                           seconds=0., input_seconds=len(self.audio)/16000, start=self.start/16000,
                           end=self.end/16000, status='accepted', final=True, closing=closing,
                           source=text, word_alignment=False, reused=True)
            self.last_status = 'accepted'
            self.translate(text, True, closing)
        else:
            self.recognize(final=True, closing=closing)
        next_start = self.end
        self.reset()
        self.counter += 1; self.sid = 3_000_000+self.counter
        self.audio = remainder; self.start = next_start; self.end = full_end
        self.last, self.settings = f, f.settings
        self.part = self.log.parts[f.settings.part] if hasattr(self.log, 'parts') else None
        self.deferred_tail = True
        self.turn_continues = self.sentence_context

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
                    closing,parent.first_ready_at if parent else time.monotonic(),bool(parent),
                    self.draft,self.mt_context())
        if parent:self.mt_event('mt_superseded',parent,replacement_version=job.version)
        self.mt_event('mt_requested',job)
        return job

    def context_audio(self, seconds):
        """The turn's audio just before this group, at most `seconds` long."""
        pieces = []
        wanted = round(seconds*16000)
        edge = self.start
        for item in reversed(self.turn):
            if item['group'] == self.sid:continue  # the sentence being closed
            if wanted <= 0 or item['end'] != edge:break
            piece = item['audio'][-wanted:]
            pieces.append(piece);wanted -= len(piece);edge = item['start']
        return np.concatenate(pieces[::-1]) if pieces else np.empty(0, dtype=np.float32)

    def mt_context(self):
        """(source, translation) of the last closed sentences right before this group."""
        if not self.sentence_context:return ()
        pairs = []
        edge = self.start
        for item in reversed(self.turn):
            if item['group'] == self.sid:continue
            if (len(pairs) >= MT_CONTEXT_SENTENCES or item['end'] != edge or not item['translation'] or
                    sum(len(source) for source, _ in pairs)+len(item['source']) > MT_CONTEXT_CHARS):
                break
            pairs.append((item['source'], item['translation']));edge = item['start']
        return tuple(pairs[::-1])

    def _decode(self, final, align_words):
        """Recognise the group; with sentence context, inside a window that also holds the
        turn's preceding audio and, for a closing decode, the audio right after the group."""
        e = self.engine
        left = (self.context_audio(min(CONTEXT_CLOSING_SECONDS if final else CONTEXT_SNAPSHOT_SECONDS,
                                       CONTEXT_WINDOW_SECONDS-len(self.audio)/16000-CONTEXT_RIGHT_SECONDS))
                if self.sentence_context else ())
        right = self.right_context if self.sentence_context and self.right_context is not None else ()
        if not len(left) and not len(right):
            return e.recognize(self.audio, 0., preliminary=not final, mode='phrases', align_words=align_words), 0
        prefix = len(left)/16000
        options = dict(until=prefix+len(self.audio)/16000) if len(right) else {}
        window = np.concatenate((left, self.audio, right)).astype(np.float32)
        text = e.recognize(window, prefix, preliminary=not final, mode='phrases', align_words=True, **options)
        words = getattr(e, 'recognition_words', None) or []
        if words:
            e.recognition_words = [dict(w, start=w['start']-prefix, end=w['end']-prefix) for w in words]
        return text, len(window)-len(self.audio)

    def recognize(self, final, closing, fallback=''):
        if self.cancel.is_set():return
        self.deferred_tail = False
        e = self.engine
        began = time.monotonic()
        align_words = not self.text_only_draft or getattr(e,'backend',None) not in ('turbo','multilingual')
        # Word times locate a sentence end in the audio; only growing groups need them.
        splittable = self.sentence_split and not final and not closing and len(self.audio) >= SENTENCE_SPLIT_MIN_SECONDS*16000
        align_words = align_words or splittable
        text, context_samples = self._decode(final, align_words)
        self.last_status = getattr(e, 'recognition_status', None) or ('accepted' if text else 'empty')
        reused = False
        if fallback and (self.last_status != 'accepted' or not text.strip()):
            # The context decode lost a sentence two snapshots agreed on: keep their text.
            text, self.last_status, reused = fallback, 'accepted', True
        self.log.event('live_asr', segment=self.sid, fragment=self.last.id, revision=self.last.revision,
                       seconds=time.monotonic()-began, input_seconds=(len(self.audio)+context_samples)/16000,
                       context_seconds=context_samples/16000,
                       start=self.start/16000, end=self.end/16000, status=self.last_status,
                       final=final, closing=closing, source=text,word_alignment=align_words,
                       **(dict(reused=True) if reused else {}))
        if self.last_status != 'accepted' or not text.strip():
            self.last_status = self.last_status if self.last_status != 'accepted' else 'empty'
            if closing and self.catchup_parent:
                self.mt_event('mt_discarded',self.catchup_parent,reason='closing_asr_'+self.last_status)
            if closing: self.finish(closing, valid=False)
            return
        text = text.strip()
        if splittable:
            previous, self.previous_text = self.previous_text, text
            previous_words = self.previous_words
            words = getattr(e,'recognition_words',None) or []
            if words:self.previous_words = words
            if getattr(e,'recognition_issue',None) == 'early repeated recognition':
                # Text cut before a loop has no word times, and the same audio tends to
                # loop again. Close the group after as many words of the last timed
                # snapshot, when that snapshot ends the same word there.
                count = len(text.split())
                bare = lambda value: value.strip().strip('.,?!…"\'')
                same = (len(previous_words) > count and
                        bare(previous_words[count-1]['word']) == bare(text.split()[-1]))
                words = previous_words
                length = len(''.join(w['word'] for w in words[:count]).strip()) if same else 0
                sentence = text
            else:
                length = stable_sentence_end(previous, text)
                sentence = text[:length].strip()
            cut = word_boundary_sample(words, length, len(self.audio)) if length else None
            if cut is not None and cut >= round(SENTENCE_MIN_WORDS*.3*16000):
                # process() closes the group at the cut with this sentence's text.
                self.split_at, self.split_text = cut, sentence
                return
        self.translate(text, final, closing)

    def translate(self, text, final, closing):
        if self.hold_last_word and not final:
            text = hold_last_word(text)
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

    def _stale_refresh_reason(self,job):
        """Why an in-flight refresh no longer needs to finish, or None."""
        if job.kind!='refresh' or not self.interruptible:return None
        if self.async_mt:
            with self._mt_condition:
                return 'newer_mt_queued' if self._mt_latest.get(job.group)!=(job.id,job.version) else None
        # Same test as the pre-start skip in recognize(): newer audio is waiting and the
        # visible text is not already far behind, so a fresh ASR pass is worth more.
        if (not job.catchup_used and self.catchup_inbox is not None and self.visible is not None and
                job.end/16000-self.visible['end']<INTERRUPT_LAG_LIMIT and
                self.catchup_inbox.newer_audio_waiting(self.last)):
            return 'newer_audio_queued'
        return None

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
        from .cli import translation_loop
        pieces=None
        try:
            # The group's last committed translation drafts the new one (speculative
            # decoding); engines that do not know hints are called as before.
            options={'hint':job.hint} if job.hint and getattr(e,'accepts_hint',False) else {}
            if job.context and getattr(e,'accepts_context',False):options['context']=job.context
            pieces=e.translate_for(text,job.settings,**options) if self.async_mt else e.translate(text,**options)
            for piece, end_reason in pieces:
                if self.cancel.is_set():
                    clear_preview()
                    self.mt_event('mt_discarded',job,reason='cancelled');return None
                stale=self._stale_refresh_reason(job)
                if stale:
                    clear_preview()
                    self.mt_event('mt_interrupted',job,reason=stale,seconds=time.monotonic()-began,
                                  output_chars=len(output))
                    self.mt_event('mt_discarded',job,reason='superseded_while_generating');return None
                output += piece
                if translation_loop(output,text): issue = 'Повтор генерации'; break
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
        finally:
            # Closing the generator is what tells a remote engine to stop between tokens.
            close=getattr(pieces,'close',None)
            if close is not None:close()
        truncated = False
        if end_reason == 'repetition': issue = issue or 'Повтор генерации'
        elif end_reason == 'length' and output.strip() and not issue:
            # The token budget ran out. Keep what was translated, visibly cut,
            # instead of silently dropping the whole version.
            truncated = True
            output = output.rstrip() + TRUNCATION_MARKER
        elif end_reason != 'stop': issue = issue or 'Перевод не завершён'
        if not output.strip(): issue = issue or 'Пустой перевод'
        return MTResult(output,end_reason,issue,time.monotonic()-began,bool(preview),truncated)

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
                           finish_reason=result.end_reason,issue=result.issue,
                           truncated=result.truncated)
            self.mt_event('mt_finished',job,seconds=result.seconds,
                          finish_reason=result.end_reason,issue=result.issue,
                          truncated=result.truncated)
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
