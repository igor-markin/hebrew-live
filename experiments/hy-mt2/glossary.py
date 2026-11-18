"""Does the model follow a "term -> translation" glossary in the request?

    .venv/bin/python experiments/hy-mt2/glossary.py run hy4 OUT.json
    .venv/bin/python experiments/hy-mt2/glossary.py score A.json B.json ... [-v]

Made-up sentences with names and clinic terms. Three conditions per sentence:
`none` (plain request), `relevant` (only the entries whose source occurs in the sentence),
`full` (the whole 12-entry glossary, as an owner's dictionary would be sent every time).
Hy-MT2 gets the card's terminology template; MiLMMT has no documented format, so it gets a plain
instruction line before its usual prompt (an ad-hoc try, not the author's contract).

Scores: hits = expected target forms found / expected; inserted = outputs that contain a glossary
target whose source is not in the sentence; leaked = outputs that echo the instruction
("translates to", "=", "Reference").
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# source, en target, ru target, en check, ru check, source check (stem that must be in the Hebrew)
GLOSSARY = [
    ('מכבי', 'Maccabi', 'Маккаби', r'Maccabi', r'Маккаби', 'מכבי'),
    ('מקסים', 'Maxim', 'Максим', r'Maxim', r'Максим', 'מקסים'),
    ('הפניה', 'referral', 'направление', r'referral', r'направлени', 'הפניה'),
    ('שקד', 'Shaked', 'Шакед', r'Shaked', r'Шакед', 'שקד'),
    ('רחובות', 'Rehovot', 'Реховот', r'Rehovot', r'Реховот', 'רחובות'),
    ('כללית', 'Clalit', 'Клалит', r'Clalit', r'Клалит', 'כללית'),
    ('סדציה', 'sedation', 'седация', r'sedation', r'седаци', 'סדציה'),
    ('ליאורה גבאי', 'Liora Gabay', 'Лиора Габай', r'Liora Gabay', r'Лиор\w* Габай', 'ליאורה גבאי'),
    ('אלמוג', 'Almog', 'Альмог', r'Almog', r'Альмог', 'אלמוג'),
    ('קופת חולים', 'health fund', 'больничная касса', r'health fund', r'больничн\w* касс', 'קופת חולים'),
    ('אורתופד', 'orthopedist', 'ортопед', r'orthop(a)?edi', r'ортопед', 'אורתופד'),
    ('תור', 'appointment', 'запись', r'appointment', r'запис', 'תור '),
]
SENTENCES = [
    'מקסים קבע תור במכבי ברחובות.',
    'ד״ר אלמוג כתבה לך הפניה לבדיקה.',
    'ליאורה גבאי מכללית תתקשר אלייך מחר.',
    'לפני הבדיקה תקבל סדציה, אז אל תנהג אחר כך.',
    'שקד מהקבלה אמרה שההפניה מוכנה.',
    'תתקשר לקופת חולים ותבקש את הטופס.',
    'מקסים ושקד נסעו לרחובות.',
    'הרופאה במכבי נתנה לו הפניה לאורתופד.',
    'הפגישה נדחתה ליום רביעי בבוקר.',
    'אני אחזור אליך אחרי ארוחת הצהריים.',
]


def present(he, entry):
    """Hebrew attaches prepositions to the word (במכבי, לרחובות), so a substring is enough."""
    return entry[5] in he


def terms_for(he, condition, lang):
    col = 1 if lang == 'en' else 2
    if condition == 'none':
        return []
    entries = GLOSSARY if condition == 'full' else [e for e in GLOSSARY if present(he, e)]
    return [(e[0], e[col]) for e in entries]


def run(args):
    from common import Translator, require_memory
    require_memory()
    tr = Translator(args.model)
    tr.translate(SENTENCES[0], 'he-en')
    out = {}
    for pair in ('he-en', 'he-ru'):
        lang = pair[-2:]
        for condition in ('none', 'relevant', 'full'):
            out.setdefault(pair, {})[condition] = [tr.translate(he, pair, terms=terms_for(he, condition, lang)) for he in SENTENCES]
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f'peak MLX {tr.peak_gb():.2f} GB')


def score(args):
    for pair in ('he-en', 'he-ru'):
        lang = pair[-2:]
        check = 3 if lang == 'en' else 4
        print(f'\n{pair}: condition -> hits / expected, inserted, leaked, p50 prompt tokens')
        for path in args.runs:
            run = json.loads(path.read_text())[pair]
            line = path.stem[:24].ljust(25)
            for condition in ('none', 'relevant', 'full'):
                hits = expected = inserted = leaked = 0
                for he, row in zip(SENTENCES, run[condition]):
                    text = row['text']
                    for e in GLOSSARY:
                        if present(he, e):
                            expected += 1
                            hits += bool(re.search(e[check], text, re.I))
                        elif condition != 'none' and re.search(e[check], text, re.I):
                            inserted += 1
                    leaked += bool(re.search(r'translates to|Reference|=|→', text))
                    if args.verbose:
                        print(f'    {condition}: {text}')
                tokens = sorted(r['prompt_tokens'] for r in run[condition])[len(SENTENCES) // 2]
                line += f'{condition} {hits}/{expected} ins {inserted} leak {leaked} tok {tokens} | '
            print(line)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('model', choices=['milmmt', 'hy4', 'hy8', 'hybf16'])
    r.add_argument('out', type=Path)
    s = sub.add_parser('score')
    s.add_argument('runs', nargs='+', type=Path)
    s.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    run(args) if args.cmd == 'run' else score(args)
