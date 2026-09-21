"""Durable local session output; inference routes logs to its immutable part."""
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import json
import logging
import os
import shutil
import threading
import time
import traceback
import uuid

DEFAULT_FREE_RESERVE = 64 * 1024 * 1024


class LowStorageError(OSError):
    """The archive volume is too full to begin or safely continue recording."""


class StorageGuard:
    def __init__(self, path, reserve=DEFAULT_FREE_RESERVE, free_bytes=None):
        self.path=Path(path);self.reserve=reserve
        self.free_bytes=free_bytes or (lambda value:shutil.disk_usage(value).free)

    def check(self, upcoming=0):
        available=self.free_bytes(self.path)
        if available < self.reserve+max(0,upcoming):
            raise LowStorageError(f'Insufficient free space for a readable session archive ({available} bytes free)')
        return available

    def check_metadata(self, upcoming=0):
        available=self.free_bytes(self.path)
        if available < max(0,upcoming):
            raise LowStorageError(f'Insufficient free space to finalize session metadata ({available} bytes free)')
        return available


def private_text(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf8')


class Log:
    def __init__(self, folder, debug=False, path=None):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = path or folder / (datetime.now(ZoneInfo('Asia/Jerusalem')).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.jsonl')
        self.file = private_text(self.path)
        self.lock = threading.RLock()
        self.debug = debug
        self.start = time.monotonic()
        self.metrics = {}
        self.closed = False

    def event(self, event, **data):
        with self.lock:
            for key in ('seconds', 'lag', 'audio_lag'):
                if key in data:
                    self.metrics.setdefault(event + '.' + key, []).append(data[key])
            self.file.write(json.dumps(dict(event=event, elapsed=round(time.monotonic()-self.start, 3), **data), ensure_ascii=False) + '\n')
            self.file.flush()

    def error(self, exc):
        self.event('error', type=type(exc).__name__, stack=[dict(file=Path(f.filename).name, line=f.lineno, function=f.name) for f in traceback.extract_tb(exc.__traceback__)])

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            summary = {}
            for key, values in self.metrics.items():
                ordered = sorted(values); n = len(ordered)
                summary[key] = dict(count=n, p50=ordered[n//2], p95=ordered[min(n-1, int(n*.95))], max=ordered[-1])
            self.event('summary', metrics=summary)
        finally:
            self.file.close()


class Part:
    def __init__(self, folder, number, direction, metadata, save_audio=True, storage_guard=None):
        self.number, self.direction = number, direction
        self.save_audio=bool(save_audio);self.storage_guard=storage_guard
        base = folder / f'{number:03d}-{direction}'
        self.log = Log(folder, path=Path(str(base) + '.diagnostics.jsonl'))
        self.source = self.target = self.audio = None
        self.audio_path = Path(str(base) + '.audio.wav')
        self.rate = None
        self.samples = 0
        self.written = set()
        try:
            self.source = private_text(Path(str(base) + '.transcript.txt'))
            self.target = private_text(Path(str(base) + '.translation.txt'))
            if self.save_audio:
                fd = os.open(self.audio_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                # Valid empty WAV even if model loading/device opening fails.
                self.configure_audio(16000, 1)
            self.log.event('part_start', part=number, direction=direction,
                           audio_saved=self.save_audio, **metadata)
        except BaseException:
            self.close()
            raise

    def configure_audio(self, rate, channels):
        import soundfile as sf
        if self.samples:
            actual_channels=self.audio.channels if self.audio else getattr(self,'channels',None)
            if self.rate != rate or actual_channels != channels:
                raise RuntimeError('Audio format changed within a part')
            return
        self.rate=rate;self.channels=channels
        if not self.save_audio:
            self.log.event('audio_format',rate=rate,channels=channels,subtype=None,persisted=False)
            return
        if self.audio:
            self.audio.close()
        if self.storage_guard:self.storage_guard.check(4096)
        self.audio = sf.SoundFile(self.audio_path, 'w', samplerate=rate, channels=channels, subtype='FLOAT', format='WAV')
        self.audio.flush()
        self.log.event('audio_format',rate=rate,channels=channels,subtype='FLOAT')

    def write_audio(self, data, rate):
        channels = data.shape[1] if data.ndim == 2 else 1
        actual_channels=self.audio.channels if self.audio else getattr(self,'channels',None)
        if self.rate != rate or actual_channels != channels:
            self.configure_audio(rate, channels)
        if self.storage_guard:self.storage_guard.check(len(data)*channels*4+4096)
        if self.audio:
            self.audio.write(data)
        self.samples += len(data)
        if self.audio:self.audio.flush()
        return self.samples / rate

    def text(self, kind, fragment, value):
        key = (kind, fragment.id)
        if key in self.written:
            return
        file = self.source if kind == 'source' else self.target
        start = getattr(fragment,'start',max(0, fragment.offset - len(fragment.audio)/16000 + fragment.prefix))
        file.write(f'[{fragment.id:06d} {start:.3f}–{fragment.offset:.3f}s]\n{value.strip()}\n\n')
        file.flush()
        self.written.add(key)

    def close(self):
        failures = []
        for file in (self.audio, self.source, self.target):
            if file:
                try:
                    file.close()
                except Exception as exc:
                    failures.append(exc)
        try:
            self.log.close()
        except Exception as exc:
            failures.append(exc)
        if failures:
            raise failures[0]


class Session:
    debug = False
    def __init__(self, folder, direction, metadata, save_audio=True,
                 free_space_reserve=DEFAULT_FREE_RESERVE, free_bytes=None):
        folder.mkdir(parents=True, exist_ok=True)
        self.storage_guard=StorageGuard(folder,free_space_reserve,free_bytes)
        self.storage_guard.check(16384)
        stamp = datetime.now(ZoneInfo('Asia/Jerusalem')).strftime('%Y%m%d-%H%M%S')
        self.path = folder / (stamp + '-' + uuid.uuid4().hex[:8])
        self.path.mkdir(mode=0o700)
        self.metadata = metadata
        self.save_audio=bool(save_audio)
        self.restart_safe=True
        self.integrity=dict(schema_version=1,audio_saved=self.save_audio,partial=False,
                            accepted={},asr_attempted={},terminal=[],known_unprocessed=[],
                            capture_discontinuities=[])
        self._accepted_samples={}
        self._part_directions={}
        self.parts = {}
        self.local = threading.local()
        self.lock = threading.RLock()
        self._integrity_lock=threading.Lock()
        self.current = 1
        self.add(1, direction)
        self.write_integrity()

    def add(self, number, direction):
        with self.lock:
            metadata = dict(self.metadata)
            if number > 1:
                from .languages import split_direction
                metadata['language'] = split_direction(direction)[0]
            part = Part(self.path, number, direction, metadata,self.save_audio,self.storage_guard)
            self.parts[number] = part
            self._part_directions[number]=direction
            self.current = number
            return part

    def bind(self, part):
        self.local.part = part

    def event(self, event, **data):
        with self.lock:
            part = data.pop('part', None) or getattr(self.local, 'part', None) or self.current
            self.parts[part].log.event(event, **data)
            if event=='live_asr':
                self._append_range('asr_attempted',part,data.get('start'),data.get('end'),
                                   status=data.get('status'),final=bool(data.get('final')))
            elif event=='phrase_asr_status':
                self._append_range('asr_attempted',part,data.get('start'),data.get('end'),
                                   status=data.get('status'),final=bool(data.get('final')))
            elif event=='live_publication' and data.get('stage') in ('closed','technical','unavailable'):
                self._append_terminal(part,data.get('start'),data.get('end'),data.get('stage'),data.get('issue'))
            elif event=='phrase_terminal':
                self._append_terminal(part,data.get('start'),data.get('end'),data.get('outcome'),data.get('issue'))

    def try_event(self, event, **data):
        """Write a control-path event only when no worker owns session I/O."""
        if not self.lock.acquire(blocking=False):return False
        try:self.event(event,**data)
        finally:self.lock.release()
        return True

    def _append_range(self, key, part, start, end, **extra):
        if not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or end<=start:return
        with self._integrity_lock:
            self.integrity[key].setdefault(str(part),[]).append(dict(start=round(start,3),end=round(end,3),**extra))

    def _append_terminal(self, part, start, end, outcome, issue=None):
        if not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or end<=start:return
        with self._integrity_lock:
            self.integrity['terminal'].append(dict(part=part,start=round(start,3),end=round(end,3),
                                                   outcome=outcome,issue=issue))

    def is_partial(self):
        with self._integrity_lock:return bool(self.integrity['partial'])

    def note_accepted(self, part, samples, rate):
        """Record PCM copied into the application FIFO; never implies driver completeness."""
        with self._integrity_lock:
            total=self._accepted_samples.get(part,0)+samples;self._accepted_samples[part]=total
            self.integrity['accepted'][str(part)]=dict(samples=total,rate=rate,duration=round(total/rate,3))

    def note_unprocessed(self, part, start, end, reason, extent='known'):
        with self._integrity_lock:
            if isinstance(start,(int,float)) and isinstance(end,(int,float)) and end>start:
                item=dict(part=part,start=round(start,3),end=round(end,3),reason=reason,extent=extent)
            else:item=dict(part=part,start=None,end=None,reason=reason,extent=extent)
            if item not in self.integrity['known_unprocessed']:self.integrity['known_unprocessed'].append(item)
            self.integrity['partial']=True

    def note_unprocessed_fragment(self, fragment, reason):
        settings=getattr(fragment,'settings',None);part=getattr(settings,'part',self.current)
        audio=getattr(fragment,'audio',())
        start=max(0.,getattr(fragment,'offset',0.)-len(audio)/16000+getattr(fragment,'prefix',0.))
        self.note_unprocessed(part,start,getattr(fragment,'offset',start),reason)

    def note_capture_discontinuity(self, detail):
        with self._integrity_lock:
            self.integrity['capture_discontinuities'].append(dict(extent='unknown',detail=str(detail)))
            self.integrity['partial']=True

    def write_integrity(self, include_parts=True):
        with self._integrity_lock:
            payload=json.loads(json.dumps(self.integrity))
        if include_parts:
            with self.lock:
                payload['parts']={str(number):dict(direction=part.direction,audio_saved=part.audio_path.is_file(),
                                                   samples=part.samples,rate=part.rate)
                                  for number,part in self.parts.items()}
        else:
            previous=self.path/'session.json'
            try:old=json.loads(previous.read_text())
            except (OSError,json.JSONDecodeError):old={}
            payload['parts']=old.get('parts',{}) if isinstance(old,dict) else {}
        path=self.path/'session.json';temporary=self.path/'.session.json.tmp'
        self.storage_guard.check_metadata(16384)
        fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf8') as stream:
                json.dump(payload,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:
            if temporary.exists():temporary.unlink()

    def integrity_view(self):
        with self._integrity_lock:
            known=list(self.integrity['known_unprocessed'])
            discontinuities=list(self.integrity['capture_discontinuities'])
            partial=bool(self.integrity['partial'])
        details=[]
        for item in known:
            part=item.get('part')
            details.append(dict(part=part,direction=self._part_directions.get(part),
                                reason=item.get('reason','runtime_error'),start=item.get('start'),end=item.get('end')))
        ranges=[f"part {item['part']} {item['direction'] or ''} · {item['start']:.3f}–{item['end']:.3f}s · {item['reason']}"
                for item in details if isinstance(item.get('start'),(int,float)) and isinstance(item.get('end'),(int,float))]
        kind='mixed' if known and discontinuities else 'capture_unknown' if discontinuities else 'known_unprocessed' if known else None
        return dict(partial=partial,partial_kind=kind,partial_ranges=ranges,partial_details=details,
                    capture_discontinuity=bool(discontinuities))

    def error(self, exc):
        with self.lock:
            part = getattr(self.local, 'part', None) or self.current
            self.parts[part].log.error(exc)

    def close(self):
        if not self.restart_safe:
            # A daemon worker may still own a file/session lock after its bounded
            # join expired. Do not close handles underneath it or wait on that
            # lock; persist the parent-owned integrity ledger only.
            self.write_integrity(include_parts=False)
            return
        failures = []
        for part in self.parts.values():
            try:
                part.close()
            except Exception as exc:
                failures.append(exc)
        if failures:self.note_unprocessed(self.current,None,None,'archive_finalize_failed','unknown')
        try:self.write_integrity()
        except Exception as exc:failures.append(exc)
        if failures:
            raise failures[0]


class LibraryHandler(logging.Handler):
    def __init__(self, log):
        super().__init__()
        self.log = log

    def emit(self, record):
        # No arbitrary library message/input text in technical diagnostics.
        known = str(record.msg).startswith('Unrecognized keys in `rope_parameters`')
        self.log.event('library', logger=record.name, level=record.levelname,
                       detail=record.getMessage() if known else None,
                       file=Path(record.pathname).name, line=record.lineno,
                       message_template_sha256=hashlib.sha256(str(record.msg).encode()).hexdigest())
