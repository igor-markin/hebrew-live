"""The other side of a phone call, taken digitally from an Android phone over USB.

scrcpy records the call downlink - the other person's voice only - into a FIFO as WAV.
The room, the phone speaker and the owner's own voice never reach recognition. Outside a
call the phone sends almost nothing, so the stream just waits.
"""
import os
import shutil
import signal
import struct
import subprocess
import tempfile
import threading

import numpy as np

RATE = 48000                 # scrcpy raw audio is always 48 kHz stereo 16-bit
SOURCE = 'voice-call-downlink'
BLOCK_SECONDS = .1
IDLE_FLUSH_SECONDS = .5      # a call that ends mid-block must not leave its tail waiting
STARTS = 3                   # scrcpy can crash while it opens the recording: two more tries before giving up
RESTART_PAUSE_SECONDS = .5
LOG_TAIL_LINES = 5
_SEARCH = ('/opt/homebrew/bin', '/usr/local/bin')


class PhoneAudioError(RuntimeError):
    pass


def find_scrcpy():
    """An app started from Finder has no Homebrew on PATH."""
    found = os.environ.get('HEBREW_LIVE_SCRCPY') or shutil.which('scrcpy')
    if found:
        return found
    return next((os.path.join(folder, 'scrcpy') for folder in _SEARCH
                 if os.access(os.path.join(folder, 'scrcpy'), os.X_OK)), None)


def find_adb():
    """The adb the status check uses is the one scrcpy gets through ADB, so both see the same phone."""
    found = os.environ.get('HEBREW_LIVE_ADB') or shutil.which('adb')
    if found:
        return found
    return next((os.path.join(folder, 'adb') for folder in _SEARCH
                 if os.access(os.path.join(folder, 'adb'), os.X_OK)), None)


# `adb devices` states, as the window names them. Anything else is `unknown`.
_STATES = {'device': 'ready', 'unauthorized': 'unauthorized', 'authorizing': 'unauthorized', 'offline': 'offline',
           'no permissions': 'no_permissions', 'recovery': 'wrong_mode', 'rescue': 'wrong_mode',
           'sideload': 'wrong_mode', 'bootloader': 'wrong_mode', 'host': 'wrong_mode'}
STATUSES = ('ready', 'no_scrcpy', 'no_adb', 'no_device', 'unauthorized', 'offline', 'no_permissions',
            'wrong_mode', 'several_devices', 'adb_failed', 'timeout', 'unknown')
CAPTURE_FAILED = 'capture_failed'   # not a check result: scrcpy stopped while adb still saw the phone


def parse_devices(output):
    """[(serial, state)] from `adb devices`; daemon start-up chatter and blank lines are skipped."""
    found = []
    for line in output.splitlines():
        words = line.split(None, 1)
        if len(words) < 2 or line.startswith(('*', 'List of')):
            continue
        serial, rest = words
        # `-l` and newer adb pad with spaces and append details; only "no permissions" has a space in it.
        state = 'no permissions' if rest.startswith('no permissions') else rest.split()[0]
        found.append((serial, state))
    return found


START_SECONDS = 15.          # a cold adb service first scans the USB ports


