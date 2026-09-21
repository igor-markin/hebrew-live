import queue,threading,unittest
import numpy as np
from hebrew_live.cli import Inbox,segment
from hebrew_live.display import TranslationScreen,sentence_layout
from hebrew_live.stream import Settings
class Log:
    def event(self,*a,**k):pass
    def error(self,*a,**k):pass
class ContextTests(unittest.TestCase):
    def test_hesitations_remain_one_utterance_even_after_four_seconds(self):
        # "I ... speak ... English": pauses of 0.8 seconds must remain revisable.
        samples=np.concatenate([np.ones(16000*2),np.zeros(12800),np.ones(16000*2),
                                np.zeros(12800),np.ones(16000),np.zeros(24000)]).astype('float32')
        raw=queue.Queue();raw.put((samples,len(samples)/16000));raw.put(None)
        box=Inbox();errors=queue.Queue()
        segment(raw,box,lambda f:float(f.max()>0),threading.Event(),Log(),errors)
        self.assertTrue(errors.empty())
        finals=[]
        while (f:=box.get()) is not None:
            if f.final:finals.append(f)
        self.assertEqual(len(finals),1)
        self.assertEqual(int((finals[0].audio>0).sum()),80000)
    def test_ellipsis_does_not_end_a_sentence(self):
        self.assertEqual(sentence_layout('Я… говорю по-английски. И я... могу.')[0],
                         'Я… говорю по-английски.\n\nИ я... могу.')
class OriginalDisplayTests(unittest.TestCase):
    def screen(self):
        s=TranslationScreen(native_bidi=False);s.update('context',1,Settings())
        s.update('source',1,'שלום חברים')
        s.update('preview',1,'Здравствуйте, друзья.')
        return s
    def test_source_immediate_translation_whole_and_confirmation(self):
        s=self.screen()
        self.assertIn('שלום חברים',s.plain())
        self.assertIn('Здравствуйте',s.plain())
        self.assertTrue(any(str(span.style)=='dim' for line in s.lines(110) for span in line.spans))
        self.assertTrue(any(str(span.style)=='yellow' for line in s.lines(110) for span in line.spans))
        s.update('source',1,'שלום חברים אני איגור')
        self.assertEqual(s.preview,'Здравствуйте, друзья.')
        self.assertEqual(s.source_preview,'שלום חברים') # Keep a matched pair, no blank flicker.
        s.update('final',1,'Здравствуйте, друзья. Я Игорь.')
        self.assertEqual(s.source_history,['שלום חברים אני איגור'])
        self.assertNotIn('черновик',s.plain())
        self.assertTrue(any(str(span.style)=='yellow' for line in s.lines(110) for span in line.spans))
    def test_clear_hides_late_source_and_final_but_accepts_new_generation(self):
        s=self.screen();s.clear(1)
        s.update('source',1,'старый оригинал');s.update('final',1,'старый перевод')
        self.assertFalse(s.has_sources);self.assertEqual(s.history,[])
        s.update('context',2,Settings(generation=1));s.update('source',2,'новый')
        s.update('final',2,'חדש')
        self.assertEqual(s.source_history,['новый']);self.assertEqual(s.history,['חדש'])
    def test_wide_narrow_resize_and_scroll_keep_all_pairs(self):
        s=self.screen();s.update('final',1,'Здравствуйте, друзья.')
        wide='\n'.join(line.plain for line in s.lines(110))
        narrow='\n'.join(line.plain for line in s.lines(40))
        self.assertNotIn(' │ ',wide);self.assertNotIn(' │ ',narrow)
        for width in (40,110):
            rows=s.lines(width)
            source_index=next(i for i,row in enumerate(rows) if 'םולש' in row.plain)
            self.assertIn('Здравствуйте',rows[source_index+2].plain)
        for i in range(12):
            s.finalize('Длинный перевод '+str(i),'מקור ארוך '+str(i))
        s.scroll(-100,110,5);top=s.top
        s.finalize('Ещё перевод','עוד מקור')
        self.assertEqual(s.top,top)
        self.assertEqual(len(s.history),14);self.assertEqual(len(s.source_history),14)
        self.assertIn('מקור ארוך 11',s.plain())

class NativeRTLTests(unittest.TestCase):
    def test_apple_terminal_receives_logical_hebrew_once_and_right_aligned(self):
        from unittest.mock import patch
        with patch.dict('os.environ',{'TERM_PROGRAM':'Apple_Terminal'}):
            s=TranslationScreen()
        source='שלום איגור 2026'
        s.update('source',1,source);s.update('preview',1,'Привет, Игорь 2026.')
        for width in (40,79,110):
            rows=s.lines(width)
            source_row=next(r.plain for r in rows if source in r.plain)
            self.assertIn(source,source_row)
            cell=min(width,88)
            self.assertEqual(source_row.index(source)+len(source),cell)
            self.assertNotIn('6202',source_row)
        self.assertNotIn(' │ ','\n'.join(r.plain for r in s.lines(79)))

    def test_non_native_terminal_still_gets_visual_order(self):
        from rich.text import Text
        from hebrew_live.display import visual_line
        s=TranslationScreen(native_bidi=False)
        s.update('source',1,'שלום איגור 2026')
        s.update('preview',1,'Привет.')
        expected=visual_line(Text('שלום איגור 2026'))[0].plain
        self.assertTrue(any(expected in row.plain for row in s.lines(79)))
        self.assertIn('2026',expected)

    def test_runs_do_not_overpaint_rtl_and_preserve_color(self):
        from rich.text import Text
        from hebrew_live.display import style_runs
        t=Text('שלום 2026 │ Перевод',style='white')
        t.stylize('dim',0,11);t.stylize('yellow',12,len(t.plain))
        runs=style_runs(t)
        self.assertEqual(''.join(t.plain[a:b] for a,b,_ in runs),t.plain)
        self.assertEqual(sum(b-a for a,b,_ in runs),len(t.plain))
        self.assertEqual(runs[0],(0,11,'dim'))

    def test_revision_replaces_both_texts_together_without_empty_frame(self):
        s=TranslationScreen(native_bidi=True)
        s.update('source',1,'שלום');s.update('preview',1,'Привет.')
        before=[r.plain for r in s.lines(79)]
        s.update('source',1,'שלום חברים')
        self.assertEqual(before,[r.plain for r in s.lines(79)])
        s.update('preview',1,'Привет, друзья.')
        self.assertEqual(s.source_preview,'שלום חברים')
        before=[r.plain for r in s.lines(79)]
        s.update('final',1,'Привет, друзья.')
        self.assertEqual(s.draft_history,['Привет, друзья.'])
        self.assertEqual(sum('Привет, друзья.' in r.plain for r in s.lines(79)),2)
