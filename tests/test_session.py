import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf
from hebrew_live.cli import Fragment, Inbox, segment
from hebrew_live.feed import inference
from hebrew_live.display import TranslationScreen, sentence_layout
from hebrew_live.session import Session
from hebrew_live.stream import Settings, Control, Boundary, AudioBlock, transfer, replay


class SessionTests(unittest.TestCase):
    def test_retry_request_is_revalidated_after_browser_admission(self):
        from hebrew_live.runtime import retry_request_current
        stop=threading.Event();cancel=threading.Event();control=Control(Settings(),stop);control.paused=True
        session=SimpleNamespace(path=Path('/tmp/current-session'))
        request=dict(group='0:3000001',start=1.25,end=2.5,part=1,direction='he-ru',session=str(session.path),generation=4)
        group=dict(id=request['group'],part=1,direction='he-ru',complete=True,
                   live=dict(issue='Ошибка',start=1.25,end=2.5))
        browser=SimpleNamespace(lock=threading.RLock(),state=dict(session=str(session.path),retrying_group=request['group'],
            finished=False,stopping=False,model_switching=False,paused=True,generation=4,groups=[group]))
        self.assertTrue(retry_request_current(request,session,control,browser,stop,cancel,False))
        browser.state['paused']=False
        self.assertFalse(retry_request_current(request,session,control,browser,stop,cancel,False))
        browser.state['paused']=True;browser.state['groups']=[]
        self.assertFalse(retry_request_current(request,session,control,browser,stop,cancel,False))
        browser.state['groups']=[group];stop.set()
        self.assertFalse(retry_request_current(request,session,control,browser,stop,cancel,False))

    def test_retry_audio_reads_original_range_as_16khz_mono_without_modifying_wav(self):
        from hebrew_live.runtime import read_retry_audio
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{});part=session.parts[1]
            original=np.column_stack((np.linspace(-.2,.2,48000,dtype=np.float32),np.linspace(.2,-.2,48000,dtype=np.float32)))
            part.write_audio(original,48000);before=part.audio_path.stat().st_size
            retry=read_retry_audio(part,.25,.5)
            self.assertEqual(len(retry),4000);self.assertEqual(retry.ndim,1)
            self.assertEqual(part.audio_path.stat().st_size,before)
            session.close()

    def test_real_transfer_pause_switch_clear_and_final_files(self):
        """Default recording + resampling + segmentation + inference, fake ML only."""
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{})
            stop=threading.Event();control=Control(Settings(),stop)
            raw=queue.Queue(300);box=Inbox();updates=queue.Queue();errors=queue.Queue()
            calls=[]
            class FakeEngine:
                mx=type('MX',(),{'get_peak_memory':lambda:0})
                def recognize(self,a,p,**kw):
                    calls.append((self.language,self.direction))
                    text='שלום' if self.language=='he' else 'Привет'
                    self.recognition_words=[dict(word=text,start=0,end=len(a)/16000)]
                    return text
                def translate(self,text):yield ('Привет.' if self.direction=='he-ru' else 'שלום.'),'stop'
            class VAD:
                def __call__(self,a):return 1
                def reset(self):pass
            consumer=threading.Thread(target=segment,args=(raw,box,VAD(),stop,session,errors))
            infer=threading.Thread(target=inference,args=(box,FakeEngine(),updates,stop,errors,session))
            consumer.start();infer.start()
            writer=threading.Thread(target=transfer,args=(control,raw,session,48000,1,consumer,errors,updates));writer.start()
            control.accept(np.full(4800,.1,dtype=np.float32),time.monotonic())
            self.assertTrue(control.key(' ',1))
            self.assertFalse(control.accept(np.full(4800,.9,dtype=np.float32),time.monotonic()))
            self.assertTrue(control.key('\x14',2)) # Direction while paused.
            self.assertTrue(control.key(' ',3))
            control.accept(np.full(4800,.2,dtype=np.float32),time.monotonic())
            self.assertTrue(control.key('\x0c',4))
            control.accept(np.full(4800,.3,dtype=np.float32),time.monotonic())
            self.assertTrue(control.key('\x14',5))
            control.accept(np.full(4800,.4,dtype=np.float32),time.monotonic())
            control.queue.put(None)
            for t in (writer,consumer,infer):t.join(5);self.assertFalse(t.is_alive())
            self.assertTrue(errors.empty(), list(errors.queue))
            folder=session.path;session.close()
            self.assertEqual(len(list(folder.iterdir())),12)
            for number,expected in ((1,[.1]),(2,[.2,.3]),(3,[.4])):
                wav=next(folder.glob(f'{number:03d}-*.wav'))
                data,rate=sf.read(wav)
                self.assertEqual(rate,48000)
                np.testing.assert_allclose(data,np.repeat(expected,4800),atol=1e-6)
                self.assertEqual(os.stat(wav).st_mode & 0o777,0o600)
            self.assertEqual(os.stat(folder).st_mode & 0o777,0o700)
            source=(folder/'002-ru-he.transcript.txt').read_text()
            self.assertEqual(source.count('Привет'),2)
            self.assertIn('0.000–0.100s',source)
            self.assertIn('0.100–0.200s',source)
            self.assertEqual(calls,[('he','he-ru'),('ru','ru-he'),('ru','ru-he'),('he','he-ru')])
            self.assertIn('שלום.',(folder/'002-ru-he.translation.txt').read_text())

    def test_failed_translation_keeps_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{})
            box=Inbox();box.put(Fragment(1,1,np.ones(1600),0,time.monotonic(),True,Settings(),.1));box.finish()
            class Engine:
                def recognize(self,*a,**kw):
                    self.recognition_words=[dict(word='מקור',start=0,end=.1)]
                    return 'מקור'
                def translate(self,*a):raise RuntimeError('fake failure')
            errors=queue.Queue()
            inference(box,Engine(),queue.Queue(),threading.Event(),errors,session)
            folder=session.path;session.close()
            self.assertFalse(errors.empty())
            self.assertIn('מקור',(folder/'001-he-ru.transcript.txt').read_text())
            self.assertIn('Ошибка перевода',(folder/'001-he-ru.translation.txt').read_text())

    def test_disk_failure_stops_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{})
            stop=threading.Event();control=Control(Settings(),stop);errors=queue.Queue()
            class Consumer:
                def is_alive(self):return True
            control.accept(np.ones(1600,dtype=np.float32),time.monotonic())
            raw=queue.Queue()
            with patch.object(session.parts[1],'write_audio',side_effect=OSError('disk full')):
                transfer(control,raw,session,16000,1,Consumer(),errors,queue.Queue())
            self.assertTrue(stop.is_set());self.assertFalse(errors.empty());self.assertIsNone(raw.get())
            session.close()

    def test_empty_session_wav_and_no_duplicate_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{})
            part=session.parts[1];f=Fragment(1,1,np.zeros(160),0,0,True,Settings(),.01)
            part.text('source',f,'once');part.text('source',f,'twice')
            folder=session.path;session.close()
            self.assertEqual(sf.info(folder/'001-he-ru.audio.wav').frames,0)
            self.assertNotIn('twice',(folder/'001-he-ru.transcript.txt').read_text())


