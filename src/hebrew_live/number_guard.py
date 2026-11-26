"""Do the figures in a translation match the figures in its source?

Only disagreements that involve digits are reported: a digit number the source has and the
translation lost, or a digit number the translation shows and the source does not support
(a day of the month spoken in words that came out as a year). Number words alone are too
ambiguous to raise an alarm on - Hebrew weekdays are ordinals, "אחד", "один" and "one" are
pronouns, "half past two" is "половина третьего" - so they are parsed generously and only
ever used to explain a digit on the other side.
"""
from typing import NamedTuple
import re


class Issue(NamedTuple):
    kind: str    # 'missing': in the source, not in the translation; 'extra': the reverse
    number: str  # the digits as written


_TOKEN = re.compile(r'\d+|[^\W\d_]+')
# "10 000" and "10,000" are one number; a dot is left alone because it also separates dates.
_THOUSANDS = re.compile(r'(?<=\d)[  ,](?=\d{3}(?!\d))')

# Roles: 'u' unit 0-9, 'x' Hebrew ten (a teen after a unit), 't' ten/teen/tens, 'h' hundreds,
# 'H' times a hundred, 'T' times a thousand, 'A' thousands added whole, 'f' stands alone.
_HE = {}
for _value, _words in enumerate(('אפס', 'אחד אחת', 'שניים שתיים שנים שתים שני שתי', 'שלוש שלושה שלושת',
                                 'ארבע ארבעה ארבעת', 'חמש חמישה חמשה חמשת חמישת', 'שש שישה ששה ששת',
                                 'שבע שבעה שבעת', 'שמונה שמונת', 'תשע תשעה תשעת')):
    _HE.update(dict.fromkeys(_words.split(), ('u', _value)))
for _value, _words in enumerate(('ראשון ראשונה', 'שנייה שניה', 'שלישי שלישית', 'רביעי רביעית', 'חמישי חמישית',
                                 'שישי שישית', 'שביעי שביעית', 'שמיני שמינית', 'תשיעי תשיעית'), 1):
    _HE.update(dict.fromkeys(_words.split(), ('u', _value)))
_HE.update(dict.fromkeys(('עשר', 'עשרה', 'עשרת'), ('x', 10)))
_HE.update({word: ('t', value) for value, word in ((20, 'עשרים'), (30, 'שלושים'), (40, 'ארבעים'), (50, 'חמישים'),
                                                   (60, 'שישים'), (60, 'ששים'), (70, 'שבעים'), (80, 'שמונים'),
                                                   (90, 'תשעים'), (10, 'עשירי'), (10, 'עשירית'))})
_HE.update({'מאה': ('h', 100), 'מאתיים': ('h', 200), 'מאות': ('H', 100), 'אלף': ('T', 1000), 'אלפים': ('T', 1000),
            'אלפיים': ('A', 2000)})
_HE.update({word: ('f', value) for word, value in (('שעתיים', 2), ('יומיים', 2), ('שבועיים', 2), ('חודשיים', 2),
                                                   ('שנתיים', 2), ('פעמיים', 2), ('פעם', 1), ('זוג', 2),
                                                   ('תריסר', 12), ('עשור', 10))})
_HE_PREFIXES = 'ובלהמכש'
_HE_HALF, _HE_QUARTER = ('חצי', 'מחצית'), ('רבע',)
# The streaming recognizer also writes «twelve» without its yod: «לשתם עשרה» for «לשתים עשרה».
_HE_TWELVE = re.compile(r'(שת|שנ)ם(?=\s+עשרה?\b)')

_EN = {}
for _value, _word in enumerate('zero one two three four five six seven eight nine'.split()):
    _EN[_word] = ('u', _value)
for _value, _word in enumerate('first second third fourth fifth sixth seventh eighth ninth'.split(), 1):
    _EN[_word] = ('u', _value)
