"""Causal boundary contracts: same hypotheses, no model/scheduler changes."""
import unittest
from hebrew_live.phrase_buffer import PhraseBuffer, align_words


def words(text, step=.3):
    return [dict(word=w,start=i*step,end=(i+1)*step) for i,w in enumerate(text.split())]


def confirmed(text, now=3):
    b=PhraseBuffer();w=words(text)
    b.update(w,0,now,1);b.update(w,0,now+.1,1)
    return b


class BoundaryTests(unittest.TestCase):
    def test_one_occurrence_does_not_confirm_two(self):
        b=PhraseBuffer();b.update(words('да'),0,1,1)
        b.update(words('да да'),0,2,1)
        self.assertEqual([w['word_stable'] for w in b.pending],[True,False])
        b.update(words('да да'),0,3,1)
        self.assertTrue(all(w['word_stable'] for w in b.pending))
        self.assertEqual(b.take(3,.6,final=True)[0].source,'да да')

    def test_alignment_chooses_time_nearest_repeat(self):
        old=[dict(word='да',start=.3,end=.6)]
        self.assertEqual(align_words(old,words('да да')),{1:0})

    def test_alignment_never_crosses_or_reuses(self):
        old=words('да нет да');new=words('нет да нет')
        pairs=sorted(align_words(old,new).items())
        self.assertEqual(len(pairs),2)
        self.assertEqual([p for _,p in pairs],sorted({p for _,p in pairs}))

    def test_insert_delete_confirm_later_words_without_losing_repeat(self):
        b=PhraseBuffer();b.update(words('мы завтра будем дома'),0,2,1)
        b.update(words('мы не завтра будем дома'),0,3,1)
        self.assertEqual([w['stable'] for w in b.pending],[True,False,True,True,True])
        b.update(words('мы не будем дома'),0,4,1)
        self.assertTrue(all(w['stable'] for w in b.pending))
        self.assertEqual(b.take(4,.6,final=True)[0].source,'мы не будем дома')

    def test_one_new_period_is_not_a_boundary(self):
        b=PhraseBuffer();b.update(words('Он придёт завтра'),0,1.5,1)
        b.update(words('Он придёт. завтра'),0,2.5,1)
        self.assertTrue(all(w['word_stable'] for w in b.pending))
        self.assertFalse(b.pending[1]['boundary_stable'])
        self.assertEqual(b.take(2.5,max_wait=100),[])
        b.update(words('Он придёт. завтра'),0,3,1)
        self.assertEqual(b.take(3,max_wait=100)[0].source,'Он придёт.')

    def test_changed_punctuation_requires_its_own_confirmation(self):
        b=PhraseBuffer();b.update(words('Он придёт, завтра'),0,2,1)
        b.update(words('Он придёт. завтра'),0,3,1)
        self.assertFalse(b.pending[1]['boundary_stable'])
        b.update(words('Он придёт завтра'),0,3.5,1)
        self.assertEqual(b.take(3.5,max_wait=100),[])

    def test_technical_final_does_not_close_sentence(self):
        b=PhraseBuffer();b.update(words('Он придёт.'),0,10,1,final=True)
        self.assertTrue(all(w['word_stable'] for w in b.pending))
        self.assertFalse(any(w['boundary_stable'] for w in b.pending))
        self.assertEqual(b.take(10,quiet=0,final=True),[])
        self.assertEqual(b.take(10,.6,final=True)[0].source,'Он придёт.')

    def test_actual_pause_closes_clause_without_punctuation(self):
        b=PhraseBuffer();b.update(words('אני חוזר הביתה'),0,2,1,final=True)
        u=b.take(2,.6,final=True)[0]
        self.assertEqual((u.source,u.reason),('אני חוזר הביתה','clause_pause'))

    def test_internal_acoustic_gap_closes_clause(self):
        w=words('אני בא');w+= [dict(word='מחר',start=1.3,end=1.6)]
        b=PhraseBuffer();b.update(w,0,2,1);b.update(w,0,3,1)
        u=b.take(3)[0];self.assertEqual((u.source,u.reason),('אני בא','clause_pause'))

    def test_deadline_prefers_last_confirmed_comma(self):
        b=confirmed('אני חוזר, אתה נשאר, כולם מחכים כאן עכשיו',now=5)
        u=b.take(5,max_wait=4)[0]
        self.assertEqual((u.source,u.reason),('אני חוזר, אתה נשאר,','clause_boundary'))

    def test_single_new_comma_not_used_as_confirmed_boundary(self):
        b=PhraseBuffer();b.update(words('אחד שני שלישי רביעי חמישי'),0,5,1)
        b.update(words('אחד שני שלישי רביעי, חמישי'),0,6,1)
        u=b.take(6)[0]
        self.assertEqual(u.source,'אחד שני שלישי');self.assertEqual(u.reason,'deadline')
        self.assertEqual([w['word'] for w in b.pending],['רביעי,','חמישי'])

    def test_deadline_without_safe_cut_waits_even_after_long_time(self):
        b=confirmed('אני חושב על')
        self.assertEqual(b.take(100),[])
        self.assertEqual(len(b.pending),3)

    def test_open_edge_and_continuation_remain_together(self):
        b=confirmed('למדרגות ולקחת את זה על',now=5)
        emitted=b.take(5)
        self.assertFalse(any(u.source.endswith('על') for u in emitted))
        w=words('למדרגות ולקחת את זה על יד הדירה שלי?')
        b.update(w,0,6,1);b.update(w,0,6.2,1)
        emitted+=b.take(6.2)
        self.assertEqual(' '.join(u.source for u in emitted),'למדרגות ולקחת את זה על יד הדירה שלי?')
        self.assertEqual(sum('על יד' in u.source for u in emitted),1)

    def test_open_edges_generalize_beyond_one_expression(self):
        for text in ['אני עושה את זה כדי ש', 'אני עושה את זה בגלל ה',
                     'я останусь здесь потому что', 'я буду ждать рядом с']:
            b=confirmed(text,now=5);u=b.take(5)
            self.assertTrue(all(not x.source.endswith(('כדי','בגלל','потому','рядом')) for x in u))
            self.assertTrue(b.pending)

    def test_right_dependent_word_prevents_fallback_cut(self):
        b=confirmed('אנחנו נמצאים פה רק עכשיו תמיד',now=5)
        u=b.take(5)[0]
        # Latest candidate (after 'רק') is open; before 'רק' has dependent RHS.
        self.assertEqual(u.source,'אנחנו נמצאים')

    def test_negation_is_not_detached_by_stable_period(self):
        b=confirmed('לא. להתקשר היום',now=5)
        self.assertEqual(b.take(5),[])
        self.assertEqual(b.take(5,force='eof')[0].source,'לא. להתקשר היום')

    def test_control_flush_preserves_and_labels_unconfirmed_tail(self):
        b=PhraseBuffer();b.update(words('אני לא'),0,1,1)
        u=b.take(1,force='direction')[0]
        self.assertEqual(u.source,'אני לא');self.assertTrue(u.unconfirmed)
        self.assertTrue(u.incomplete);self.assertFalse(b.pending)
        self.assertEqual(b.take(2,force='eof'),[])

    def test_empty_rejection_do_not_invent_boundary_or_drop_tail(self):
        b=PhraseBuffer();b.update(words('אני בא.'),0,2,1)
        for status in ['empty','rejected']:
            b.update([],0,3,1,final=True,status=status)
            self.assertFalse(any(w['boundary_stable'] for w in b.pending))
            self.assertEqual(b.take(3,.6,final=True),[])
        self.assertEqual(b.take(3,force='eof')[0].source,'אני בא.')

    def test_service_word_with_one_complement_is_not_a_fallback_edge(self):
        for text in ['לעלות למדרגות ולקחת את זה על יד הדירה שלי',
                     'мы можем поговорить рядом с домом прямо сейчас']:
            b=confirmed(text,now=6);u=b.take(6)
            self.assertFalse(any(x.source.endswith(('על יד','с домом')) for x in u))
            self.assertTrue(b.pending)
        b=confirmed('לעלות למדרגות ולקחת את זה על יד הדירה שלי',now=6)
        u=b.take(6);u+=b.take(7,.6,final=True)
        self.assertEqual(sum('על יד הדירה שלי' in x.source for x in u),1)

    def test_retained_occurrence_cannot_confirm_new_window_repeat(self):
        b=PhraseBuffer();b.update(words('да'),0,1,1)
        b.update(words('да'),.3,2,2)
        self.assertEqual([w['word_stable'] for w in b.pending],[False,False])
        self.assertTrue(b.pending[0]['unconfirmed'])
        b.update(words('да'),.3,3,2)
        self.assertEqual([w['word_stable'] for w in b.pending],[False,True])
        self.assertEqual(b.take(3,.6,final=True)[0].source,'да да')

    def test_new_timestamp_gap_alone_is_not_an_acoustic_boundary(self):
        b=PhraseBuffer();b.update(words('мы придём завтра'),0,2,1)
        w=words('мы придём завтра');w[2]['start']=1.3;w[2]['end']=1.6
        b.update(w,0,3,1,final=True)
        self.assertEqual(b.take(3,max_wait=100),[])

    def test_pronoun_completes_service_word_without_pair_dictionary(self):
        for text,expected in [
            ('אנחנו רוצים לקחת את זה עכשיו הביתה','אנחנו רוצים לקחת את זה'),
            ('мы будем говорить об этом сегодня вечером','мы будем говорить об этом'),
            ('мы хотим поговорить про это сегодня вечером','мы хотим поговорить про это')]:
            b=confirmed(text,now=6);u=b.take(6)
            self.assertEqual(u[0].source,expected)

    def test_pronoun_does_not_close_conjunction_or_negation(self):
        for text in ['אני אומר אם זה נכון עכשיו', 'это произошло потому что это важно сегодня', 'он сказал не это сегодня утром']:
            b=confirmed(text,now=6)
            self.assertFalse(any(u.source.endswith(('אם זה','что это','не это')) for u in b.take(6)))
