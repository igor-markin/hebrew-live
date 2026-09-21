import queue
import threading
import unittest
import numpy as np
from hebrew_live.cli import Inbox,Fragment,segment

class NullLog:
    debug=False
    def event(self,*a,**k):pass
    def error(self,*a,**k):pass

class PipelineTests(unittest.TestCase):
    def test_preview_replaced_final_first(self):
        box=Inbox()
        a=lambda rev,final:Fragment(1,rev,None,0,0,final)
        box.put(a(1,False));box.put(a(2,False));box.put(a(3,True));box.finish()
        self.assertEqual(box.get().revision,3);self.assertIsNone(box.get())
    def test_bounded_final_queue(self):
        box=Inbox()
        for i in range(4):box.put(Fragment(i,1,None,0,0,True))
        with self.assertRaises(RuntimeError):box.put(Fragment(4,1,None,0,0,True))
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
