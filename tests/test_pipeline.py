import json,queue
from pathlib import Path
import tempfile
import threading
import time
import unittest
import numpy as np
from hebrew_live.cli import Inbox,Fragment,segment

class NullLog:
    debug=False
    def event(self,*a,**k):pass
    def error(self,*a,**k):pass

class PipelineTests(unittest.TestCase):
    def test_slow_inference_overload_preserves_queued_work_and_records_gap(self):
        from hebrew_live.feed import inference
        from hebrew_live.session import Session
        from hebrew_live.session_history import SessionHistory
        from hebrew_live.browser_ui import BrowserUI
        from hebrew_live.stream import Control,Settings,transfer
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{},save_audio=False)
            stop=threading.Event();errors=queue.Queue();updates=queue.Queue()
            box=Inbox(lambda f:(session.note_unprocessed_fragment(f,'translation_backlog'),stop.set()))
            class Engine:
                mx=type('MX',(),{'get_peak_memory':lambda _:0})()
                def recognize(self,audio,*args,**kwargs):
                    time.sleep(.02);self.recognition_status='accepted';self.recognition_issue=None
                    self.recognition_words=[dict(word='שלום',start=0,end=1)];return 'שלום'
                def translate(self,text):yield 'hello','stop'
            raw=queue.Queue(300);control=Control(Settings(publication='draft'),stop,session.note_accepted);control.capture_rate=16000
            consumer=threading.Thread(target=segment,args=(raw,box,lambda _:1,stop,session,errors));consumer.start()
            for _ in range(6):self.assertTrue(control.accept(np.ones(160000,dtype=np.float32),time.monotonic()))
            control.queue.put(None);transfer(control,raw,session,16000,1,consumer,errors,updates);consumer.join(3)
            self.assertTrue(box.overloaded)
            worker=threading.Thread(target=inference,args=(box,Engine(),updates,stop,errors,session));worker.start();worker.join(5)
            self.assertFalse(worker.is_alive());self.assertTrue(errors.empty(),list(errors.queue))
            folder=session.path;ui=BrowserUI(open_browser=False);ui.prepare_exports(session)
            manifest=json.loads((folder/'session.json').read_text())
            self.assertTrue(manifest['partial']);self.assertEqual(manifest['accepted']['1']['duration'],60)
            self.assertEqual(manifest['known_unprocessed'][0]['reason'],'translation_backlog')
            self.assertGreater(manifest['known_unprocessed'][0]['end'],manifest['known_unprocessed'][0]['start'])
            archived=SessionHistory(folder.parent).read(folder.name)
            self.assertTrue(archived['partial']);self.assertEqual(archived['partial_kind'],'known_unprocessed')
            self.assertEqual(archived['partial_details'][0]['reason'],'translation_backlog')
            self.assertEqual(archived['partial_details'][0]['direction'],'he-ru')
            self.assertTrue(ui.state['partial']);self.assertTrue(ui.state['partial_ranges'])
            self.assertEqual(ui.state['partial_details'][0]['part'],1)
    def test_preview_replaced_final_first(self):
        box=Inbox()
        a=lambda rev,final:Fragment(1,rev,None,0,0,final)
        box.put(a(1,False));box.put(a(2,False));box.put(a(3,True));box.finish()
        self.assertEqual(box.get().revision,3);self.assertIsNone(box.get())
    def test_bounded_final_queue(self):
        rejected=[];box=Inbox(rejected.append)
        for i in range(4):box.put(Fragment(i,1,None,0,0,True))
        self.assertFalse(box.put(Fragment(4,1,None,0,0,True)))
        self.assertTrue(box.overloaded);self.assertEqual(rejected[0].id,4)
    def test_silence_produces_no_fragments(self):
        raw=queue.Queue();box=Inbox();errors=queue.Queue()
        raw.put((np.zeros(16000,dtype=np.float32),1));raw.put(None)
        segment(raw,box,lambda f:0,threading.Event(),NullLog(),errors)
        self.assertTrue(errors.empty());self.assertIsNone(box.get())
    def test_speech_finalized_at_eof(self):
        raw=queue.Queue();box=Inbox();errors=queue.Queue()
        raw.put((np.ones(16000,dtype=np.float32),1));raw.put(None)
        segment(raw,box,lambda f:1,threading.Event(),NullLog(),errors)
        self.assertTrue(errors.empty());self.assertTrue(box.get().final);self.assertIsNone(box.get())

if __name__=='__main__':unittest.main()

class UXTests(unittest.TestCase):
    def test_final_supersedes_active_preview(self):
        box=Inbox();f=Fragment(1,1,None,0,0,False)
        box.put(Fragment(1,2,None,0,0,True))
        self.assertTrue(box.superseded(f))
        self.assertFalse(box.superseded(box.get()))
    def test_wrap_resizes_without_losing_history(self):
        from hebrew_live.cli import TranslationScreen
        screen=TranslationScreen();screen.finalize('Длинная фраза '*100)
        self.assertGreater(len(screen.lines(32)),len(screen.lines(64)))
        self.assertEqual(len(screen.history),1)
    def test_cancel_skips_pending_inference(self):
        from hebrew_live.feed import inference
        box=Inbox();box.put(Fragment(1,1,None,0,0,True));box.finish()
        cancel=threading.Event();cancel.set();updates=queue.Queue();errors=queue.Queue()
        inference(box,object(),updates,threading.Event(),errors,NullLog(),cancel)
        self.assertTrue(errors.empty())
        self.assertEqual(updates.get()[0],'done')


class UnifiedCaptionTests(unittest.TestCase):
    def test_confirmation_changes_color_not_position(self):
        from rich.console import Console
        from hebrew_live.cli import TranslationScreen
        screen=TranslationScreen();screen.history.append('Первая фраза.')
        screen.preview='Следующее предложение достаточно длинное, чтобы переноситься.'
        console=Console(width=32)
        before=screen.caption()
        before_lines=[x.plain for x in before.wrap(console,32)]
        self.assertTrue(any(str(span.style)=='yellow' for span in before.spans))
        screen.finalize(screen.preview)
        after=screen.caption()
        self.assertEqual(before.plain,after.plain)
        self.assertEqual(before_lines,[x.plain for x in after.wrap(console,32)])
        self.assertFalse(any(str(span.style)=='yellow' for span in after.spans))
        self.assertEqual(str(after.style),'white')
    def test_draft_is_inline_and_final_history_is_preserved(self):
        from hebrew_live.cli import TranslationScreen
        screen=TranslationScreen()
        for i in range(10):screen.finalize(str(i)+'.')
        screen.preview='Новая фраза'
        self.assertEqual(screen.caption().plain,'\n\n'.join(str(i)+'.' for i in range(10))+'\n\nНовая фраза')
