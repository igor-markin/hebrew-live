import struct
import threading
import time
import types
import unittest
from unittest import mock

import numpy as np

from hebrew_live import phone_audio
from hebrew_live.phone_audio import Blocks, PhoneAudio, PhoneAudioError, command, parse_header


def wav(pcm, rate=48000, channels=2, bits=16):
    return (b'RIFF' + struct.pack('<I', 0xffffffff) + b'WAVEfmt ' +
            struct.pack('<IHHIIHH', 16, 1, channels, rate, rate * channels * bits // 8, channels * bits // 8, bits) +
            b'data' + struct.pack('<I', 0xffffffff) + pcm)


def stereo(seconds, left=16384, right=0):
    return np.tile(np.array([left, right], dtype='<i2'), round(48000 * seconds)).tobytes()


class FakeScrcpy:
    """Stands in for the scrcpy process: writes a WAV stream into the FIFO it was given."""
    payload = b''; log_line = b''; exits = None

    def __init__(self, arguments, stdout=None, **_):
        self.arguments, self.code, self.released = arguments, self.exits, threading.Event()
        if self.log_line: stdout.write(self.log_line); stdout.flush()
        if self.payload:
            fifo = next(item.split('=', 1)[1] for item in arguments if item.startswith('--record='))
            threading.Thread(target=self.write, args=(fifo,), daemon=True).start()

    def write(self, fifo):
        try:
            with open(fifo, 'wb', buffering=0) as out:
                out.write(self.payload); self.released.wait(5)
        except BrokenPipeError:
            pass                                         # the reader gave up on a bad stream

    def poll(self): return self.code
    def terminate(self): self.code = -15; self.released.set()
    def wait(self, timeout=None): return self.code
    def kill(self): self.code = -9; self.released.set()


def wait_for(condition, seconds=3.):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition(): return True
        time.sleep(.01)
    return False


class PhoneAudioTests(unittest.TestCase):
    def test_header_is_parsed_only_when_complete(self):
        data = wav(b'')
        self.assertIsNone(parse_header(data[:30]))
        self.assertEqual(parse_header(data), (48000, 2, len(data)))
        with self.assertRaises(PhoneAudioError): parse_header(wav(b'', bits=24))

    def test_blocks_are_mono_and_fixed_length(self):
        blocks = Blocks(2, 4800); pcm = stereo(.25)
        out = list(blocks.feed(pcm[:1000])) + list(blocks.feed(pcm[1000:]))
        self.assertEqual([len(block) for block in out], [4800, 4800])
        self.assertEqual(out[0].dtype, np.float32); self.assertAlmostEqual(float(out[0][0]), .25, places=4)
        self.assertEqual([len(block) for block in blocks.flush()], [2400]); self.assertEqual(list(blocks.flush()), [])

    def test_command_takes_only_the_other_side_of_the_call_and_plays_nothing(self):
        arguments = command('/tmp/x.wav', executable='/opt/homebrew/bin/scrcpy')
        for expected in ('--no-video', '--no-audio-playback', '--no-window', '--audio-source=voice-call-downlink',
                         '--audio-codec=raw', '--record=/tmp/x.wav', '--record-format=wav'):
            self.assertIn(expected, arguments)
        with mock.patch.object(phone_audio, 'find_scrcpy', return_value=None), self.assertRaises(PhoneAudioError):
            command('/tmp/x.wav')

    def test_call_audio_arrives_as_blocks_and_the_tail_is_flushed(self):
        process = type('Scrcpy', (FakeScrcpy,), dict(payload=wav(stereo(.25))))
        blocks = []; ended = []
        with PhoneAudio(blocks.append, ended.append, executable='scrcpy', popen=process) as phone:
            self.assertTrue(wait_for(lambda: len(blocks) == 3), [len(block) for block in blocks])
            folder = phone.folder
        self.assertEqual([len(block) for block in blocks], [4800, 4800, 2400])
        self.assertAlmostEqual(float(np.mean(blocks[0])), .25, places=4)
        self.assertEqual(ended, [])                      # stopping on purpose is not a failure
        import os
        self.assertFalse(os.path.exists(folder))

    def test_scrcpy_exit_reports_its_last_error(self):
        process = type('Scrcpy', (FakeScrcpy,), dict(log_line=b'INFO: starting\nERROR: Could not find any ADB device\nERROR: Server connection failed\n', exits=1))
        ended = []
        with PhoneAudio(lambda block: None, ended.append, executable='scrcpy', popen=process):
            self.assertTrue(wait_for(lambda: ended))
        self.assertEqual(ended, ['ERROR: Could not find any ADB device'])

    def test_wrong_sample_rate_ends_the_stream(self):
        process = type('Scrcpy', (FakeScrcpy,), dict(payload=wav(stereo(.1), rate=44100)))
        ended = []
        with PhoneAudio(lambda block: None, ended.append, executable='scrcpy', popen=process):
            self.assertTrue(wait_for(lambda: ended))
        self.assertIn('44100', ended[0])

    def test_phone_is_requested_by_flag_or_environment(self):
        from hebrew_live.runtime import phone_requested
        with mock.patch.dict('os.environ', {}, clear=True):
            self.assertTrue(phone_requested(types.SimpleNamespace(phone=True)))
            self.assertFalse(phone_requested(types.SimpleNamespace(phone=False)))
            self.assertFalse(phone_requested(types.SimpleNamespace()))
        with mock.patch.dict('os.environ', {'HEBREW_LIVE_INPUT': 'phone'}):
            self.assertTrue(phone_requested(types.SimpleNamespace()))


if __name__ == '__main__':
    unittest.main()
