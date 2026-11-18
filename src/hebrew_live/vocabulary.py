"""The owner's own words: terms and names with the translations he wants.

Translation is told about the entries that occur in the phrase. Recognition can take the
words as the text that came just before the audio (`HEBREW_LIVE_VOCABULARY_ASR=1`), but that
is off: a list of 29 terms raised word errors on speech without those words from 947 to 1184
(eval-d1) and from 1585 to 1889 (eval-whatsapp), see experiments/tail-only. Whisper reads only
the last 223 tokens of such text - about 35 Hebrew terms - so a longer list is cut to what
fits, entries at the top of the list first. An empty vocabulary changes nothing.
"""
import json
import os
import tempfile
from dataclasses import asdict, dataclass

from .paths import data_root

ASR_PROMPT_TOKENS = 200      # Whisper keeps the last n_ctx // 2 - 1 = 223 prompt tokens
TRANSLATOR_TERMS = 8         # terms of one phrase handed to the translator
PREFIXES = 'ובלהמכש'         # "and", "in", "to", "the", "from", "as", "that" are glued to the word
FILE = 'vocabulary.json'


@dataclass(frozen=True)
class Entry:
    he: str                  # the spelling recognition should produce
    ru: str = ''             # how to translate it, when the owner cares
    en: str = ''


def enabled():
    return os.environ.get('HEBREW_LIVE_VOCABULARY', '1') != '0'


def asr_enabled():
    return os.environ.get('HEBREW_LIVE_VOCABULARY_ASR', '0') == '1'


def path():
    return data_root() / FILE


def clean(text):
    return ' '.join(str(text or '').split())


def load(source=None):
    """Entries in priority order. A missing or unreadable file is an empty vocabulary:
    a broken list must not keep a call from being translated."""
    try:
        with open(source or path(), encoding='utf8') as file:
            items = json.load(file)['entries']
        entries = []
        for item in items:
            entry = Entry(clean(item.get('he')), clean(item.get('ru')), clean(item.get('en')))
            if entry.he and all(entry.he != other.he for other in entries):
                entries.append(entry)
        return entries
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def damaged(source=None):
    """True when the file exists but is not a list `load` can read: an editor must not
    replace a hand-edited list it could not read with an empty one."""
    try:
        with open(source or path(), encoding='utf8') as file:
            return not isinstance(json.load(file)['entries'], list)
    except FileNotFoundError:
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return True


def save(entries, target=None):
    target = target or path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=os.path.dirname(target), prefix='.vocabulary-')
    try:
        with os.fdopen(handle, 'w', encoding='utf8') as file:
            json.dump(dict(version=1, entries=[asdict(entry) for entry in entries]), file, ensure_ascii=False, indent=1)
        os.replace(temporary, target)        # never leave a half-written list behind
    except BaseException:
        os.unlink(temporary)
        raise


class Watched:
    """The list as the file says now. The engine lives in a child process; re-reading the file
    when its time, size or inode changes (a save replaces it) lets the window's edits reach the
    next translation without a restart, for the price of one stat per translation."""

    def __init__(self, source=None):
        self.source, self.signature, self.entries = source, None, []

    def current(self):
        target = self.source or path()
        try:
            info = os.stat(target)
            signature = (info.st_mtime_ns, info.st_size, info.st_ino)
        except OSError:
            signature = None
        if signature != self.signature:
            self.signature, self.entries = signature, load(target) if signature else []
        return self.entries


def add(entries, he, ru='', en=''):
    """The word goes to the top: what the owner touched last matters most."""
    entry = Entry(clean(he), clean(ru), clean(en))
    if not entry.he:
        raise ValueError('A vocabulary entry needs the Hebrew spelling')
    return [entry, *remove(entries, entry.he)]


def remove(entries, he):
    return [entry for entry in entries if entry.he != clean(he)]


def _bare(word):
    return word.strip('.,?!…:;"\'()[]-–—')


def relevant(entries, text, language, limit=TRANSLATOR_TERMS):
    """(Hebrew, translation) of the entries that occur in `text` and have a translation into
    `language`. The translator is told only about these: with the whole list in every request
    it followed fewer terms and inserted one that was not said (hy-mt2 report, glossary)."""
    words = [_bare(word) for word in text.split()]
    found = []
    for entry in entries:
        target = getattr(entry, language, '') if language in ('ru', 'en') else ''
        parts = entry.he.split()
        if not target or len(found) == limit:
            continue
        for index in range(len(words) - len(parts) + 1):
            glued = words[index][:-len(parts[0])] if words[index].endswith(parts[0]) else None
            if (glued is not None and len(glued) <= 2 and all(letter in PREFIXES for letter in glued)
                    and words[index + 1:index + len(parts)] == parts[1:]):
                found.append((entry.he, target))
                break
    return found


def asr_prompt(entries, count, budget=ASR_PROMPT_TOKENS):
    """(prompt, entries used). `count(text)` is the recognizer's own token count; an entry
    that no longer fits is skipped, shorter ones after it may still fit.

    The list ends with a period. Without it Whisper takes the speech for more of the list
    and drops it: 429 of 735 words were lost on 20 windows of ordinary speech, 3 with the
    period (29 terms, 2026-11-18)."""
    text = lambda items: ', '.join(item.he for item in items) + '.'
    used = []
    for entry in entries:
        if count(text((*used, entry))) <= budget:
            used.append(entry)
    return (text(used) if used else ''), used
