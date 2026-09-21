"""Exercise the actual curses loop and macOS control characters over a PTY."""
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

CHILD = r'''
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys, threading, time
import numpy as np
import hebrew_live.cli as cli
import hebrew_live.remote_engine as remote_engine
from hebrew_live.runtime import run_session
from hebrew_live.session import Session

class Engine:
    mx=type('MX',(),{'get_peak_memory':lambda:0})
    def __init__(self,folder,log,language='he',backend='turbo',direction='he-ru',topic='none',**kw):
        self.log=log;self.language=language;self.backend=backend;self.direction=direction;self.topic=topic
        self.translation_size='milmmt';self.custom_models=False;self.translation_context=[]
    def warmup(self):pass
    def recognize(self,*a,**kwargs):
        text='שלום עולם' if self.language=='he' else 'Привет мир'
        self.recognition_words=[dict(word=' '+w,start=i*.02,end=(i+1)*.02) for i,w in enumerate(text.split())]
        return text
    def translate(self,*a):
        time.sleep(.03)
        yield ('Привет мир.' if self.direction=='he-ru' else 'שלום עולם.'),'stop'
    def switch_models(self,selection):self.backend=selection['asr']
    def interrupt(self):pass
    def close(self):pass
class VAD:
    def __init__(self,*a,**kw):pass
    def __call__(self,*a):return 1
    def reset(self):pass
class Stream:
    def __init__(self,callback,**kw):self.callback=callback;self.stop=threading.Event()
    def __enter__(self):
        def audio():
            while not self.stop.wait(.05):self.callback(np.full((800,1),.25,dtype=np.float32),800,None,False)
        self.thread=threading.Thread(target=audio);self.thread.start();return self
    def __exit__(self,*a):self.stop.set();self.thread.join()
args=SimpleNamespace(models=Path(sys.argv[1])/'models',language=None,direction='he-ru',topic='none',command='listen',device=None)
session=Session(Path(sys.argv[1]),'he-ru',{})
try:
    with patch.object(remote_engine,'RemoteEngine',Engine),patch.object(cli,'VAD',VAD),patch.object(cli,'verify'),patch('sounddevice.query_devices',return_value={'default_samplerate':16000}),patch('sounddevice.InputStream',Stream):
        run_session(args,session)
finally:session.close()
'''


class TerminalTests(unittest.TestCase):
    def test_pause_repeat_ctrl_t_clear_resize_and_stop_in_real_tty(self):
        with tempfile.TemporaryDirectory() as tmp:
            master,slave=pty.openpty()
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,110,0,0))
            env=dict(os.environ,TERM='xterm-256color',TERM_PROGRAM='Apple_Terminal',PYTHONUNBUFFERED='1')
            process=subprocess.Popen([sys.executable,'-c',CHILD,tmp],stdin=slave,stdout=slave,stderr=slave,env=env)
            os.close(slave);output=bytearray()
            def pump(seconds):
                until=time.monotonic()+seconds
                while time.monotonic()<until:
                    if select.select([master],[],[],.02)[0]:
                        try:output.extend(os.read(master,65536))
                        except OSError as exc:
                            if exc.errno==errno.EIO:return
                            raise
            try:
                pump(.6)
                os.write(master,b' ');pump(.1)
                for _ in range(10):os.write(master,b' ');pump(.04)
                pump(.75)
                os.write(master,b'\x14');pump(.2) # macOS VSTATUS must not consume Ctrl+T.
                os.write(master,b' ');pump(.5)
                os.write(master,b'\x0c');pump(.15)
                fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack('HHHH',12,40,0,0))
                os.write(master,b'\x1b[5~\x1b[6~\x1b[F');pump(.2)
                os.write(master,b'q');pump(.5)
                process.wait(timeout=5)
                self.assertEqual(process.returncode,0,output.decode(errors='replace'))
                folder=next(Path(tmp).iterdir())
                events=[json.loads(line)['event'] for file in sorted(folder.glob('*.jsonl')) for line in file.read_text().splitlines()]
                self.assertEqual(events.count('pause'),1)
                self.assertEqual(events.count('resume'),1)
                self.assertEqual(events.count('direction'),1)
                self.assertEqual(events.count('clear'),1)
                self.assertEqual(len(list(folder.iterdir())),9)
                self.assertIn('Paused',output.decode(errors='replace'))
                self.assertIn('Session saved:',output.decode(errors='replace'))
                self.assertIn('שלום',output.decode(errors='replace'))
                self.assertIn('Привет мир',output.decode(errors='replace'))
                import soundfile as sf
                total=sum(sf.info(file).duration for file in folder.glob('*.wav'))
                self.assertLess(total,2.) # More than a second of paused callbacks was discarded.
                self.assertGreater(total,.4)
            finally:
                if process.poll() is None:process.kill();process.wait()
                os.close(master)

    def test_two_quit_keys_in_one_read_cancel_pending_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            master,slave=pty.openpty()
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,110,0,0))
            process=subprocess.Popen([sys.executable,'-c',CHILD.replace('time.sleep(.03)','time.sleep(.5)'),tmp],stdin=slave,stdout=slave,stderr=slave,env=dict(os.environ,TERM='xterm-256color'))
            os.close(slave)
            try:
                time.sleep(.6);os.write(master,b'qq')
                until=time.monotonic()+5
                while process.poll() is None and time.monotonic()<until:
                    if select.select([master],[],[],.05)[0]:
                        try:os.read(master,65536)
                        except OSError:break
                process.wait(timeout=2)
                self.assertEqual(process.returncode,0)
                folder=next(Path(tmp).iterdir())
                events=[json.loads(line) for file in folder.glob('*.jsonl') for line in file.read_text().splitlines()]
                self.assertEqual(sum(e['event']=='cancel_requested' for e in events),1)
                self.assertTrue(next(e for e in events if e['event']=='finished')['cancelled'])
            finally:
                if process.poll() is None:process.kill();process.wait()
                os.close(master)

    def test_direction_after_replay_eof_cannot_change_only_the_screen(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'input.wav';sf.write(source,np.full(4800,.2,dtype=np.float32),16000)
            sessions=Path(tmp)/'sessions'
            child=CHILD.replace('time.sleep(.03)','time.sleep(1.5)').replace("command='listen',device=None)","command='benchmark',device=None,file=Path(sys.argv[2]))")
            master,slave=pty.openpty()
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,110,0,0))
            process=subprocess.Popen([sys.executable,'-c',child,str(sessions),str(source)],stdin=slave,stdout=slave,stderr=slave,env=dict(os.environ,TERM='xterm-256color'))
            os.close(slave)
            try:
                time.sleep(1.);os.write(master,b'\x14')
                until=time.monotonic()+5
                while process.poll() is None and time.monotonic()<until:
                    if select.select([master],[],[],.05)[0]:
                        try:os.read(master,65536)
                        except OSError:break
                process.wait(timeout=2);self.assertEqual(process.returncode,0)
                folder=next(sessions.iterdir())
                self.assertEqual(len(list(folder.iterdir())),5)
                events=[json.loads(line)['event'] for file in folder.glob('*.jsonl') for line in file.read_text().splitlines()]
                self.assertNotIn('direction',events)
            finally:
                if process.poll() is None:process.kill();process.wait()
                os.close(master)