def status(run=subprocess.run, timeout=3., start_timeout=START_SECONDS):
    """Whether a call can be taken now, without starting capture: one of STATUSES.

    With the adb service down, `adb devices` starts it itself and can need more than the three
    seconds it has here (the likely cause of three failed window checks on 25.11.2026, not
    reproduced). The service is started first, with its own longer limit and its output not
    captured (a service that keeps an inherited pipe open would hold up the check).
    """
    if not find_scrcpy():
        return 'no_scrcpy'
    adb = find_adb()
    if not adb:
        return 'no_adb'
    try:
        started = run([adb, 'start-server'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      stdin=subprocess.DEVNULL, timeout=start_timeout)
        if started.returncode:
            return 'adb_failed'
        result = run([adb, 'devices'], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 'timeout'
    except OSError:
        return 'adb_failed'
    if result.returncode:
        return 'adb_failed'
    devices = parse_devices(result.stdout or '')
    if len(devices) > 1:
        return 'several_devices'          # scrcpy refuses to pick one, whatever their states
    if not devices:
        return 'no_device'
    return _STATES.get(devices[0][1], 'unknown')


def command(fifo, source=SOURCE, executable=None):
    executable = executable or find_scrcpy()
    if not executable:
        raise PhoneAudioError('scrcpy is not installed: brew install scrcpy')
    return [executable, '--no-video', '--no-audio-playback', '--no-window', '--no-control',
            f'--audio-source={source}', '--audio-codec=raw', f'--record={fifo}', '--record-format=wav']


def parse_header(data):
    """(rate, channels, payload offset) once the WAV header is complete, else None."""
    fmt, payload = data.find(b'fmt '), data.find(b'data')
    if fmt < 0 or payload < 0 or len(data) < payload + 8:
        return None
    _, channels, rate, _, _, bits = struct.unpack('<HHIIHH', data[fmt + 8:fmt + 24])
    if bits != 16 or not channels:
        raise PhoneAudioError(f'Unexpected phone audio format: {bits}-bit, {channels} channels')
    return rate, channels, payload + 8


class Blocks:
    """Cut a PCM16 byte stream into mono float32 blocks of a fixed length."""

    def __init__(self, channels, frames):
        self.channels, self.size, self.pending = channels, frames * channels * 2, bytearray()

    def feed(self, data):
        self.pending += data
        while len(self.pending) >= self.size:
            yield self.mono(self.pending[:self.size]); del self.pending[:self.size]

    def flush(self):
        whole = len(self.pending) // (self.channels * 2) * self.channels * 2
        if whole:
            yield self.mono(self.pending[:whole]); del self.pending[:whole]

    def mono(self, data):
        samples = np.frombuffer(bytes(data), dtype='<i2').astype(np.float32) / 32768
        return samples.reshape(-1, self.channels).mean(axis=1)


class PhoneAudio:
    """Context manager: `on_audio(block)` for every 100 ms of call audio, `on_end(reason)`
    if scrcpy exits on its own (cable unplugged, USB debugging refused).

    A scrcpy that stops before any audio arrived is started again, up to `starts` runs in all:
    scrcpy 5.0.1 sometimes crashes while it opens the recording. `on_event(name, **data)` hears
    every exit and restart, so the session log keeps the reason after the temporary folder is gone."""

    def __init__(self, on_audio, on_end, source=SOURCE, executable=None, popen=subprocess.Popen,
                 on_event=None, starts=STARTS, restart_pause=RESTART_PAUSE_SECONDS):
        self.on_audio, self.on_end, self.source, self.executable, self.popen = on_audio, on_end, source, executable, popen
        self.on_event, self.starts, self.restart_pause = on_event, starts, restart_pause
        self.stopping = threading.Event(); self.lock = threading.Lock()
        self.thread = self.process = self.folder = None; self.attempt = 0

    def __enter__(self):
        self.folder = tempfile.mkdtemp(prefix='hebrew-live-phone-')
        self.fifo = os.path.join(self.folder, 'audio.wav')
        os.mkfifo(self.fifo, 0o600)
        try:
            self.arguments = command(self.fifo, self.source, self.executable)
            self.environment = dict(os.environ, PATH=os.pathsep.join((os.environ.get('PATH', ''), *_SEARCH)))  # scrcpy runs adb
            adb = find_adb()
            if adb: self.environment['ADB'] = adb
            self.launch()
        except BaseException:
            self.cleanup(); raise
        self.thread = threading.Thread(target=self.read, name='phone-audio', daemon=True)
        self.thread.start()
        return self

    def launch(self):
        """Start one scrcpy run with its own log. False once stopping: `__exit__` must not miss a process."""
        with self.lock:
            if self.stopping.is_set():
                return False
            self.attempt += 1
            self.log = os.path.join(self.folder, f'scrcpy-{self.attempt}.log')
            with open(self.log, 'wb') as log:
                self.process = self.popen(self.arguments, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                          env=self.environment)
            return True

    def __exit__(self, *_):
        with self.lock:
            self.stopping.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(3)
            except subprocess.TimeoutExpired: self.process.kill()
        if self.thread: self.thread.join(3)
        self.cleanup()

    def event(self, name, **data):
        if self.on_event is None:
            return
        try: self.on_event(name, **data)
        except Exception: pass               # a diagnostics failure must not stop the call

    def cleanup(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def lines(self):
        try:
            with open(self.log, encoding='utf8', errors='replace') as log:
                return [line.strip() for line in log if line.strip()]
        except OSError:
            return []

    def failure(self, code=None):
        """Why scrcpy stopped: its first error names the cause (no device, permission refused),
        the later ones only follow from it. A crash prints nothing, so the signal names it."""
        lines = self.lines()
        problems = [line for line in lines if 'ERROR' in line]
        if problems:
            return problems[0]
        if isinstance(code, int) and code < 0:
            try: name = signal.Signals(-code).name
            except ValueError: name = f'signal {-code}'
            return f'scrcpy crashed: {name}'
        return lines[-1] if lines else 'scrcpy stopped'

    def exited(self, audio):
        """scrcpy is gone on its own: log why, then start it again or report the end. True if restarted."""
        code = self.process.poll()
        reason = self.failure(code)
        restart = not audio and self.attempt < self.starts
        self.event('phone_capture_exit', attempt=self.attempt, returncode=code, reason=reason[:300], audio=audio,
                   restart=restart, log=[line[:200] for line in self.lines()[-LOG_TAIL_LINES:]])
        if restart and not self.stopping.wait(self.restart_pause) and self.launch():
            self.event('phone_capture_restart', attempt=self.attempt)
            return True
        if not self.stopping.is_set(): self.on_end(reason)
        return False

    def read(self):
        import select
        header = bytearray(); blocks = None; delivered = False
        # Non-blocking, so that a scrcpy which fails before opening the FIFO cannot hang us.
        reader = os.open(self.fifo, os.O_RDONLY | os.O_NONBLOCK)
        try:
            idle = 0.
            while not self.stopping.is_set():
                ready, _, _ = select.select([reader], [], [], .1)
                try: data = os.read(reader, 65536) if ready else b''
                except BlockingIOError: data = b''; ready = []
                if not data:
                    idle += .1
                    if blocks and idle >= IDLE_FLUSH_SECONDS:
                        for block in blocks.flush(): self.on_audio(block); delivered = True
                    if self.process.poll() is not None:
                        if self.stopping.is_set() or not self.exited(audio=delivered):
                            return
                        header = bytearray(); blocks = None; idle = 0.    # a new run writes a new WAV header
                        continue
                    if ready: self.stopping.wait(.1)      # EOF before the writer opened: do not spin
                    continue
                idle = 0.
                if blocks is None:
                    header += data
                    parsed = parse_header(header)
                    if parsed is None: continue
                    rate, channels, offset = parsed
                    if rate != RATE: raise PhoneAudioError(f'Unexpected phone audio rate: {rate} Hz')
                    blocks = Blocks(channels, round(RATE * BLOCK_SECONDS)); data = bytes(header[offset:])
                for block in blocks.feed(data): self.on_audio(block); delivered = True
        except Exception as exc:
            if not self.stopping.is_set(): self.on_end(str(exc))
        finally:
            os.close(reader)
