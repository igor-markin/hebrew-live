"""Translation language capabilities and stable direction identifiers.

The live product records Hebrew speech.  The optional ``ru-he`` direction is
kept for backwards-compatible CLI/archive use, but browser target switching
always keeps Hebrew as the source language.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    english_name: str
    milmmt_name: str | None = None
    rtl: bool = False


_LANGUAGES = (
    Language('ar', 'Arabic', 'Arabic', True),
    Language('az', 'Azerbaijani', 'Azerbaijani'),
    Language('bg', 'Bulgarian', 'Bulgarian'),
    Language('bn', 'Bengali', 'Bengali'),
    Language('bo', 'Tibetan'),
    Language('ca', 'Catalan', 'Catalan'),
    Language('cs', 'Czech', 'Czech'),
    Language('da', 'Danish', 'Danish'),
    Language('de', 'German', 'German'),
    Language('el', 'Greek', 'Greek'),
    Language('en', 'English', 'English'),
    Language('es', 'Spanish', 'Spanish'),
    Language('fa', 'Persian', 'Persian', True),
    Language('fi', 'Finnish', 'Finnish'),
    Language('fr', 'French', 'French'),
    Language('gu', 'Gujarati'),
    Language('he', 'Hebrew', 'Hebrew', True),
    Language('hi', 'Hindi', 'Hindi'),
    Language('hr', 'Croatian', 'Croatian'),
    Language('hu', 'Hungarian', 'Hungarian'),
    Language('id', 'Indonesian', 'Indonesian'),
    Language('it', 'Italian', 'Italian'),
    Language('ja', 'Japanese', 'Japanese'),
    Language('kk', 'Kazakh', 'Kazakh'),
    Language('km', 'Khmer', 'Khmer'),
    Language('ko', 'Korean', 'Korean'),
    Language('lo', 'Lao', 'Lao'),
    Language('mn', 'Mongolian'),
    Language('mr', 'Marathi'),
    Language('ms', 'Malay', 'Malay'),
    Language('my', 'Burmese', 'Burmese'),
    Language('nl', 'Dutch', 'Dutch'),
    Language('no', 'Norwegian', 'Norwegian'),
    Language('pl', 'Polish', 'Polish'),
    Language('pt', 'Portuguese', 'Portuguese'),
    Language('ro', 'Romanian', 'Romanian'),
    Language('ru', 'Russian', 'Russian'),
    Language('sk', 'Slovak', 'Slovak'),
    Language('sl', 'Slovenian', 'Slovenian'),
    Language('sv', 'Swedish', 'Swedish'),
    Language('ta', 'Tamil', 'Tamil'),
    Language('te', 'Telugu'),
    Language('th', 'Thai', 'Thai'),
    Language('tl', 'Tagalog', 'Tagalog'),
    Language('tr', 'Turkish', 'Turkish'),
    Language('ug', 'Uyghur', rtl=True),
    Language('uk', 'Ukrainian'),
    Language('ur', 'Urdu', 'Urdu', True),
    Language('uz', 'Uzbek', 'Uzbek'),
    Language('vi', 'Vietnamese', 'Vietnamese'),
    Language('yue', 'Cantonese', 'Cantonese'),
    Language('zh-cn', 'Chinese (Simplified)', 'Chinese (Simplified)'),
    Language('zh-tw', 'Chinese (Traditional)', 'Chinese (Traditional)'),
)

LANGUAGES = {language.code: language for language in _LANGUAGES}


def target_languages():
    """Return targets advertised by the single supported MiLMMT contract."""
    return tuple(language for language in _LANGUAGES
                 if language.code != 'he' and language.milmmt_name is not None)


def target_language_options():
    return [dict(code=language.code, name=language.english_name, rtl=language.rtl)
            for language in target_languages()]


def direction_for_target(target):
    supported = {language.code for language in target_languages()}
    if target not in supported:
        raise ValueError(f'Unsupported target language for MiLMMT: {target}')
    return f'he-{target}'


def split_direction(direction):
    if not isinstance(direction, str) or '-' not in direction:
        raise ValueError('Invalid translation direction')
    source, target = direction.split('-', 1)
    if source not in LANGUAGES or target not in LANGUAGES or source == target:
        raise ValueError('Invalid translation direction')
    return source, target


def validate_direction(direction, allow_legacy=True):
    source, target = split_direction(direction)
    if allow_legacy and (source, target) == ('ru', 'he'):
        return direction
    if source != 'he':
        raise ValueError('The live product records Hebrew speech')
    direction_for_target(target)
    return direction


def prompt_names(direction):
    source, target = split_direction(direction)
    source_name = LANGUAGES[source].milmmt_name
    target_name = LANGUAGES[target].milmmt_name
    if source_name is None or target_name is None:
        raise ValueError(f'Direction {direction} is not supported by MiLMMT')
    return source_name, target_name