class ControlTests(unittest.TestCase):
    def test_key_repeat_burst_cannot_resume(self):
        control=Control(Settings(),threading.Event())
        self.assertTrue(control.key(' ',1))
        for t in np.arange(1.01,4,.04):self.assertFalse(control.key(' ',float(t)))
        self.assertTrue(control.paused)
        self.assertTrue(control.key(' ',5));self.assertFalse(control.paused)

    def test_full_queue_does_not_commit_switch(self):
        control=Control(Settings(),threading.Event())
        for i in range(300):control.queue.put(i)
        with self.assertRaises(queue.Full):control.key('\x14')
        self.assertEqual(control.settings.direction,'he-ru')

    def test_clear_rejects_late_result_without_clearing_persistence(self):
        screen=TranslationScreen();screen.update('context',1,Settings())
        screen.update('preview',1,'Старый текст')
        screen.clear(1);screen.update('final',1,'Старый текст')
        self.assertEqual(screen.history,[]);self.assertEqual(screen.preview,'')
        screen.update('context',2,Settings(generation=1));screen.update('final',2,'Новый текст')
        self.assertEqual(screen.history,['Новый текст'])

    def test_replay_does_not_read_while_paused(self):
        control=Control(Settings(),threading.Event());control.key(' ',1)
        class File:
            samplerate=100
            reads=0
            def read(self,*a,**kw):
                self.reads+=1
                return np.ones((10,1),dtype=np.float32) if self.reads<3 else np.empty((0,1))
        file=File();thread=threading.Thread(target=replay,args=(file,control));thread.start()
        time.sleep(.12);self.assertEqual(file.reads,0)
        control.key(' ',2);thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(file.reads,3)

    def test_sentence_boundaries(self):
        text='Цена 3.14 руб. Адрес: ул. Герцля, д. 5. «Готово!» Следующий вопрос? Да.'
        result,_=sentence_layout(text)
        self.assertIn('3.14 руб. Адрес',result)
        self.assertIn('ул. Герцля, д. 5.\n\n«Готово!»\n\nСледующий вопрос?\n\nДа.',result)
        result,_=sentence_layout('Это т. е. пример. שלום! מה נשמע?')
        self.assertEqual(result,'Это т. е. пример.\n\nשלום!\n\nמה נשמע?')