for _value, _word in enumerate('ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(), 10):
    _EN[_word] = ('t', _value)
for _value, _word in enumerate('tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth '
                               'eighteenth nineteenth'.split(), 10):
    _EN[_word] = ('t', _value)
for _value, _word in enumerate('twenty thirty forty fifty sixty seventy eighty ninety'.split(), 2):
    _EN[_word] = ('t', _value * 10)
for _value, _word in enumerate('twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth'.split(), 2):
    _EN[_word] = ('t', _value * 10)
_EN.update({'hundred': ('H', 100), 'hundredth': ('H', 100), 'thousand': ('T', 1000), 'k': ('T', 1000),
            'once': ('f', 1), 'twice': ('f', 2), 'couple': ('f', 2), 'pair': ('f', 2), 'both': ('f', 2),
            'dozen': ('f', 12)})

_RU = {}
for _value, _words in enumerate(('ноль нуль нуля', 'один одна одно одного одной одному одним одну одном',
                                 'два две двух двум двумя', 'три трех трем тремя', 'четыре четырех четырем четырьмя',
                                 'пять пяти пятью', 'шесть шести шестью', 'семь семи семью',
                                 'восемь восьми восемью восьмью', 'девять девяти девятью')):
    _RU.update(dict.fromkeys(_words.split(), ('u', _value)))
_RU.update(dict.fromkeys('десять десяти десятью'.split(), ('t', 10)))
_RU.update(dict.fromkeys('сто ста'.split(), ('h', 100)))
_RU.update({word: ('f', 2) for word in 'оба обе обоих пара пару пары дважды'.split()})
_RU.update({'однажды': ('f', 1), 'трижды': ('f', 3), 'дюжина': ('f', 12), 'дюжину': ('f', 12)})
# Ordinals decline like adjectives; spelling out the endings keeps "пятница" and "вторник" out.
_RU_ENDINGS = 'ый ой ий ого ому ым ом ая ую ое ые ых ыми ье ья ьего ьему ьим ьем ью ьей ьи ьих ьими'.split()
for _stem, _role, _value in (('перв', 'u', 1), ('втор', 'u', 2), ('трет', 'u', 3), ('четверт', 'u', 4), ('пят', 'u', 5),
                             ('шест', 'u', 6), ('седьм', 'u', 7), ('восьм', 'u', 8), ('девят', 'u', 9),
                             ('десят', 't', 10), ('сороков', 't', 40), ('сот', 'h', 100)):
    _RU.update({_stem + ending: (_role, _value) for ending in _RU_ENDINGS})
# Long stems are unambiguous, so any ending matches: "двадцать", "двадцати", "двадцатого".
_RU_STEMS = tuple(sorted((
    ('одиннадцат', 't', 11), ('двенадцат', 't', 12), ('тринадцат', 't', 13), ('четырнадцат', 't', 14),
    ('пятнадцат', 't', 15), ('шестнадцат', 't', 16), ('семнадцат', 't', 17), ('восемнадцат', 't', 18),
    ('девятнадцат', 't', 19), ('двадцат', 't', 20), ('тридцат', 't', 30), ('сорок', 't', 40),
    ('пятьдесят', 't', 50), ('пятидесят', 't', 50), ('шестьдесят', 't', 60), ('шестидесят', 't', 60),
    ('семьдесят', 't', 70), ('семидесят', 't', 70), ('восемьдесят', 't', 80), ('восьмидесят', 't', 80),
    ('девяност', 't', 90), ('двест', 'h', 200), ('двухсот', 'h', 200), ('трист', 'h', 300), ('трехсот', 'h', 300),
    ('четырест', 'h', 400), ('четырехсот', 'h', 400), ('пятьсот', 'h', 500), ('пятисот', 'h', 500),
    ('шестьсот', 'h', 600), ('шестисот', 'h', 600), ('семьсот', 'h', 700), ('семисот', 'h', 700),
    ('восемьсот', 'h', 800), ('восьмисот', 'h', 800), ('девятьсот', 'h', 900), ('девятисот', 'h', 900),
    ('тысяч', 'T', 1000),
    # Digits named as nouns, as in a phone menu: «нажмите восьмёрку».
    ('единиц', 'f', 1), ('двойк', 'f', 2), ('тройк', 'f', 3), ('четверк', 'f', 4), ('пятерк', 'f', 5),
    ('шестерк', 'f', 6), ('семерк', 'f', 7), ('восьмерк', 'f', 8), ('девятк', 'f', 9), ('десятк', 'f', 10)),
    key=lambda item: -len(item[0])))

_HALF = {'he': _HE_HALF, 'ru': ('половин', 'полчаса', 'полови'), 'en': ('half',)}
_QUARTER = {'he': _HE_QUARTER, 'ru': ('четверть', 'четверти'), 'en': ('quarter',)}


def _classify(word, language):
    if language == 'he':
        for strip in range(3):
            if word[strip:] in _HE and all(letter in _HE_PREFIXES for letter in word[:strip]):
                return _HE[word[strip:]]
        return None
    word = word.lower()
    if language == 'en':
        return _EN.get(word)
    if language == 'ru':
        word = word.replace('ё', 'е')
        if word in _RU:
            return _RU[word]
        for stem, role, value in _RU_STEMS:
            if word.startswith(stem):
                return role, value
    return None


class _Side:
    """Digit figures of one text, plus every number its words could stand for."""

    def __init__(self, text, language, thousands=True):
        if language == 'he':
            text = _HE_TWELVE.sub(r'\1ים', text)
        found = list(_TOKEN.finditer(_THOUSANDS.sub('', text) if thousands else text))
        tokens = [match.group() for match in found]
        self.mentions = []         # (value, digits or None, character offset), every number in reading order
        self.figures = []          # (value, digits as written), digit numbers only
        self.values = set()        # integers the text can account for
        self.spoken = set()        # digit strings read out one digit at a time
        self.chunks = [token for token in tokens if token.isdigit()]
        self.concat = ''.join(self.chunks)
        self.quarter = False
        total = current = 0
        rank = 4; is_open = False; run = ''; previous = None; began = 0

        def close(adjacent=False):
            nonlocal total, current, rank, is_open, previous
            if is_open:
                value = total + current
                self.values.add(value)
                self.mentions.append((value, None, began))
                # "nineteen ninety-six": two adjacent two-digit numbers read as a year.
                if previous is not None and 10 <= previous <= 99 and value <= 99:
                    self.values.add(previous * 100 + value)
                previous = value if adjacent else None
            elif not adjacent:
                previous = None
            total = current = 0; rank = 4; is_open = False

        def end_run():
            nonlocal run
            if len(run) > 1:
                self.spoken.add(run)
            run = ''

        for index, token in enumerate(tokens):
            if token.isdigit():
                close(); end_run()
                following = _classify(tokens[index + 1], language) if index + 1 < len(tokens) else None
                value = int(token) * 1000 if following and following[0] == 'T' else int(token)
                self.figures.append((value, token)); self.values.update((value, int(token)))
                self.mentions.append((value, token, found[index].start()))
                continue
            item = _classify(token, language)
            if item is None:
                close(); end_run()
                word = token.lower()
                if any(word.startswith(stem) or word[1:].startswith(stem) for stem in _HALF.get(language, ())):
                    self.values.add(30)
                if any(word.startswith(stem) or word[1:].startswith(stem) for stem in _QUARTER.get(language, ())):
                    self.values.update((15, 45)); self.quarter = True
                continue
            role, value = item
            self.values.add(value)
            if role == 'u':
                run += str(value)
            else:
                end_run()
            if role == 'f':
                close()
                self.mentions.append((value, None, found[index].start()))
            elif role == 'T':
                began = began if is_open else found[index].start()
                total += (current or 1) * 1000; current = 0; rank = 4; is_open = True
            elif role == 'A':
                began = began if is_open else found[index].start()
                total += value; current = 0; rank = 4; is_open = True
            elif role == 'H':
                began = began if is_open else found[index].start()
                current = (current or 1) * 100; rank = 3; is_open = True
            elif role == 'x' and is_open and rank == 1 and 0 < current % 100 < 10:
                current += 10; rank = 0                      # "שלוש עשרה" is thirteen
            else:
                level = {'u': 1, 'x': 2, 't': 2, 'h': 3}[role]
                if is_open and level >= rank:
                    close(adjacent=True)                     # a new number starts: "עשרים וארבע שבע"
                began = began if is_open else found[index].start()
                current += value; rank = level; is_open = True
        close(); end_run()
        # A clock hour may come back in the other 12-hour half; "a quarter to five" names the next hour.
        hours = [value for value in self.values if 1 <= value <= 12]
        self.values.update([value - 12 for value in self.values if 13 <= value <= 23])
        self.values.update(value + 12 for value in hours if value < 12)
        if self.quarter:
            self.values.update(value - 1 for value in hours)

    def explains(self, value, digits):
        # «00» of «16:00» needs no source; a lone «0» does: «нажмите 0» for «הקישו שתיים» passed
        # unnoticed (Mor call replay, 26.11)
        return (value in self.values or not digits.strip('0') and len(digits) > 1 or digits in self.spoken
                or len(digits) >= 3 and digits in self.concat
                or any(digits in other for other in self.spoken if len(digits) >= 2)
                or any(digits in chunk for chunk in self.chunks if len(chunk) >= 7 and len(digits) >= 2))


def check(source, translation, source_language='he', target_language='ru'):
    """Digit numbers that one text has and the other cannot account for."""
    original, translated = _Side(source, source_language), _Side(translation, target_language)
    issues = [Issue('missing', digits) for value, digits in original.figures if not translated.explains(value, digits)]
    issues += [Issue('extra', digits) for value, digits in translated.figures if not original.explains(value, digits)]
    return issues


def unheard(source, shown, new, source_language='he', target_language='ru'):
    """Index of the first of the `new` words (a call's output, continuing the `shown` translation
    of `source`) that brings a number the source has not said yet, or None.

    Counted, not just looked up: «1 ... тоже 1» needs the source to say one twice. Digits and
    number words both count on the translation side, so a live translation waits for the number
    instead of guessing it; this is for stopping generation, not for an alarm (see `check`)."""
    if not new:
        return None
    origin = _Side(source, source_language)
    said = {}
    for value, _, _ in origin.mentions:
        said[value] = said.get(value, 0) + 1
    start = len(shown) + 1 if shown else 0
    text = (shown + ' ' + ' '.join(new)) if shown else ' '.join(new)
    starts, at = [], start
    for word in new:
        starts.append(at)
        at += len(word) + 1
    used = {}
    for value, digits, offset in _Side(text, target_language, thousands=False).mentions:
        used[value] = used.get(value, 0) + 1
        allowed = said.get(value) or (1 if origin.explains(value, digits or str(value)) else 0)
        if offset >= start and used[value] > allowed:
            return max(i for i, begin in enumerate(starts) if begin <= offset)
    return None
