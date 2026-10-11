import os
import unittest
from unittest.mock import patch

from hebrew_live import mt_generate


class FakeDetokenizer:
    """Like the library's streaming detokenizer: `last_segment` is the text not yet read.

    '~' is an incomplete multi-byte token: held back until the next token or finalize."""
    def __init__(self, vocab):self.vocab=vocab;self.reset()
    def reset(self):self.held='';self.unread=''
    def add_token(self,token):
        piece=self.vocab[token]
        if piece=='~':self.held+='é';return
        self.unread+=self.held+piece;self.held=''
    def finalize(self):self.unread+=self.held;self.held=''
    @property
    def last_segment(self):
        value,self.unread=self.unread,'';return value


class FakeTokenizer:
    eos_token_ids={1,106}
    vocab={10:'a',11:'b',12:'~',13:'c'}
    @property
    def detokenizer(self):return FakeDetokenizer(self.vocab)


def stepper(tokens):
    def step(prompt,model,*,max_tokens,sampler):
        for n,token in enumerate(tokens):
            if n==max_tokens:return
            yield token,None
    return step


class MtGenerateTests(unittest.TestCase):
    def run_fast(self,tokens,max_tokens=50,stats=None):
        with patch.dict(os.environ,{'HEBREW_LIVE_MT_GENERATE':'fast'}):
            return list(mt_generate.generate(None,FakeTokenizer(),[1,2,3],max_tokens=max_tokens,
                                             sampler=None,step=stepper(tokens),stats=stats))
    def test_stop_token_ends_with_stop_and_flushes_held_text(self):
        self.assertEqual(self.run_fast([10,11,1]),[('a',None),('b',None),('','stop')])
        self.assertEqual(self.run_fast([10,12,106]),[('a',None),('',None),('é','stop')])
    def test_incomplete_token_is_joined_to_the_next_segment(self):
        self.assertEqual(self.run_fast([10,12,13,106]),[('a',None),('',None),('éc',None),('','stop')])
    def test_limit_reports_length_without_losing_the_last_token(self):
        out=self.run_fast([10,11,13,10,11],max_tokens=3)
        self.assertEqual(out,[('a',None),('b',None),('c','length')])
    def test_stats_count_tokens_and_first_token_time(self):
        stats={}
        self.run_fast([10,11,1],stats=stats)
        self.assertEqual(stats['tokens'],3)
        self.assertGreaterEqual(stats['first_token_seconds'],0)
    def test_early_close_stops_pulling_tokens(self):
        pulled=[]
        def step(prompt,model,*,max_tokens,sampler):
            for token in (10,11,13,10):
                pulled.append(token);yield token,None
        with patch.dict(os.environ,{'HEBREW_LIVE_MT_GENERATE':'fast'}):
            generator=mt_generate.generate(None,FakeTokenizer(),[1],max_tokens=50,sampler=None,step=step)
            next(generator);generator.close()
        self.assertEqual(pulled,[10])

    def test_detokenizer_is_built_once_and_reset_between_generations(self):
        built=[]
        class Counting(FakeTokenizer):
            @property
            def detokenizer(self):
                built.append(1);return FakeDetokenizer(self.vocab)
        tokenizer=Counting()
        with patch.dict(os.environ,{'HEBREW_LIVE_MT_GENERATE':'fast'}):
            for tokens,expected in (([10,12,13,106],'aéc'),([11,1],'b'),([10,11,13,10,11],'abca')):
                out=list(mt_generate.generate(None,tokenizer,[1],max_tokens=4,sampler=None,step=stepper(tokens)))
                self.assertEqual(''.join(text for text,_ in out),expected)
        self.assertEqual(len(built),1)
    def test_overlapping_generations_never_share_a_detokenizer(self):
        built=[]
        class Counting(FakeTokenizer):
            @property
            def detokenizer(self):
                built.append(1);return FakeDetokenizer(self.vocab)
        tokenizer=Counting()
        with patch.dict(os.environ,{'HEBREW_LIVE_MT_GENERATE':'fast'}):
            first=mt_generate.generate(None,tokenizer,[1],max_tokens=50,sampler=None,step=stepper([10,11,13,1]))
            second=mt_generate.generate(None,tokenizer,[1],max_tokens=50,sampler=None,step=stepper([13,13,1]))
            self.assertEqual(next(first),('a',None))
            self.assertEqual(next(second),('c',None))
            self.assertEqual(next(first),('b',None))
            self.assertEqual(next(second),('c',None))
            self.assertEqual([text for text,_ in first],['c',''])
            self.assertEqual([text for text,_ in second],[''])
        self.assertEqual(len(built),2)
    def test_abandoned_generation_returns_its_detokenizer(self):
        built=[]
        class Counting(FakeTokenizer):
            @property
            def detokenizer(self):
                built.append(1);return FakeDetokenizer(self.vocab)
        tokenizer=Counting()
        with patch.dict(os.environ,{'HEBREW_LIVE_MT_GENERATE':'fast'}):
            abandoned=mt_generate.generate(None,tokenizer,[1],max_tokens=50,sampler=None,step=stepper([10,11,13]))
            next(abandoned);abandoned.close()
            self.assertEqual(list(mt_generate.generate(None,tokenizer,[1],max_tokens=50,sampler=None,step=stepper([13,1]))),[('c',None),('','stop')])
        self.assertEqual(len(built),1)

    def test_budget_scales_with_source_and_stays_bounded(self):
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop('HEBREW_LIVE_MT_MAX_TOKENS',None)
            self.assertEqual(mt_generate.max_tokens_for(0),96)
            self.assertEqual(mt_generate.max_tokens_for(10),96)
            self.assertEqual(mt_generate.max_tokens_for(40),192)
            self.assertEqual(mt_generate.max_tokens_for(100),432)
            self.assertEqual(mt_generate.max_tokens_for(5000),512)
    def test_environment_override_restores_fixed_limit(self):
        with patch.dict(os.environ,{'HEBREW_LIVE_MT_MAX_TOKENS':'256'}):
            self.assertEqual(mt_generate.max_tokens_for(1),256)
            self.assertEqual(mt_generate.max_tokens_for(5000),256)
        with patch.dict(os.environ,{'HEBREW_LIVE_MT_MAX_TOKENS':'junk'}):
            self.assertEqual(mt_generate.max_tokens_for(1),96)
    def test_mode_switch(self):
        with patch.dict(os.environ,{'HEBREW_LIVE_MT_GENERATE':'stock'}):self.assertEqual(mt_generate.mode(),'stock')
        with patch.dict(os.environ,{'HEBREW_LIVE_MT_GENERATE':'anything'}):self.assertEqual(mt_generate.mode(),'fast')


if __name__=='__main__':unittest.main()
