import os,queue,threading,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from hebrew_live.cli import Fragment
from hebrew_live.retranslation import RetranslationProcessor
from hebrew_live.sentence_freeze import pair_finished,sentence_start,split_sentences,tail_after,target_cut
from hebrew_live.stream import Settings
from hebrew_live.translation import prompt


class HelperTests(unittest.TestCase):
 def test_split_keeps_numbers_and_unfinished_tail(self):
  self.assertEqual(split_sentences('יש לי 50,000 שקל. זה 2.5 אחוז? ואז'),['יש לי 50,000 שקל.','זה 2.5 אחוז?','ואז'])
  self.assertEqual(split_sentences('Он сказал «да». Потом'),['Он сказал «да».','Потом'])
 def test_tail_after_exact_and_reworded_prefix(self):
  self.assertEqual(tail_after('שלום לכם.','שלום לכם. מה שלומכם'),'מה שלומכם')
  self.assertEqual(tail_after('אני לא יכול להשיג את הכסף.','אני לא יכולה להשיג כסף. מהבנק שלי'),'מהבנק שלי')
  self.assertEqual(tail_after('','א ב'),'א ב')
  self.assertEqual(tail_after('א ב ג.','א ב ג.'),'')
 def test_pair_finished_counts_sentences_followed_by_speech(self):
  self.assertEqual(pair_finished('א. ב. ג',False)[0],2)
  self.assertEqual(pair_finished('א.',False)[0],0)
  self.assertEqual(pair_finished('א. ב',True)[0],2)
 def test_target_cut_pairs_one_to_one_or_by_text_share(self):
  self.assertEqual(target_cut(['א.','ב.','ג'],['A.','B.','C'],2),2)
  self.assertIsNone(target_cut(['א.','ב'],['A','B'],1))
  sources=['אחת שתיים שלוש ארבע חמש.','שש שבע שמונה תשע עשר']
  self.assertEqual(target_cut(sources,['11.','One two three four five.','Six seven eight nine ten'],1),2)
  self.assertIsNone(target_cut(sources,['One.','Two.','Three four five six seven eight nine ten'],1))
 def test_sentence_start(self):
  self.assertEqual(sentence_start('деньги придут','Готово.'),'Деньги придут')
  self.assertEqual(sentence_start('и деньги','потому что'),'и деньги')
  self.assertEqual(sentence_start(', 11. Ого','Спасибо.'),'11. Ого')
 def test_prompt_forces_shown_translation_as_answer_start(self):
  tokenizer=SimpleNamespace(encode=lambda text,add_special_tokens=False:text)
  text=prompt(tokenizer,'milmmt','ב','he-ru',pairs=(('א.','А.'),))
  self.assertTrue(text.endswith('Hebrew: א. ב\nRussian: А.'),text)
  self.assertNotIn('Background',text)


