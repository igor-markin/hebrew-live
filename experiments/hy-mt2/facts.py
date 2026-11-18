"""Fact checklist: names that are also words, places, dates, times, numbers, medical terms.

    .venv/bin/python experiments/hy-mt2/facts.py run hy4 OUT.json [--mode greedy]
    .venv/bin/python experiments/hy-mt2/facts.py score A.json B.json ...

The sentences are made up for this test (not from anyone's recordings). Each item lists what the
translation must contain (every group needs one matching alternative, regex, case-insensitive
unless the pattern says otherwise) and what it must not contain (the literal reading of a name,
a year instead of a day, a wrong term). Digits are also checked after removing separators.
"""
import argparse
import json
import re
import sys
from pathlib import Path

YEAR = r'\b(19|20)\d\d\b'
ITEMS = [
    # id, category, Hebrew, {en: (must, must_not), ru: (must, must_not)}
    ('name-maxim', 'name', 'מקסים התקשר אליי אתמול בערב.',
     {'en': ([r'Ma[xk]s?im'], [r'wonderful|charming|amazing|lovely|delightful']),
      'ru': ([r'Макс[иі]м'], [r'прекрасн|замечательн|очарователь|чудесн|восхитит'])}),
    ('name-chen', 'name', 'אמרתי לחן שהפגישה נדחתה.',
     {'en': ([r'\b(Chen|Hen|Khen)\b'], [r'charm|grace|favou?r']),
      'ru': ([r'\b(Хен|Хэн|Чен|Хена|Хэне|Хен[уе])\b'], [r'обаян|шарм|благодат|милост'])}),
    ('name-tal-or', 'name', 'טל ואור יגיעו מחר בבוקר.',
     {'en': ([r'\bTal\b', r'\bOr\b'], [r'\bdew\b|\blight\b']),
      'ru': ([r'\bТал[ьи]?\b', r'\bОр\b'], [r'\bрос[аы]\b|\bсвет\b'])}),
    ('name-simcha', 'name', 'שמחה, הפקידה מהקבלה, ביקשה שתחזור אליה.',
     {'en': ([r'Sim(c)?ha'], [r'\bjoy\b|happy|happiness']),
      'ru': ([r'Симх'], [r'радост|счаст'])}),
    ('name-barak-sunday', 'name', 'ברק יבדוק את התוצאות ביום ראשון.',
     {'en': ([r'Barak', r'Sunday'], [r'lightning|first day']),
      'ru': ([r'Барак', r'воскресень'], [r'молни|первый день|в первый'])}),
    ('name-gil', 'name', 'גיל אמר שהוא יאחר בעשר דקות.',
     {'en': ([r'\bGil\b', r'\b(10|ten)\b'], [r'\bage\b|\bjoy\b']),
      'ru': ([r'\bГил[ьа]?\b', r'\b(10|десять)\b'], [r'возраст|радост'])}),
    ('name-shaked-time', 'name', 'ד״ר שקד תראה אותך בשעה 11:15.',
     {'en': ([r'Shaked', r'11[:.]15'], [r'almond']),
      'ru': ([r'Шакед', r'11[:.]15'], [r'миндал'])}),
    ('name-raz-referral', 'name', 'רז שלח לך את ההפניה במייל.',
     {'en': ([r'\bRaz\b', r'referral|\brefer'], [r'secret|mystery|\blink\b']),
      'ru': ([r'(?-i:\bРаз\b)', r'направлени'], [r'тайн|секрет|ссылк'])}),
    ('place-rehovot', 'place', 'המרפאה נמצאת ברחובות, ליד התחנה.',
     {'en': ([r'Re[h]?ovot|Rehoboth'], [r'\bstreets?\b']),
      'ru': ([r'Реховот'], [r'улиц'])}),
    ('place-kfar-saba', 'place', 'הבדיקה תהיה בכפר סבא ולא בראש העין.',
     {'en': ([r'Kfar[ -]?Saba', r"Rosh[ -]?ha[ -']?['-]?ayin"], [r'grandfather|village']),
      'ru': ([r'Кф?ар[ -]?Саб', r'Рош[ -]?(ха|а)[ -]?А[йи]н'], [r'дедушк|деревн'])}),
    ('place-clalit-bat-yam', 'place', 'הסניף של כללית בבת ים סגור היום.',
     {'en': ([r'Clalit|Klalit', r'Bat[ -]?Yam'], [r'\bgeneral\b']),
      'ru': ([r'Клалит', r'Бат[ -]?Ям'], [r'\bобщ'])}),
    ('place-maccabi', 'place', 'קבעתי תור במכבי לשבוע הבא.',
     {'en': ([r'Maccabi'], []),
      'ru': ([r'Макк?аби'], [r'Макави|Макби'])}),
    ('date-9-oct', 'date', 'התור נקבע לתשעה באוקטובר.',
     {'en': ([r'\b(9|9th|ninth|nine)\b.{0,6}October|October.{0,3}\b(9|9th|ninth)\b'], [YEAR]),
      'ru': ([r'\b(9|девят\w+)\s+октябр'], [YEAR])}),
    ('date-23-nov', 'date', 'נתראה בעשרים ושלושה בנובמבר.',
     {'en': ([r'\b(23|23rd|twenty[- ]third|twenty[- ]three)\b.{0,6}November|November.{0,3}\b(23|23rd|twenty[- ]third)\b'], [YEAR]),
      'ru': ([r'\b(23|двадцать\s+трет\w+)\s+ноябр'], [YEAR])}),
    ('date-3-mar', 'date', 'הניתוח נדחה לשלושה במרץ.',
     {'en': ([r'\b(3|3rd|third|three)\b.{0,6}March|March.{0,3}\b(3|3rd|third)\b'], [YEAR]),
      'ru': ([r'\b(3|трет\w+)\s+март'], [YEAR])}),
    ('date-year', 'date', 'היא נולדה בשנת 1987.',
     {'en': ([r'1987'], []), 'ru': ([r'1987'], [])}),
    ('date-15th', 'date', 'ב־15 לחודש תקבל את התוצאות.',
     {'en': ([r'\b15(th)?\b'], [YEAR]), 'ru': ([r'\b15(-?го|-?е)?\b'], [YEAR])}),
    ('time-3-30', 'time', 'הפגישה בשעה שלוש וחצי אחרי הצהריים.',
     {'en': ([r'3[:.]30|15[:.]30|half past three|three[- ]thirty|three and a half in the afternoon'], []),
      'ru': ([r'15[:.]30|3[:.]30|половин\w+ четв[её]рт|пол-?четв[её]рт|три тридцать|пятнадцать тридцать'], [])}),
    ('time-7-15', 'time', 'תגיע בשבע ורבע בבוקר.',
     {'en': ([r'7[:.]15|quarter past seven|seven[- ]fifteen|seven and a quarter'], []),
      'ru': ([r'7[:.]15|четверть восьмого|семь пятнадцать|семь с четвертью'], [])}),
    ('time-22', 'time', 'המשמרת מסתיימת בשעה 22:00.',
     {'en': ([r'22[:.]00|10(:00)?\s*(p\.?m|in the evening)|ten (p\.?m|in the evening|o.clock at night)'], []),
      'ru': ([r'22[:.]00|10 (часов )?вечера|десят\w* (часов )?вечера'], [])}),
    ('num-phone', 'number', 'המספר שלי הוא 054-1234567.',
     {'en': ([r'#0541234567'], []), 'ru': ([r'#0541234567'], [])}),
    ('num-250-nis', 'number', 'זה עולה 250 שקלים.',
     {'en': ([r'\b250\b', r'shekel|NIS|ILS|₪'], []), 'ru': ([r'\b250\b', r'шекел|₪'], [])}),
    ('num-1200', 'number', 'שילמתי אלף ומאתיים שקל על הטיפול.',
     {'en': ([r'1,?200|one thousand (and )?two hundred|twelve hundred', r'shekel|NIS|ILS|₪'], []),
      'ru': ([r'1[  ]?200|тысяч\w* дв(ест|ухсот|умстам)', r'шекел|₪'], [])}),
    ('num-dosage', 'number', 'קח שני כדורים שלוש פעמים ביום.',
     {'en': ([r'\b(two|2) (pills|tablets|capsules)', r'\b(three|3) times\b'], []),
      'ru': ([r'\b(две|2) (таблет|пилюл|капсул)', r'\b(три|3) раза\b'], [])}),
    ('num-mg', 'number', 'המינון הוא 5 מיליגרם.',
     {'en': ([r'\b5\s*(mg|milligrams?)\b'], []), 'ru': ([r'\b(5|пять)\s*(мг|миллиграмм)'], [])}),
    ('num-fever', 'number', 'חום של 38.5 מעלות.',
     {'en': ([r'38[.,]5'], []), 'ru': ([r'38[.,]5'], [])}),
    ('num-id', 'number', 'תעודת הזהות שלו מסתיימת ב־4821.',
     {'en': ([r'4821'], []), 'ru': ([r'4821'], [])}),
    ('term-referral', 'term', 'הרופא צריך לתת לך הפניה לגסטרואנטרולוג.',
     {'en': ([r'referral|\brefer', r'gastroenterologist'], [r'\blink\b']),
      'ru': ([r'направлени|направить', r'гастроэнтеролог'], [r'ссылк'])}),
    ('term-sedation', 'term', 'לפני הקולונוסקופיה תקבל סדציה ולא הרדמה מלאה.',
     {'en': ([r'colonoscopy', r'sedat', r'an(a)?esthe'], []),
      'ru': ([r'колоноскоп', r'седаци|седатив', r'наркоз|анестези'], [])}),
    ('term-fasting', 'term', 'צריך לעשות בדיקת דם בצום.',
     {'en': ([r'blood test', r'fast|empty stomach'], []), 'ru': ([r'анализ\w* крови', r'натощак|голод'], [])}),
    ('term-bp-diabetes', 'term', 'יש לו לחץ דם גבוה וסוכרת.',
     {'en': ([r'blood pressure|hypertension', r'diabet'], []), 'ru': ([r'давлени|гипертон', r'диабет'], [])}),
]


