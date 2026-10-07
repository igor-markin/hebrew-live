import json
from pathlib import Path
import tempfile
import unittest

from scripts.diagnose_latency import erasure, stability, summarize


def publication(segment,from_start,text,stage='open',lag=1.0):
    return dict(event='live_publication',segment=segment,from_start=from_start,audio_lag=lag,stage=stage,
                current=dict(source='מקור סודי',translation=text),elapsed=from_start)


class StabilityTests(unittest.TestCase):
    def test_erasure_counts_words_that_must_be_deleted(self):
        self.assertEqual(erasure('a b c'.split(),'a b c d'.split()),0)
        self.assertEqual(erasure('a b c'.split(),'a x c d'.split()),2)
        self.assertEqual(erasure('a b c'.split(),'a'.split()),2)
    def test_pure_growth_has_no_erasure_and_each_word_is_stable_when_it_appears(self):
        first,normalized,stable=stability([(1.,'one'),(2.,'one two'),(3.,'one two three')])
        self.assertEqual((first,normalized),(1.,0.))
        self.assertEqual(stable,[1.,2.,3.])
    def test_revised_tail_counts_as_erasure_and_delays_stability(self):
        first,normalized,stable=stability([(1.,'we go'),(2.,'we went home'),(3.,'we went home today')])
        self.assertEqual(first,1.)
        self.assertAlmostEqual(normalized,1/4)           # "go" was deleted once, final has 4 words
        self.assertEqual(stable,[1.,2.,2.,3.])           # "went" is stable only from the second version
    def test_word_that_flips_back_is_stable_only_after_the_last_change(self):
        _,_,stable=stability([(1.,'a b'),(2.,'a c'),(3.,'a b')])
        self.assertEqual(stable,[1.,3.])
    def test_no_text_has_no_stability(self):
        self.assertEqual(stability([]),(None,None,[]))
        self.assertEqual(stability([(1.,'  ')]),(None,None,[]))


class SummaryTests(unittest.TestCase):
    def write(self,folder,events,session=None):
        path=Path(folder)/'001-he-ru.diagnostics.jsonl'
        path.write_text('\n'.join(json.dumps(item,ensure_ascii=False) for item in events)+'\n',encoding='utf-8')
        if session:(Path(folder)/'session.json').write_text(json.dumps(session),encoding='utf-8')
        return path
    def test_live_metrics_and_privacy(self):
        events=[publication(1,1.5,'hello'),publication(1,2.5,'hello there'),publication(1,3.5,'hello there friend','closed',lag=2.0),
                publication(2,2.0,'bye','closed',lag=1.5),
                dict(event='recognition_repetition',elapsed=1),dict(event='unrecognized_audio',elapsed=2),
                dict(event='live_asr',elapsed=10,seconds=.5,input_seconds=2.,end=60.),
                dict(event='live_asr',elapsed=700,seconds=.7,input_seconds=2.,end=120.),
                dict(event='mt_cancel',outcome='acknowledged',seconds=.03),
                dict(event='mt_interrupted',reason='newer_audio_queued'),dict(event='mt_prioritized'),
                dict(event='mt_finished',elapsed=5,seconds=.4,truncated=True),
                dict(event='mt_generation',first_token_seconds=.25,tokens=20,proposed=10,accepted_drafts=8),
                dict(event='mlx_runtime',elapsed=0,device_name='Apple M5',neural_accelerator_wheel=True)]
        with tempfile.TemporaryDirectory() as folder:
            result=summarize(self.write(folder,events,dict(accepted={'1':dict(duration=300.)})))
        self.assertEqual(result['time_to_first_visible_draft_seconds']['count'],2)
        self.assertEqual(result['time_to_first_visible_draft_seconds']['p50'],1.5)
        self.assertEqual(result['normalized_erasure']['p50'],0.0)
        self.assertEqual(result['stable_word_seconds']['count'],4)
        self.assertEqual(result['closed_translation_audio_lag_seconds']['count'],2)
        self.assertEqual(result['audio_seconds'],300.)
        self.assertEqual(result['lost_speech_events'],2)
        self.assertEqual(result['lost_speech_per_10_minutes'],4.0)
        self.assertEqual(result['asr_short_call_seconds_by_5_minutes'],{'0':.5,'600':.7})
        self.assertEqual(result['mt_interrupted'],{'newer_audio_queued':1})
        self.assertEqual(result['mt_cancel'],{'acknowledged':1})
        self.assertEqual(result['mt_length_truncated'],1)
        self.assertEqual(result['mt_speculative_acceptance'],0.8)
        self.assertEqual(result['mlx_runtime']['device_name'],'Apple M5')
        rendered=json.dumps(result,ensure_ascii=False)
        for secret in ('hello','friend','סודי'):self.assertNotIn(secret,rendered)
    def test_audio_seconds_fall_back_to_last_asr_end(self):
        with tempfile.TemporaryDirectory() as folder:
            result=summarize(self.write(folder,[dict(event='live_asr',elapsed=1,seconds=.5,input_seconds=2.,end=90.)]))
        self.assertEqual(result['audio_seconds'],90.)
    def test_empty_log_summarizes_without_error(self):
        with tempfile.TemporaryDirectory() as folder:
            result=summarize(self.write(folder,[]))
        self.assertIsNone(result['audio_seconds']);self.assertIsNone(result['lost_speech_per_10_minutes'])


if __name__=='__main__':unittest.main()
