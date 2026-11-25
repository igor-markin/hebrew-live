"""Phone menus: «… הקישו 2». The telephone band makes the recognizer write «הקישו» (press) and the
«אנא» (please) before it as other words; the translator then invents («ответьте на сообщение 2»).

`fix` replaces them for the translator only, and writes the button's number as a digit («press two»
became «нажмите две клавиши», «набрать два номера»), word for word: the count of words stays, the shown
Hebrew stays. `button` says that a menu phrase ends here: after the number. Rules were collected
from 4 recorded menus and their shifted replays; on 500 other clips they change nothing.
HEBREW_LIVE_MENU=0 switches both off."""
import os
import re

EDGE = '.,?!…:;"'
DIGITS = {word: str(digit) for digit, words in enumerate(
    ('אפס', 'אחת אחד', 'שתיים שתים שניים', 'שלוש שלושה', 'ארבע ארבעה', 'חמש חמישה', 'שש שישה', 'שבע שבעה', 'שמונה',
     'תשע תשעה')) for word in words.split()}
NUMBERS = {*DIGITS, 'כוכבית', 'סולמית'}
PRESS = {'קישו', 'כישו', 'קיישו', 'כיישו', 'הקיישו', 'הקייסו', 'הכישו', 'הכיישו'}     # not Hebrew words
NEAR = {'הקישור', 'הקיישור', 'הקישוש', 'קישוש', 'הקשוש', 'קישור', 'כישור'}   # only before a number
PLEASE = {'אנה', 'אנאה', 'ענה', 'הענה', 'אמא', 'אימא', 'אנהג'}                       # only before «הקישו»
SPLIT = {'שו': ('כי', 'קי', 'הקי'), **dict.fromkeys(('ישו', 'ישוע'), ('הענק', 'ענק', 'אנהג'))}   # «אנא הקישו» cut elsewhere
VERBS = ('הקישו', 'להקיש')
SIX = re.compile('ה?קישוש+י*ש+')     # «הקישו שש» in one word


def enabled():
    return os.environ.get('HEBREW_LIVE_MENU', '1') != '0'


def _core(word):
    return word.strip(EDGE)


def _tail(word):
    return word[len(word.rstrip(EDGE)):]


def _number(word):
    return _core(word) in NUMBERS or re.fullmatch(r'\d{1,2}', _core(word)) is not None


def fix(text):
    words = text.split(' ')
    out = list(words)
    for i, word in enumerate(words):
        core = _core(word)
        before_number = i + 1 < len(words) and _number(words[i + 1])
        joined = re.fullmatch(r'(\S+?)-(\S+)', core)     # «הקיישו-שתיים»
        press = core == 'הקישו'
        if core in PRESS or core in NEAR and before_number:
            out[i], press = 'הקישו' + ('' if before_number else _tail(word)), True
        elif joined and joined[1] in PRESS | NEAR and _number(joined[2]):
            out[i], press = f'הקישו-{joined[2]}' + _tail(word), True
        elif SIX.fullmatch(core):
            out[i], press = 'הקישו-שש' + _tail(word), True
        elif core == 'להקי' and before_number:
            out[i] = 'להקיש'
        elif before_number and i and _core(words[i - 1]) in SPLIT.get(core, ()):
            out[i - 1], out[i] = 'אנא', 'הקישו'
        if press and i and _core(words[i - 1]) in PLEASE and out[i - 1] == words[i - 1]:
            out[i - 1] = 'אנא' + _tail(words[i - 1])
    for i, word in enumerate(out):
        core = _core(word)
        if i and core in DIGITS and _core(out[i - 1]) in VERBS:
            out[i] = word.replace(core, DIGITS[core])
        elif core.startswith('הקישו-') and core[6:] in DIGITS:
            out[i] = word.replace(core, 'הקישו-' + DIGITS[core[6:]])
    return ' '.join(out)


def button(words):
    """Whether the last of these words is the number of a menu button, with its subject before it:
    «לשירות לקוחות הקישו 2», «לחידוש פוליסה יש להקיש שתיים»; not «הקישו 2», whose subject follows."""
    said = fix(' '.join(words)).split(' ')
    if len(said) >= 3 and _number(said[-1]) and _core(said[-2]) in VERBS:
        return any(_core(word) not in ('אנא', 'יש', 'נא') for word in said[:-2])
    joined = re.fullmatch(r'הקישו-(\S+)', _core(said[-1]))
    return bool(joined and _number(joined[1]) and len(said) >= 2)


def number_awaited(text):
    """Whether this Hebrew ends right before a button number («…, אנא הקישו»)."""
    return _core(fix(text).split(' ')[-1]) in VERBS
