import os
import unittest
from unittest.mock import patch

try:
    import mlx.core as mx
    HAVE_MLX=True
except Exception:  # CI runners without Metal keep the pure-Python tests
    HAVE_MLX=False

from hebrew_live.mt_speculate import Drafter, step_for, tolerance

VOCAB=23


class ToleranceSettingTests(unittest.TestCase):
    def test_environment_value(self):
        for text,expected in (('',0.),('0.5',.5),('junk',0.),('-1',0.)):
            with patch.dict(os.environ,{'HEBREW_LIVE_MT_SPECULATE_TOLERANCE':text}):self.assertEqual(tolerance(),expected)


class DrafterTests(unittest.TestCase):
    def test_follows_matching_tokens_and_proposes_the_rest(self):
        drafter=Drafter([5,6,7,8,9])
        drafter.emit(5);drafter.emit(6)
        self.assertEqual(drafter.propose(2),[7,8])
        self.assertEqual(drafter.propose(10),[7,8,9])
    def test_mismatch_loses_alignment_until_two_tokens_match_again(self):
        drafter=Drafter([5,6,7,8,9])
        drafter.emit(5);drafter.emit(99)
        self.assertEqual(drafter.propose(3),[])
        drafter.emit(7)            # only one token of the new tail: not enough to resync
        self.assertEqual(drafter.propose(3),[])
        drafter.emit(8)            # [7, 8] occurs in the draft: continue after it
        self.assertEqual(drafter.propose(3),[9])
    def test_exhausted_draft_proposes_nothing(self):
        drafter=Drafter([1,2])
        drafter.emit(1);drafter.emit(2)
        self.assertEqual(drafter.propose(5),[])
    def test_empty_draft_never_proposes(self):
        drafter=Drafter([])
        drafter.emit(3)
        self.assertEqual(drafter.propose(5),[])


class FakeCache:
    """Sliding-window cache: once full it forgets its oldest tokens, and trim cannot undo that."""
    def __init__(self,max_size):self.max_size=max_size;self.history=[];self.offset=0;self.lost=False
    state=()
    def is_trimmable(self):return self.offset<self.max_size
    def append(self,tokens):
        self.history+=tokens;self.offset+=len(tokens)
        if len(self.history)>self.max_size:self.history=self.history[-self.max_size:];self.lost=True
    def trim(self,n):
        if self.lost:raise AssertionError('trimmed a cache that already dropped old tokens')
        n=min(self.offset,n);self.offset-=n;del self.history[len(self.history)-n:];return n


class FakeModel:
    """Next token = function of the visible history: exact, hardware-independent arithmetic."""
    def __init__(self,window=64):self.window=window;self.calls=[]
    def make_cache(self):return [FakeCache(self.window)]
    @staticmethod
    def rule(history):return (sum(token*(i+3) for i,token in enumerate(history))*7+int(history[-1])) % VOCAB
    def __call__(self,tokens,cache):
        cache=cache[0];new=[int(token) for token in tokens[0].tolist()]
        self.calls.append(len(new));rows=[]
        for token in new:
            cache.append([token]);row=[0.]*VOCAB;row[self.rule(cache.history)]=10.;rows.append(row)
        return mx.array([rows])


@unittest.skipUnless(HAVE_MLX,'MLX is required')
class SpeculativeLogicTests(unittest.TestCase):
    PROMPT=[3,9,14,5]
    def plain(self,model,count):
        cache=model.make_cache();model(mx.array(self.PROMPT)[None],cache);out=[]
        history=list(self.PROMPT)
        cache=model.make_cache();model(mx.array(self.PROMPT[:-1])[None],cache)
        last=self.PROMPT[-1]
        for _ in range(count):
            row=model(mx.array([last])[None],cache)[0,-1].tolist();last=row.index(max(row));out.append(last)
        return out
    def speculative(self,model,draft,count,stats=None,margin=0.):
        return [token for token,_ in step_for(draft,stats,margin)(mx.array(self.PROMPT),model,max_tokens=count)]
    def test_equals_plain_decoding_for_every_kind_of_draft_and_window(self):
        for window in (64,12,9):
            model=FakeModel(window);reference=self.plain(model,40)
            drafts={'exact':reference,'prefix':reference[:15],
                    'edited':reference[:10]+[(reference[10]+1)%VOCAB]+reference[11:],
                    'shifted':[7,7]+reference,'garbage':[(i*5+1)%VOCAB for i in range(40)],'empty':[]}
            for name,draft in drafts.items():
                with self.subTest(window=window,draft=name):
                    self.assertEqual(self.speculative(FakeModel(window),draft,40),reference)
    def test_exact_draft_is_verified_in_large_blocks(self):
        model=FakeModel(256);reference=self.plain(FakeModel(256),48);stats={}
        self.assertEqual(self.speculative(model,reference,48,stats),reference)
        self.assertGreater(stats['accepted_drafts'],35)
        self.assertLess(stats['speculative_rounds'],10)
        self.assertGreater(max(model.calls),8)
    def test_wrong_draft_costs_one_wasted_pass_not_correctness(self):
        model=FakeModel(256);reference=self.plain(FakeModel(256),30);stats={}
        garbage=[(token+1)%VOCAB for token in reference]
        self.assertEqual(self.speculative(model,garbage,30,stats),reference)
        self.assertEqual(stats['accepted_drafts'],0)
    def test_token_limit_is_respected(self):
        reference=self.plain(FakeModel(),30)
        for limit in (1,2,7,30):
            self.assertEqual(self.speculative(FakeModel(),reference,limit),reference[:limit])
    def test_verification_never_crosses_a_sliding_window(self):
        model=FakeModel(10);reference=self.plain(FakeModel(10),30)
        self.assertEqual(self.speculative(model,reference,30),reference)   # FakeCache raises if trim follows a wrap
    def test_tolerance_keeps_a_drafted_token_the_model_would_not_pick(self):
        reference=self.plain(FakeModel(256),30)
        edited=reference[:10]+[(reference[10]+1)%VOCAB]+reference[11:]
        strict={};loose={}
        self.assertEqual(self.speculative(FakeModel(256),edited,30,strict)[10],reference[10])
        out=self.speculative(FakeModel(256),edited,30,loose,margin=1e9)    # any drafted token is "close enough"
        self.assertEqual(out[10],edited[10])
        self.assertEqual(out[:10],reference[:10])
        self.assertGreaterEqual(loose['accepted_drafts'],10)             # it accepted the 10 matching tokens and the edited one


if __name__=='__main__':unittest.main()
