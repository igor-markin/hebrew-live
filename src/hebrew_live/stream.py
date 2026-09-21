"""Ordered audio admission and boundaries shared by microphone and replay."""
from dataclasses import dataclass, replace
import queue
import threading
import time


@dataclass(frozen=True)
class Settings:
    part: int = 1
    # Internal constructors retain the historical direction for old test and
    # archive helpers. User sessions always pass the CLI/browser choice, whose
    # new-session default is ``he-en``.
    direction: str = 'he-ru'
    language: str = 'he'
    topic: str = 'none'
    generation: int = 0
    timing: tuple | None = None
    models: tuple | None = None
    mode: str = 'phrases'
    # The installed runtime passes ``draft`` explicitly. Keeping the dataclass
    # default on the classic phrase worker preserves the internal/test contract
    # for callers that construct Settings directly.
    publication: str = 'phrases'
    draft_max_audio_seconds: float = 20.0
    draft_catchup_enabled: bool = False


@dataclass
class Boundary:
    settings: Settings
    reason: str


@dataclass
class Captured:
    data: object
    end: float
    settings: Settings


@dataclass
class AudioBlock:
    data: object
    end: float
    offset: float
    settings: Settings


class Control:
    def __init__(self, settings, stop, accepted=None):
        self.settings = settings
        self.initial_settings = settings
        self.stop = stop
        self.lock = threading.RLock()
        self.queue = queue.Queue(maxsize=300)
        self.paused = False
        self.last_keys = {}
        self.pause_started = None
        self.paused_seconds = 0.
        self.accepted = accepted
        self.capture_rate = None

    def switch_models(self, selection):
        from .model_selection import validate
        values=validate(selection)
        with self.lock:
            if self.stop.is_set():raise ValueError('Session stopping')
            settings=replace(self.settings,models=(values['asr'],values['translation']))
            self.queue.put_nowait(Boundary(settings,'models'))
            self.settings=settings
            if not self.paused:
                self.paused=True;self.pause_started=time.monotonic()

    def switch_publication(self, publication):
        if publication not in ('phrases','revisable','draft'):raise ValueError('Invalid publication mode')
        with self.lock:
            if self.stop.is_set():raise ValueError('Session stopping')
            settings=replace(self.settings,publication=publication)
            self.queue.put_nowait(Boundary(settings,'publication'))
            self.settings=settings
            if not self.paused:
                self.paused=True;self.pause_started=time.monotonic()

    def switch_target(self, target):
        """Order a Hebrew target change after accepted audio already in flight."""
        from .languages import direction_for_target
        direction=direction_for_target(target)
        with self.lock:
            if self.stop.is_set():raise ValueError('Session stopping')
            if self.settings.direction==direction:return False
            settings=replace(self.settings,part=self.settings.part+1,direction=direction,language='he')
            # Captured chunks already in this FIFO retain their immutable old
            # Settings.  Chunks admitted after this boundary receive the new
            # target, so neither a late result nor a retry can be mislabelled.
            self.queue.put_nowait(Boundary(settings,'target_language'))
            self.settings=settings
            return True

    def active_time(self):
        with self.lock:
            now = time.monotonic()
            return now - self.paused_seconds - (now-self.pause_started if self.paused else 0)

    def accept(self, data, end):
        with self.lock:
            if self.paused or self.stop.is_set():
                return False
            self.queue.put_nowait(Captured(data.copy(), end, self.settings))
            if self.accepted is not None and self.capture_rate:
                self.accepted(self.settings.part,len(data),self.capture_rate)
            return True

    def key(self, key, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.stop.is_set() or key not in (' ', '\x14', '\x0c'):
                return False
            last = self.last_keys.get(key, -float('inf'))
            self.last_keys[key] = now
            # A repeat burst stays suppressed until an idle gap, not every Nth key.
            if now-last < .65:
                return False
            settings = self.settings
            reason = 'clear'
            if key == ' ':
                reason = 'resume' if self.paused else 'pause'
            elif key == '\x14':
                if settings.direction not in ('he-ru','ru-he'):
                    return False
                direction = 'ru-he' if settings.direction == 'he-ru' else 'he-ru'
                settings = replace(settings, part=settings.part+1, direction=direction, language=direction[:2])
                reason = 'direction'
            else:
                settings = replace(settings, generation=settings.generation+1)
            # Commit control state only after the ordered boundary was accepted.
            self.queue.put_nowait(Boundary(settings, reason))
            self.settings = settings
            if key == ' ':
                if self.paused:
                    self.paused_seconds += time.monotonic()-self.pause_started
                    self.pause_started = None
                else:
                    self.pause_started = time.monotonic()
                self.paused = not self.paused
            return True


def transfer(control, raw, session, rate, channels, consumer, errors, updates):
    """Disk and resampling outside the audio callback, preserving admission order."""
    import numpy as np
    import soxr
    settings = control.initial_settings
    resampler = soxr.ResampleStream(rate, 16000, 1, dtype='float32')
    emitted = 0
    base = 0.
    last_end = time.monotonic()
    last_health = 0.

    def emit(data, end):
        nonlocal emitted
        emitted += len(data)
        if len(data):
            raw.put_nowait(AudioBlock(data, end, base+emitted/16000, settings))

    try:
        session.parts[1].configure_audio(rate, channels)
        while True:
            item = control.queue.get()
            if item is None:
                emit(resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True), last_end)
                break
            if isinstance(item, Boundary):
                emit(resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True), last_end)
                raw.put_nowait(item)
                session.event(item.reason, part=settings.part, next_part=item.settings.part)
                if item.settings.part != settings.part:
                    session.add(item.settings.part, item.settings.direction).configure_audio(rate, channels)
                settings = item.settings
                base = session.parts[settings.part].samples / rate
                emitted = 0
                resampler = soxr.ResampleStream(rate, 16000, 1, dtype='float32')
                continue
            settings = item.settings
            last_end = item.end
            session.parts[settings.part].write_audio(item.data, rate)
            mono = item.data.mean(axis=1) if item.data.ndim == 2 else item.data
            emit(resampler.resample_chunk(mono), item.end)
            rms = float(np.sqrt(np.mean(mono*mono)))
            updates.put(('level', 0, rms))
            if item.end-last_health >= 1:
                last_health = item.end
                session.event('audio_health',part=settings.part,rms=rms,peak=float(np.max(np.abs(mono))),
                              capture_queue=control.queue.qsize(),audio_queue=raw.qsize())
    except Exception as exc:
        if hasattr(session,'note_unprocessed'):
            from .session import LowStorageError
            reason='low_storage' if isinstance(exc,LowStorageError) else 'storage_or_recording_write_failed'
            session.note_unprocessed(settings.part,None,None,reason,'unknown')
        errors.put(exc); control.stop.set()
        try:
            session.error(exc)
        except Exception:
            pass
    finally:
        deadline=time.monotonic()+5
        while consumer.is_alive() and time.monotonic()<deadline:
            try:
                raw.put(None, timeout=.1)
                break
            except queue.Full:
                pass
        if consumer.is_alive() and time.monotonic()>=deadline and hasattr(session,'note_unprocessed'):
            session.note_unprocessed(settings.part,None,None,'segmenter_sentinel_timeout','unknown')


def replay(file, control):
    """Pause freezes file position and the replay clock; accepted chunks are unique."""
    deadline = control.active_time()
    while not control.stop.is_set():
        with control.lock:
            if not control.paused and control.active_time() >= deadline:
                data = file.read(max(1, file.samplerate//10), dtype='float32', always_2d=True)
                if not len(data):
                    return
                control.accept(data, time.monotonic())
                deadline += len(data)/file.samplerate
        control.stop.wait(.01)