class FreezeTests(unittest.TestCase):
 def setUp(self):
  self.mt=[];self.contexts=[];self.results=[]
  self.e=SimpleNamespace(recognize=self.recognize,translate=self.translate,accepts_context=True)
  self.q=queue.Queue()
  self.log=SimpleNamespace(event=lambda name,**v:None)
  self.p=RetranslationProcessor(self.e,self.q,self.log,threading.Event())
  self.settings=Settings(publication='draft');self.audio=np.zeros(2000000,dtype=np.float32)
 def recognize(self,a,*args,**kw):
  self.text,self.target=self.results.pop(0);self.e.recognition_status='accepted';return self.text
 def translate(self,text,context=()):
  self.mt.append(text);self.contexts.append(list(context));yield self.target,'stop'
 def step(self,end,text,target,final=False,start=0):
  self.results.append((text,target))
  self.p.process(Fragment(1,1,self.audio[start:end],0,time.monotonic(),final,self.settings,end/16000,0,'silence' if final else ''))
 def shown(self):return [v['current']['translation'] for k,_,v in self.q.queue if k=='live_publication']
 def test_finished_sentence_stays_and_only_the_tail_is_translated(self):
  self.step(8000,'א.','A.')
  self.step(16000,'א. ב','A. B')
  self.step(32000,'אא. ב ג','unused. B C')  # ASR rewords the first sentence: it is not sent again.
  self.assertEqual(self.mt,['א.','א. ב','ב ג'])
  self.assertEqual(self.contexts[-1],[('א.','A.')])
  self.assertEqual(self.shown()[-1],'A. unused. B C')
 def test_tail_translation_keeps_frozen_prefix_on_screen(self):
  self.step(8000,'א.','A.')
  self.step(16000,'א. ב','A. B')
  self.step(32000,'א. ב ג','B C')
  self.step(48000,'א. ב ג. ד','B C. D')
  self.assertEqual(self.shown(),['','A.','A. B','A. B C','A. B C. D'])
  self.assertTrue(all(text.startswith('A.') for text in self.shown()[1:]))
 def test_streaming_preview_starts_with_frozen_sentences(self):
  self.step(8000,'א.','A.')
  self.step(16000,'א. ב','A. B')
  self.results.append(('א. ב ג','unused'))
  self.e.translate=lambda text,context=():iter([('B ',None),('C.','stop')])
  with patch('hebrew_live.retranslation.STREAM_PREVIEW_INTERVAL',0):
   self.p.process(Fragment(1,2,self.audio[:32000],0,time.monotonic(),False,self.settings,2.,0,''))
  streams=[v['translation'] for k,_,v in self.q.queue if k=='live_stream']
  self.assertEqual(streams,['A. B'])
  self.assertEqual(self.shown()[-1],'A. B C.')
 def test_closing_freezes_everything_and_carries_context_to_the_next_group(self):
  self.step(8000,'א.','A.')
  self.step(16000,'א. ב','A. B')
  self.step(32000,'א. ב.','B.',final=True)
  self.assertEqual(self.shown()[-1],'A. B.')
  self.step(48000,'ג','c',start=32000)
  self.assertEqual(self.contexts[-1],[('א.','A.'),('ב.','B.')])
  self.assertEqual(self.shown()[-1],'C')
 def test_nothing_new_after_frozen_sentences_publishes_nothing(self):
  self.step(8000,'א.','A.')
  self.step(16000,'א. ב','A. B')
  count=len(self.shown())
  self.step(32000,'א.','unused')
  self.assertEqual(len(self.shown()),count);self.assertEqual(len(self.mt),2)
 def test_sentence_changed_by_the_next_recognition_is_not_frozen(self):
  self.step(8000,'א.','A.')
  self.step(16000,'אב. ג','AB. C')
  self.step(24000,'אב. ג ד','AB. C D')  # Same first sentence twice: frozen now.
  self.step(32000,'אב. ג ד ה','C D E')
  self.assertEqual(self.mt,['א.','אב. ג','אב. ג ד','ג ד ה'])
  self.assertEqual(self.shown()[-1],'AB. C D E')
 def test_sentence_agreeing_with_an_earlier_recognition_is_frozen(self):
  self.step(8000,'א.','A.')
  self.step(16000,'אא. ב','X. B')
  self.step(24000,'א. ב ג','A. B C')  # Agrees with the first recognition, not the second.
  self.step(32000,'א. ב ג ד','B C D')
  self.assertEqual(self.mt[-1],'ב ג ד')
 def test_no_context_after_a_pause(self):
  self.step(16000,'א.','A.',final=True)
  self.step(16000*6,'ב','b',start=16000*5)
  self.assertEqual(self.contexts[-1],[])
  self.assertEqual(self.shown()[-1],'b')
 def test_switch_restores_whole_group_translation(self):
  with patch.dict(os.environ,{'HEBREW_LIVE_FREEZE_SENTENCES':'0'}):
   self.p=RetranslationProcessor(self.e,self.q,self.log,threading.Event())
  self.step(16000,'א. ב','A. B');self.step(32000,'אא. ב ג','X. B C')
  self.assertEqual(self.mt,['א. ב','אא. ב ג']);self.assertEqual(self.shown()[-1],'X. B C')
 def test_preview_never_replaces_a_longer_visible_version(self):
  self.step(16000,'א ב','Длинный видимый перевод')
  self.results.append(('א ב ג','unused'))
  self.e.translate=lambda text,context=():iter([('Ко ',None),('ро ',None),('Длинный видимый перевод и ещё ',None),('слово.','stop')])
  with patch('hebrew_live.retranslation.STREAM_PREVIEW_INTERVAL',0):
   self.p.process(Fragment(1,2,self.audio[:32000],0,time.monotonic(),False,self.settings,2.,0,''))
  streams=[v['translation'] for k,_,v in self.q.queue if k=='live_stream']
  self.assertTrue(streams and all(len(text)>=len('Длинный видимый перевод') for text in streams),streams)