def check(text, must, must_not):
    digits = '#' + re.sub(r'\D', '', text)
    missing = [p for p in must if not (re.search(p[1:], digits) if p.startswith('#') else re.search(p, text, re.I))]
    wrong = [p for p in must_not if re.search(p, text, re.I)]
    return not missing and not wrong, missing, wrong


def run(args):
    sys.path.insert(0, str(Path(__file__).parent))
    from common import Translator, require_memory
    require_memory()
    tr = Translator(args.model, args.mode, args.seed)
    tr.translate(ITEMS[0][2], 'he-en')
    out = {}
    for pair in ('he-en', 'he-ru'):
        for n, (key, _, he, _) in enumerate(ITEMS):
            out.setdefault(pair, {})[key] = tr.translate(he, pair, key=n)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f'peak MLX {tr.peak_gb():.2f} GB')


def score(args):
    runs = {path.stem: json.loads(path.read_text()) for path in args.runs}
    cats = sorted({item[1] for item in ITEMS})
    for pair in ('he-en', 'he-ru'):
        lang = pair[-2:]
        print(f'\n{pair}: passed items per category')
        print('run'.ljust(28) + ''.join(c.ljust(9) for c in cats) + 'total')
        for name, run in runs.items():
            row = name[:27].ljust(28)
            total = 0
            for cat in cats:
                items = [i for i in ITEMS if i[1] == cat]
                ok = sum(check(run[pair][i[0]]['text'], *i[3][lang])[0] for i in items)
                total += ok
                row += f'{ok}/{len(items)}'.ljust(9)
            print(row + f'{total}/{len(ITEMS)}')
        if args.verbose:
            for key, cat, he, rules in ITEMS:
                for name, run in runs.items():
                    ok, missing, wrong = check(run[pair][key]['text'], *rules[lang])
                    if not ok:
                        print(f'  FAIL {name} {key}: {run[pair][key]["text"]!r} missing={missing} wrong={wrong}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('model', choices=['milmmt', 'hy4', 'hy8', 'hybf16'])
    r.add_argument('out', type=Path)
    r.add_argument('--mode', choices=['greedy', 'rp', 'rec'], default='greedy')
    r.add_argument('--seed', type=int, default=1)
    s = sub.add_parser('score')
    s.add_argument('runs', nargs='+', type=Path)
    s.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    run(args) if args.cmd == 'run' else score(args)
