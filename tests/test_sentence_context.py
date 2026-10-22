import queue,threading,time,unittest
from types import SimpleNamespace
import numpy as np
from hebrew_live.cli import Fragment
from hebrew_live.stream import Settings
from hebrew_live.retranslation import RetranslationProcessor,technical_cut,number_word,leading_words
from hebrew_live.translation import prompt


def words(text,start,end):
 parts=text.split();step=(end-start)/len(parts)
 return [dict(word=' '+w,start=start+i*step,end=start+(i+.8)*step) for i,w in enumerate(parts)]


class SentenceContextTests(unittest.TestCase):
 def setUp(self):
  self.events=[];self.calls=[];self.mt=[]
  self.e=SimpleNamespace(recognize=self.recognize,translate=self.translate,accepts_context=True)
  self.q=queue.Queue()
  part=SimpleNamespace(text=lambda kind,f,text:None)
  self.log=SimpleNamespace(event=lambda name,**v:self.events.append((name,v)),parts={1:part})
  self.p=RetranslationProcessor(self.e,self.q,self.log,threading.Event())
  self.p.sentence_split=self.p.sentence_context=True
  self.settings=Settings(publication='draft')
  self.audio=np.arange(1000000,dtype=np.float32)/1000000
 def recognize(self,a,prefix=0.,**kw):
  start=round(float(a[0])*1000000);seconds=len(a)/16000;until=kw.get('until')
  self.calls.append(dict(start=start,seconds=seconds,prefix=prefix,until=until,final=not kw.get('preliminary')))
  if until is not None:text='אחת שתיים שלוש!';span=(prefix,until)
  elif prefix:text='ארבע חמש שש';span=(prefix,seconds)
  else:text={4:'אחת שתיים שלוש. ארבע',5:'אחת שתיים שלוש. ארבע חמש'}.get(round(seconds),'שבע שמונה');span=(0,seconds)
  self.e.recognition_status='accepted';self.e.recognition_words=words(text,*span);return text
 def translate(self,text,context=()):
  self.mt.append((text,context));yield 'ru:'+text,'stop'
 def f(self,start,end,final=False,reason=''):
  return Fragment(1,1,self.audio[start:end].copy(),0,time.monotonic(),final,self.settings,end/16000,0,reason)
 def pubs(self):return [v for k,_,v in self.q.queue if k=='live_publication']

 def test_closed_sentence_keeps_the_agreed_text_and_is_context_for_the_next(self):
  self.p.process(self.f(0,64000));self.p.process(self.f(0,80000))
  cut=round(self.pubs()[-1]['end']*16000)
  self.assertTrue(all(call['until'] is None for call in self.calls))  # the cut-out sentence is not decoded again
  closed=[v for v in self.pubs() if v['stage']=='closed']
  self.assertEqual(closed[0]['current']['source'],'אחת שתיים שלוש.')  # the text two snapshots agreed on
  self.assertEqual(self.mt[-1],('אחת שתיים שלוש.',()))
  self.p.process(self.f(0,96000))
  following=self.calls[-1]
  self.assertEqual(following['start'],0)  # the closed sentence's audio is heard again as context
  self.assertAlmostEqual(following['prefix'],cut/16000,places=3)
  self.assertEqual(self.mt[-1],('ארבע חמש שש',(('אחת שתיים שלוש.','ru:אחת שתיים שלוש.'),)))
  self.assertEqual(self.pubs()[-1]['current']['source'],'ארבע חמש שש')
  self.assertEqual([round(v['context_seconds'],2) for n,v in self.events if n=='live_asr' and not v.get('reused')][-1],round(cut/16000,2))

 def test_a_pause_starts_a_turn_without_context(self):
  self.p.process(self.f(0,64000));self.p.process(self.f(0,80000))
  self.p.process(self.f(0,96000,final=True,reason='silence'))
  self.assertEqual(self.mt[-1][1],(('אחת שתיים שלוש.','ru:אחת שתיים שלוש.'),))
  self.p.process(self.f(120000,152000))
  self.assertEqual(self.calls[-1]['prefix'],0.)
  self.assertEqual(self.calls[-1]['start'],120000)
  self.assertEqual(self.mt[-1],('שבע שמונה',()))

 def test_context_decode_that_loses_the_sentence_keeps_the_agreed_text(self):
  original=self.recognize
  def recognize(a,prefix=0.,**kw):
   text=original(a,prefix,**kw)
   if kw.get('until') is not None:self.e.recognition_status='empty';return ''
   return text
  self.e.recognize=recognize
  self.p.process(self.f(0,64000));self.p.process(self.f(0,80000))
  closed=[v for v in self.pubs() if v['stage']=='closed']
  self.assertEqual(closed[0]['current']['source'],'אחת שתיים שלוש.')

 def test_closing_decode_that_skips_the_first_words_takes_them_from_the_snapshot(self):
  def recognize(a,prefix=0.,**kw):
   seconds=len(a)/16000
   if kw.get('preliminary') and seconds<5.5:text='בעכו. אה, בעכו. אה, אני צריך ללכת';span=(0,seconds)
   else:text='אני צריך ללכת ברגליים, כן?';span=(2.,seconds)  # the first two seconds are skipped
   self.e.recognition_status='accepted';self.e.recognition_words=words(text,*span);return text
  self.e.recognize=recognize
  self.p.process(self.f(0,80000));self.p.process(self.f(0,88000))  # the later snapshot skips them too
  self.p.process(self.f(0,96000,final=True,reason='silence'))
  self.assertEqual(self.mt[-1][0],'בעכו. אה, בעכו. אה, אני צריך ללכת ברגליים, כן?')
  self.assertEqual([v['prefix'] for n,v in self.events if n=='live_leading_recovered'],['בעכו. אה, בעכו. אה,'])

 def test_leading_words_need_an_anchor_inside_the_snapshot(self):
  self.assertEqual(leading_words('מה קורה? אני צריך','אני צריך ללכת'),'מה קורה?')
  self.assertEqual(leading_words('אני צריך ללכת','אני צריך ללכת ברגליים'),'')  # nothing was skipped
  self.assertEqual(leading_words('מה קורה? בואי','אני צריך ללכת'),'')  # no anchor
  self.assertEqual(leading_words('מה קורה? אני','אני'),'')  # one word is no anchor

 def test_technical_cut_prefers_a_pause_outside_numbers(self):
  limit=20*16000
  timed=words('לקבלת מידע התקשרו לטלפון. 077 270 3333 או שתיים שבע אפס',14.,20.)
  cut=technical_cut(timed,np.ones(limit+16000,dtype=np.float32),limit)
  sentence=[w['end'] for w in timed if w['word'].endswith('.')][0]
  self.assertTrue(sentence*16000<cut<sentence*16000+.5*16000)
  digits=words('077 270 3333 שתיים שבע אפס',14.,20.)
  self.assertEqual(technical_cut(digits,np.ones(limit,dtype=np.float32),limit),limit)
  self.assertEqual(technical_cut([],np.ones(limit,dtype=np.float32),limit),limit)
  quiet=np.ones(limit,dtype=np.float32);quiet[17*16000:17*16000+3200]=0
  self.assertAlmostEqual(technical_cut([],quiet,limit)/16000,17.1,delta=.06)
  self.assertTrue(number_word('3852.') and number_word('ושלוש') and not number_word('הקישו'))

 def test_long_group_is_cut_at_a_pause_with_context_on(self):
  self.settings=Settings(publication='draft',draft_max_audio_seconds=6.)
  seen=[]
  def recognize(a,prefix=0.,**kw):
   seen.append((len(a)/16000,kw.get('until')))
   text='שלום לכם, תודה רבה 05 22'
   self.e.recognition_status='accepted';self.e.recognition_words=words(text,0,len(a)/16000-prefix) if not prefix else words(text,prefix,kw.get('until') or len(a)/16000);return text
  self.e.recognize=recognize
  self.p.process(self.f(0,64000));self.p.process(self.f(0,112000))
  cut=[v for n,v in self.events if n=='live_technical_cut']
  self.assertEqual(len(cut),1);self.assertLess(cut[0]['cut'],cut[0]['limit'])

 def test_prompt_continues_the_previous_translation(self):
  tokenizer=SimpleNamespace(encode=lambda text,add_special_tokens=False:text)
  self.assertEqual(prompt(tokenizer,'milmmt','ב.','he-ru',pairs=(('א.','A.'),)),
                   'Translate this from Hebrew to Russian:\nHebrew: א. ב.\nRussian: A.')
  self.assertEqual(prompt(tokenizer,'milmmt','ב.','he-ru'),'Translate this from Hebrew to Russian:\nHebrew: ב.\nRussian:')

if __name__=='__main__':unittest.main()
