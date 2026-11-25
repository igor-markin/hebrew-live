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
    def test_slow_inference_overload_skips_the_oldest_phrases_and_records_the_gap(self):
        from hebrew_live.feed import inference
        from hebrew_live.session import Session
        from hebrew_live.session_history import SessionHistory
        from hebrew_live.browser_ui import BrowserUI
        from hebrew_live.stream import Control,Settings,transfer
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(Path(tmp),'he-ru',{},save_audio=False)
            stop=threading.Event();errors=queue.Queue();updates=queue.Queue()
            box=Inbox(lambda f:session.note_unprocessed_fragment(f,'translation_backlog'))
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
            self.assertTrue(box.overloaded);self.assertFalse(stop.is_set())
            self.assertFalse(session.stop_is_explained())
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
    def test_full_final_queue_skips_the_oldest_phrase_and_keeps_accepting(self):
        skipped=[];box=Inbox(skipped.append)
        for i in range(4):box.put(Fragment(i,1,np.zeros(16),0,0,True))
        self.assertFalse(box.overloaded)
        for i in (4,5):self.assertTrue(box.put(Fragment(i,1,np.zeros(16),0,0,True)))
        self.assertTrue(box.overloaded);self.assertEqual([f.id for f in skipped],[0,1])
        self.assertEqual([box.get().id for _ in range(4)],[2,3,4,5])
    def test_full_final_queue_never_skips_a_boundary(self):
        from hebrew_live.stream import Boundary,Settings
        skipped=[];box=Inbox(skipped.append);boundary=Boundary(Settings(),'pause')
        box.put_boundary(boundary)
        for i in range(5):box.put(Fragment(i,1,np.zeros(16),0,0,True))
        self.assertEqual([f.id for f in skipped],[0])
        self.assertIs(box.get(),boundary);self.assertEqual([box.get().id for _ in range(4)],[1,2,3,4])
    def test_overload_does_not_stop_the_segmenter(self):
        raw=queue.Queue();skipped=[];box=Inbox(skipped.append);errors=queue.Queue();stop=threading.Event()
        # 60 s of unbroken speech with nobody consuming: a final every 10 s window.
        for _ in range(6):raw.put((np.ones(160000,dtype=np.float32),1))
        raw.put(None);segment(raw,box,lambda f:1,stop,NullLog(),errors)
        self.assertFalse(stop.is_set());self.assertTrue(errors.empty())
        self.assertTrue(box.overloaded);self.assertTrue(skipped)
        self.assertEqual(len(box.pending_fragments()),4)
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
    def test_quiet_speech_reaches_vad_amplified_and_recognition_unchanged(self):
        from hebrew_live.cli import VAD_INPUT_GAIN
        raw=queue.Queue();box=Inbox();errors=queue.Queue();seen=[]
        def vad(frame):
            seen.append(float(np.abs(frame).max()));return float(seen[-1]>=.3)
        raw.put((np.full(16000,.06,dtype=np.float32),1));raw.put(None)
        segment(raw,box,vad,threading.Event(),NullLog(),errors)
        self.assertTrue(errors.empty())
        self.assertAlmostEqual(seen[0],.06*VAD_INPUT_GAIN,places=5)
        fragment=box.get();self.assertTrue(fragment.final)
        self.assertAlmostEqual(float(np.abs(fragment.audio).max()),.06,places=6)
    def background_run(self, pattern, background=True):
        """pattern: one VAD answer per 32 ms frame; frame n holds the value n."""
        from hebrew_live.stream import AudioBlock, Settings
        raw=queue.Queue();errors=queue.Queue();out=[]
        class Box:
            put=staticmethod(out.append)
            def put_boundary(self,b):out.append(b)
            def finish(self):pass
        settings=Settings(publication='draft',timing=(.7,.7,0,4.,.6))
        answers=iter(pattern)
        data=np.repeat(np.arange(len(pattern),dtype=np.float32),512)
        raw.put(AudioBlock(data,1.,len(data)/16000,settings));raw.put(None)
        segment(raw,Box(),lambda f:next(answers),threading.Event(),NullLog(),errors,background)
        self.assertTrue(errors.empty(),list(errors.queue))
        return out
    def test_audio_between_segments_is_passed_on_as_background_and_lead(self):
        out=self.background_run([0]*60+[1]*10)
        gaps=[f for f in out if f.reason=='background'];speech=[f for f in out if f.reason!='background']
        self.assertTrue(gaps);self.assertFalse(any(f.final for f in gaps))
        self.assertEqual(gaps[-1].audio[0],0.)
        first=speech[0]
        joined=np.concatenate([first.lead,first.audio])
        # every frame once, in order: nothing is lost between the lead and the pre-roll
        self.assertEqual(list(joined[::512][:60]),list(range(60)))
        self.assertEqual(round(first.offset*16000)-len(joined),0)
    def test_the_lead_does_not_repeat_after_the_segment_ends(self):
        out=self.background_run([0]*60+[1]*10+[0]*20+[1]*10)
        second=[f for f in out if f.reason!='background'][-1]
        if second.lead is not None:self.assertGreaterEqual(second.lead[0],70.)
    def test_without_background_nothing_changes(self):
        out=self.background_run([0]*60+[1]*10,background=False)
        self.assertFalse([f for f in out if f.reason=='background']);self.assertIsNone(out[0].lead)
    def test_background_of_old_settings_is_dropped_at_their_boundary(self):
        box=Inbox();box.put(Fragment(0,1,np.zeros(16),0,0,False,None,0.,0.,'background'))
        box.put_boundary('boundary');box.finish()
        self.assertEqual(box.get(),'boundary');self.assertIsNone(box.get())
    def test_loud_speech_is_clipped_only_for_vad(self):
        raw=queue.Queue();box=Inbox();errors=queue.Queue();seen=[]
        def vad(frame):
            seen.append(float(np.abs(frame).max()));return 1.
        raw.put((np.full(16000,.8,dtype=np.float32),1));raw.put(None)
        segment(raw,box,vad,threading.Event(),NullLog(),errors)
        self.assertTrue(errors.empty());self.assertEqual(max(seen),1.)
        self.assertAlmostEqual(float(np.abs(box.get().audio).max()),.8,places=6)

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