class ScriptAndDisplayTests(unittest.TestCase):
    def test_hebrew_visual_cells_keep_numbers_and_draft_color(self):
        from rich.text import Text
        from bidi.algorithm import get_display
        from hebrew_live.display import visual_line
        logical=Text('שלום 12 ',style='white');logical.append('Привет',style='yellow')
        visual,rtl=visual_line(logical)
        self.assertTrue(rtl)
        self.assertEqual(visual.plain,get_display(logical.plain))
        self.assertIn('12',visual.plain)
        yellow=''.join(visual.plain[s.start:s.end] for s in visual.spans if str(s.style)=='yellow')
        self.assertEqual(yellow,'Привет')
        self.assertEqual(logical.plain,'שלום 12 Привет')

    def test_wrong_script_rejected_and_not_translated(self):
        from hebrew_live.cli import Engine
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'ru-he',{})
            engine=Engine.__new__(Engine)
            from unittest.mock import Mock
            engine.language_guard=Mock();engine.language_guard.reject.return_value=None
            engine.language='ru';engine.asr_path='fake';engine.log=session
            class ASR:
                @staticmethod
                def transcribe(*a,**kw):
                    assert kw['language']=='ru'
                    return {'language':'ru','segments':[{'words':[{'start':0,'end':.1,'word':' שלום'}]}]}
            engine.asr=ASR()
            box=Inbox();box.put(Fragment(1,1,np.ones(3200),0,time.monotonic(),True,Settings(direction='ru-he',language='ru'),.2));box.finish()
            errors=queue.Queue();updates=queue.Queue()
            inference(box,engine,updates,threading.Event(),errors,session)
            folder=session.path;session.close()
            self.assertTrue(errors.empty(),list(errors.queue))
            self.assertIn('Речь не распознана',(folder/'001-ru-he.transcript.txt').read_text())
            self.assertIn('שלום',engine.raw_recognition)
            self.assertIn('ASR returned Hebrew',(folder/'001-ru-he.diagnostics.jsonl').read_text())
            self.assertIn('Речь не распознана',(folder/'001-ru-he.translation.txt').read_text())

    def test_library_diagnostics_share_fourth_file_without_arbitrary_text(self):
        import logging
        from hebrew_live.session import LibraryHandler
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{});handler=LibraryHandler(session)
            handler.emit(logging.LogRecord('test',logging.WARNING,'module.py',4,'Secret input: %s',('private utterance',),None))
            folder=session.path;session.close()
            self.assertEqual(len(list(folder.iterdir())),4)
            text=(folder/'001-he-ru.diagnostics.jsonl').read_text()
            self.assertIn('"event": "library"',text)
            self.assertNotIn('private utterance',text)
