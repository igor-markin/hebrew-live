"""Does the Russian name the weekday the Hebrew names?

The translator confuses Hebrew weekdays: on 23.11.2026 MiLMMT turned «ביום שלישי» (Tuesday) into
«четверг» and «ראשון עד חמישי» (Sunday to Thursday) into «с понедельника по четверг», even when
it translated the whole phrase at once. Hebrew weekdays are ordinals (ראשון «first», שני «second,
two»), so a word counts as a day only next to «יום/ימים» or in a range from such a day
(«בימים ראשון עד חמישי»); «שבת» counts on its own. A day in the Russian that the Hebrew does
not support is only reported.

    fix(source, translation)   -> (translation with wrong days replaced, issues)

A replacement is made only when the Hebrew days and the Russian days pair up one to one in
order; the replacement keeps the case of the word it replaces («с понедельника» -> «с
воскресенья»). Everything else is an issue for the reader, never a silent change.
"""
import re
from typing import NamedTuple

DAYS = ('sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat')

_HE_DAY = {'ראשון': 'sun', 'שני': 'mon', 'שלישי': 'tue', 'רביעי': 'wed', 'חמישי': 'thu', 'שישי': 'fri',
           'א': 'sun', 'ב': 'mon', 'ג': 'tue', 'ד': 'wed', 'ה': 'thu', 'ו': 'fri'}
_HE_DAY_WORD = ('יום', 'ימים')    # a prefix may stand before them: «ביום», «בימים»
_HE_RANGE = ('עד', 'ועד', 'עד-', '-', '–')
_PREFIXES = 'ובלמהכש'
_HE_TOKEN = re.compile(r"[א-ת]+['׳’]?|[-–]")

# Russian forms by case. Masculine nominative and accusative are one form; the case is told by
# the preposition before it.
_RU_FORMS = {
    'sun': dict(nom='воскресенье', gen='воскресенья', dat='воскресенью', acc='воскресенье', ins='воскресеньем',
                pre='воскресенье', pl='воскресенья', pl_gen='воскресений', pl_dat='воскресеньям',
                pl_ins='воскресеньями', pl_pre='воскресеньях'),
    'mon': dict(nom='понедельник', gen='понедельника', dat='понедельнику', acc='понедельник', ins='понедельником',
                pre='понедельнике', pl='понедельники', pl_gen='понедельников', pl_dat='понедельникам',
                pl_ins='понедельниками', pl_pre='понедельниках'),
    'tue': dict(nom='вторник', gen='вторника', dat='вторнику', acc='вторник', ins='вторником', pre='вторнике',
                pl='вторники', pl_gen='вторников', pl_dat='вторникам', pl_ins='вторниками', pl_pre='вторниках'),
    'wed': dict(nom='среда', gen='среды', dat='среде', acc='среду', ins='средой', pre='среде', pl='среды',
                pl_gen='сред', pl_dat='средам', pl_ins='средами', pl_pre='средах'),
    'thu': dict(nom='четверг', gen='четверга', dat='четвергу', acc='четверг', ins='четвергом', pre='четверге',
                pl='четверги', pl_gen='четвергов', pl_dat='четвергам', pl_ins='четвергами', pl_pre='четвергах'),
    'fri': dict(nom='пятница', gen='пятницы', dat='пятнице', acc='пятницу', ins='пятницей', pre='пятнице',
                pl='пятницы', pl_gen='пятниц', pl_dat='пятницам', pl_ins='пятницами', pl_pre='пятницах'),
    'sat': dict(nom='суббота', gen='субботы', dat='субботе', acc='субботу', ins='субботой', pre='субботе',
                pl='субботы', pl_gen='суббот', pl_dat='субботам', pl_ins='субботами', pl_pre='субботах'),
}
_RU_ADJECTIVES = {'субботн': 'sat', 'воскресн': 'sun', 'пятничн': 'fri', 'понедельничн': 'mon'}
_RU_SHABBAT = re.compile(r'ша+бб?ат\w*', re.I)
_RU_LOOKUP = {}
for _day, _forms in _RU_FORMS.items():
    for _case, _form in _forms.items():
        _RU_LOOKUP.setdefault(_form, (_day, []))[1].append(_case)
_RU_WORD = re.compile(r'[А-Яа-яЁё]+')
_ACCUSATIVE = {'в', 'во', 'на', 'про', 'через', 'за', 'по'}   # «по четверг» is «up to Thursday»


class Issue(NamedTuple):
    kind: str       # 'fixed', 'wrong' (left as is), 'missing', 'extra'
    he: str         # the Hebrew day word ('' for 'extra')
    ru: str         # the Russian word as written ('' for 'missing')
    expected: str   # the day the Hebrew names, as a Russian nominative ('' for 'extra')


