"""The other side of a phone call, taken digitally from an Android phone over USB.

scrcpy records the call downlink - the other person's voice only - into a FIFO as WAV.
The room, the phone speaker and the owner's own voice never reach recognition. Outside a
call the phone sends almost nothing, so the stream just waits.
"""
import os
import shutil
import struct
import subprocess
import tempfile
import threading

import numpy as np

RATE = 48000                 # scrcpy raw audio is always 48 kHz stereo 16-bit
SOURCE = 'voice-call-downlink'
BLOCK_SECONDS = .1
IDLE_FLUSH_SECONDS = .5      # a call that ends mid-block must not leave its tail waiting
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
    if scrcpy exits on its own (cable unplugged, USB debugging refused)."""

    def __init__(self, on_audio, on_end, source=SOURCE, executable=None, popen=subprocess.Popen):
        self.on_audio, self.on_end, self.source, self.executable, self.popen = on_audio, on_end, source, executable, popen
        self.stopping = threading.Event(); self.thread = self.process = self.folder = None

    def __enter__(self):
        self.folder = tempfile.mkdtemp(prefix='hebrew-live-phone-')
        self.fifo, self.log = os.path.join(self.folder, 'audio.wav'), os.path.join(self.folder, 'scrcpy.log')
        os.mkfifo(self.fifo, 0o600)
        try:
            arguments = command(self.fifo, self.source, self.executable)
            environment = dict(os.environ, PATH=os.pathsep.join((os.environ.get('PATH', ''), *_SEARCH)))  # scrcpy runs adb
            with open(self.log, 'wb') as log:
                self.process = self.popen(arguments, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                          env=environment)
        except BaseException:
            self.cleanup(); raise
        self.thread = threading.Thread(target=self.read, name='phone-audio', daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopping.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(3)
            except subprocess.TimeoutExpired: self.process.kill()
        if self.thread: self.thread.join(3)
        self.cleanup()

    def cleanup(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def failure(self):
        """Why scrcpy stopped: its first error names the cause (no device, permission refused),
        the later ones only follow from it."""
        try:
            with open(self.log, encoding='utf8', errors='replace') as log:
                lines = [line.strip() for line in log if line.strip()]
        except OSError:
            lines = []
        problems = [line for line in lines if 'ERROR' in line]
        return problems[0] if problems else lines[-1] if lines else 'scrcpy stopped'

    def read(self):
        import select
        header = bytearray(); blocks = None
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
                        for block in blocks.flush(): self.on_audio(block)
                    if self.process.poll() is not None:
                        if not self.stopping.is_set(): self.on_end(self.failure())
                        return
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
                for block in blocks.feed(data): self.on_audio(block)
        except Exception as exc:
            if not self.stopping.is_set(): self.on_end(str(exc))
        finally:
            os.close(reader)
