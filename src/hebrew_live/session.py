"""Durable local session output; inference routes logs to its immutable part."""
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import json
import logging
import os
import threading
import time
import traceback
import uuid


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
    def __init__(self, folder, number, direction, metadata):
        self.number, self.direction = number, direction
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
            fd = os.open(self.audio_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            # Valid empty WAV even if model loading/device opening fails.
            self.configure_audio(16000, 1)
            self.log.event('part_start', part=number, direction=direction, **metadata)
        except BaseException:
            self.close()
            raise

    def configure_audio(self, rate, channels):
        import soundfile as sf
        if self.samples:
            if self.rate != rate or self.audio.channels != channels:
                raise RuntimeError('Audio format changed within a part')
            return
        if self.audio:
            self.audio.close()
        self.rate = rate
        self.audio = sf.SoundFile(self.audio_path, 'w', samplerate=rate, channels=channels, subtype='FLOAT', format='WAV')
        self.audio.flush()
        self.log.event('audio_format',rate=rate,channels=channels,subtype='FLOAT')

    def write_audio(self, data, rate):
        channels = data.shape[1] if data.ndim == 2 else 1
        if self.rate != rate or self.audio.channels != channels:
            self.configure_audio(rate, channels)
        self.audio.write(data)
        self.samples += len(data)
        self.audio.flush()
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
    def __init__(self, folder, direction, metadata):
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(ZoneInfo('Asia/Jerusalem')).strftime('%Y%m%d-%H%M%S')
        self.path = folder / (stamp + '-' + uuid.uuid4().hex[:8])
        self.path.mkdir(mode=0o700)
        self.metadata = metadata
        self.parts = {}
        self.local = threading.local()
        self.lock = threading.RLock()
        self.current = 1
        self.add(1, direction)

    def add(self, number, direction):
        with self.lock:
            metadata = dict(self.metadata)
            if number > 1:
                from .languages import split_direction
                metadata['language'] = split_direction(direction)[0]
            part = Part(self.path, number, direction, metadata)
            self.parts[number] = part
            self.current = number
            return part

    def bind(self, part):
        self.local.part = part

    def event(self, event, **data):
        with self.lock:
            part = data.pop('part', None) or getattr(self.local, 'part', None) or self.current
            self.parts[part].log.event(event, **data)

    def error(self, exc):
        with self.lock:
            part = getattr(self.local, 'part', None) or self.current
            self.parts[part].log.error(exc)

    def close(self):
        failures = []
        for part in self.parts.values():
            try:
                part.close()
            except Exception as exc:
                failures.append(exc)
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