def _bare(token):
    return token.rstrip("'׳’")


def _day_of(token, letters):
    bare = _bare(token)
    for i in range(min(3, len(bare))):
        if all(c in _PREFIXES for c in bare[:i]):
            rest = bare[i:]
            if rest == 'שבת':
                return 'sat'
            # «ה» alone is the article, not Thursday: a letter day needs its geresh, «יום ה'».
            if rest in _HE_DAY and (len(rest) > 1 or letters and token != bare):
                return _HE_DAY[rest]
    return None


def _is_day_word(token):
    bare = _bare(token)
    return any(bare[i:] in _HE_DAY_WORD for i in range(min(3, len(bare)))
               if all(c in _PREFIXES for c in bare[:i]))


def hebrew_days(source):
    """[(day, word)] the Hebrew names as weekdays, in order: after «יום/ימים», in a range that
    goes on from such a day, in a range of two ordinals («ראשון עד חמישי»), and «שבת»."""
    tokens = _HE_TOKEN.findall(source)
    ranged = set()   # ordinals that stand on both sides of «עד»
    for i in range(len(tokens) - 2):
        if _bare(tokens[i + 1]) in _HE_RANGE and _day_of(tokens[i], False) and _day_of(tokens[i + 2], False):
            ranged.update((i, i + 2))
    found = []
    expect = last_day = False
    for i, token in enumerate(tokens):
        if _is_day_word(token):
            expect, last_day = True, False
            continue
        if _bare(token) in _HE_RANGE:
            expect, last_day = last_day, False
            continue
        day = _day_of(token, True)
        if day != 'sat' and not (expect or i in ranged):
            day = None
        if day is not None:
            found.append((day, token))
        expect, last_day = False, day is not None
    return found


def _russian_days(translation):
    """[(day, cases, match)] for every Russian weekday word, in order."""
    found = []
    for match in _RU_WORD.finditer(translation):
        word = match.group().lower().replace('ё', 'е')
        if word in _RU_LOOKUP:
            day, cases = _RU_LOOKUP[word]
            found.append((day, cases, match))
        elif _RU_SHABBAT.fullmatch(word):
            found.append(('sat', ['shabbat'], match))
        elif word.startswith(tuple(_RU_ADJECTIVES)):
            # «субботний», «воскресного»: the day is named, but its case cannot be carried over.
            found.append((_RU_ADJECTIVES[next(a for a in _RU_ADJECTIVES if word.startswith(a))], ['adj'], match))
    return found


def _case_of(translation, match, cases):
    if len(cases) == 1:
        return cases[0]
    before = translation[:match.start()].split()
    preposition = before[-1].lower() if before else ''
    if 'acc' in cases and preposition in _ACCUSATIVE:
        return 'acc'
    if 'nom' in cases:
        return 'nom'
    if 'pre' in cases and preposition in ('в', 'во', 'о', 'об'):
        return 'pre'
    return cases[0]


def _cased(form, like):
    return form.capitalize() if like[:1].isupper() else form


def fix(source, translation, frozen=0):
    """(translation, issues). Days at or after character `frozen` may be replaced; a wrong day
    before it (already on screen and never changed) is only reported."""
    he = hebrew_days(source)
    ru = _russian_days(translation)
    issues = []
    expected = [day for day, _ in he]
    named = [day for day, _, _ in ru]
    if expected and len(expected) == len(named):
        pieces, at = [], 0
        for (day, word), (got, cases, match) in zip(he, ru):
            if got == day:
                continue
            case = _case_of(translation, match, cases)
            if case == 'adj':
                issues.append(Issue('wrong', word, match.group(), _RU_FORMS[day]['nom']))
                continue
            wanted = _RU_FORMS[day]['nom' if case == 'shabbat' else case]
            if match.start() >= frozen:
                before = translation[at:match.start()]
                # «в четверг» but «во вторник»
                preposition = re.search(r'(?<![А-Яа-яЁё])([Вв])(о?)(\s+)$', before)
                if preposition and preposition.start(1) >= frozen:
                    vo = 'о' if wanted.startswith('вт') else ''
                    before = before[:preposition.start(2)] + vo + preposition.group(3)
                pieces += [before, _cased(wanted, match.group())]
                at = match.end()
                issues.append(Issue('fixed', word, match.group(), _RU_FORMS[day]['nom']))
            else:
                issues.append(Issue('wrong', word, match.group(), _RU_FORMS[day]['nom']))
        pieces.append(translation[at:])
        return ''.join(pieces), issues
    supported = set(expected)
    for day, word in he:
        if day not in named:
            issues.append(Issue('missing', word, '', _RU_FORMS[day]['nom']))
    for day, _, match in ru:
        if day not in supported:
            issues.append(Issue('extra', '', match.group(), ''))
    return translation, issues
