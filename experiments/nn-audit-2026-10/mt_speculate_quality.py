"""Plan 3.7 screening: does a drafted/tolerant translation chain end worse than plain greedy?

Final translations of the 12 synthetic sentences (grown two words at a time, each step drafted
from the previous output) are scored with chrF++ against reference translations written by a
strong LLM (plan 4.3) and with a keyword fact check (numbers, days, negations). Twelve sentences
only screen for gross damage; they cannot establish non-inferiority.

    MARGINS="0 0.3 0.7 1.5" .venv/bin/python experiments/nn-audit-2026-10/mt_speculate_quality.py he-ru|he-en
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'experiments' / 'corpus'))
sys.path.insert(0, str(Path(__file__).parent))
from mlx_lm import load
from mlx_lm.sample_utils import make_sampler

import corpus
from metrics import chrf
from hebrew_live import mt_generate, mt_speculate
from hebrew_live.translation import configure, prompt

GOLD = {
    'he-en': [
        'The government approved the budget, but the decision has not yet come into force.',
        'The index rose by half a percent, not by five percent.',
        "He had my back even when no one else believed in me.",
        "In hindsight I would do it differently, but I don't regret it.",
        'The boy takes part in class, but finds it hard to wait for his turn.',
        'After-school care ends at four, and the shuttle leaves at a quarter to four.',
        'Who can accompany the class on Tuesday?',
        'The door code is two four six eight.',
        "It's the third floor, apartment twelve, and there is no elevator.",
        "I have a referral from the family doctor, but I don't have a payment commitment.",
        "I didn't ask to cancel the appointment, only to change the time.",
        'You need to arrive after fasting for eight hours, but drinking water is allowed.',
    ],
    'he-ru': [
        'Правительство утвердило бюджет, но решение ещё не вступило в силу.',
        'Индекс вырос на полпроцента, а не на пять процентов.',
        'Он поддерживал меня, даже когда никто другой в меня не верил.',
        'Оглядываясь назад, я бы поступил иначе, но я не жалею.',
        'Ребёнок участвует в уроке, но с трудом дожидается своей очереди.',
        'Продлёнка заканчивается в четыре, а автобус отправляется без четверти четыре.',
        'Кто может сопровождать класс во вторник?',
        'Код от двери: два, четыре, шесть, восемь.',
        'Это третий этаж, квартира двенадцать, лифта нет.',
        'У меня есть направление от семейного врача, но нет гарантии оплаты.',
        'Я не просил отменить приём, а только изменить время.',
        'Нужно прийти натощак после восьми часов голодания, но воду пить можно.',
    ],
}
# Each group: one of the alternatives must appear (lower-case substring) for the fact to count as kept.
FACTS = {
    'he-en': [[('not yet', 'has not')], [('half',), ('not',)], [('even when', 'no one', 'nobody')], [("n't", 'not regret', 'no regret')],
              [('turn',)], [('four',), ('quarter to', 'a quarter', '3:45', '15 minutes', 'quarter of')], [('tuesday',)],
              [('two',), ('four',), ('six',), ('eight',)], [('third', '3rd'), ('twelve', '12'), ('no elevator', 'no lift', "n't have an elevator", 'without')],
              [('referral',), ("n't", 'no ', 'not', 'without')], [("n't", 'not'), ('time', 'hour')], [('eight', '8'), ('water',), ('allowed', 'may', 'can', 'permitted')]],
    'he-ru': [[('не вступил', 'ещё не', 'еще не')], [('пол',), ('не на', 'а не')], [('никто', 'даже когда')], [('не жал',)],
              [('очеред',)], [('четыр', '4'), ('без четверти', 'без пятнадцати', '3:45', 'четверти')], [('вторник',)],
              [('два', '2'), ('четыре', '4'), ('шесть', '6'), ('восемь', '8')], [('трет', '3'), ('двенадцат', '12'), ('нет лифт', 'лифта нет', 'без лифт')],
              [('направлени',), ('нет', 'не ', 'без')], [('не просил', 'не хотел', 'не прошу'), ('время', 'час')], [('восьм', '8'), ('вод',), ('можно', 'разрешен')]],
}

direction = sys.argv[1] if len(sys.argv) > 1 else 'he-ru'
margins = [float(x) for x in os.environ.get('MARGINS', '0 0.3 0.7 1.5').split()]
model, tok = load(str(ROOT / 'models' / 'milmmt-4b-4bit'))
configure(tok, 'milmmt')
refs = [r for _, _, r in corpus.load()]


def run(text, hint=None, margin=0.):
    ids = prompt(tok, 'milmmt', text, direction)
    limit = mt_generate.max_tokens_for(len(tok.encode(text, add_special_tokens=False)))
    step = mt_speculate.step_for(tok.encode(hint, add_special_tokens=False), None, margin) if hint else None
    return ''.join(p for p, _ in mt_generate.generate(model, tok, ids, max_tokens=limit,
                                                     sampler=make_sampler(temp=0), step=step)).strip()


def facts_kept(text, groups):
    low = text.lower()
    return sum(any(alt in low for alt in group) for group in groups), len(groups)


def final_translations(margin):
    finals = []
    for ref in refs:
        words = ref.split()
        text = run(' '.join(words[:min(4, len(words))]))
        for n in range(6, len(words) + 2, 2):
            text = run(' '.join(words[:min(n, len(words))]), text, margin)
        finals.append(text)
    return finals


gold = GOLD[direction]
rows = {'plain greedy': [run(ref) for ref in refs]}
for margin in margins:
    rows[f'drafted, tolerance {margin}'] = final_translations(margin)
for name, finals in rows.items():
    score = sum(chrf(f, g) for f, g in zip(finals, gold)) / len(gold)
    kept = [facts_kept(f, g) for f, g in zip(finals, FACTS[direction])]
    lost = [i + 1 for i, (a, b) in enumerate(kept) if a < b]
    print(f'{name:26s} chrF++ {score:5.1f}  facts kept {sum(a for a, _ in kept)}/{sum(b for _, b in kept)}  sentences with a lost fact: {lost}')
