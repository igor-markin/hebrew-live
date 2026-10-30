"""Finished sentences of a growing draft group stay on screen unchanged.

Whisper re-decodes the whole open group every second, so the text of sentences that
were already shown keeps drifting. A sentence is frozen once two recognitions in a row
agree on it, it is followed by more speech and its translation could be paired with it.
Later ASR versions are aligned against the frozen source and only the remainder (the
tail) is translated again.
"""
from difflib import SequenceMatcher
import re

TERMINAL = ('.', '!', '?', '…', '。', '！', '？')
_CLOSERS = '"\'»”)]›'
_SENTENCE = re.compile(r'.+?(?:[.!?…。！？]+[' + re.escape(_CLOSERS) + r']*(?=\s|$)|$)', re.S)
_WORD = re.compile(r'[\W_]+', re.U)
# Shown sentence pairs the translator continues from with each tail.
CONTEXT_SENTENCES = 2


def split_sentences(text):
    """Sentences in order; the last one may be unfinished. `2.5` and `50,000` are kept whole."""
    return [part.strip() for part in _SENTENCE.findall(text.strip()) if part.strip()]


def finished(sentence):
    return sentence.rstrip(_CLOSERS).endswith(TERMINAL)


def _norm(word):
    return _WORD.sub('', word).casefold()


def tail_after(frozen, text):
    """The part of `text` that follows the frozen source `frozen`.

    The new ASR version may reword the frozen part, so the cut is placed where the last
    matching run of words ends, then moved to an adjacent sentence end when one is within
    two words."""
    words = text.split()
    if not frozen.strip():
        return text.strip()
    old = [_norm(word) for word in frozen.split()]
    new = [_norm(word) for word in words]
    n = len(old)
    if new[:n] == old:
        cut = n
    else:
        blocks = [block for block in SequenceMatcher(None, old, new, autojunk=False).get_matching_blocks()
                  if block.size]
        if blocks:
            last = blocks[-1]
            cut = last.b + last.size + (n - last.a - last.size)
        else:
            cut = n
        cut = min(max(cut, 0), len(words))
        near = [index for index in range(max(1, cut - 2), min(len(words), cut + 2) + 1)
                if finished(words[index - 1])]
        if near:
            cut = min(near, key=lambda index: (abs(index - cut), -index))
    return ' '.join(words[cut:])


def same_prefix(sentences, previous):
    """How many leading sentences are word for word the same in both recognitions."""
    count = 0
    for left, right in zip(sentences, previous):
        if [_norm(word) for word in left.split()] != [_norm(word) for word in right.split()]:
            break
        count += 1
    return count


def sentence_start(text, before):
    """A new bubble that continues the previous group starts with a capital letter unless
    the previous text stopped mid-sentence; a stray leading comma is dropped."""
    text = text.lstrip(',;: ')
    if not text or not finished(before) or not text[:1].islower():
        return text
    return text[0].upper() + text[1:]


def pair_finished(source, closing):
    """How many leading sentences of `source` are finished speech, and its sentences.

    Every sentence but the last is followed by more speech; the last one counts only when
    the group closes."""
    sources = split_sentences(source)
    if closing:
        return len(sources), sources
    count = 0
    while count < len(sources) - 1 and finished(sources[count]):
        count += 1
    return count, sources


def target_cut(sources, targets, count, tolerance=.1):
    """How many leading translation sentences render the first `count` source sentences,
    or None. One to one when both sides have as many sentences; otherwise the finished
    translation sentence boundary whose share of the text is closest to the source share,
    within `tolerance` (the model may split `11 וואו,` into `11. Ого,`)."""
    if len(targets) == len(sources):
        return count if all(finished(sentence) for sentence in targets[:count]) else None
    share = lambda parts, upto: len(' '.join(parts[:upto])) / max(1, len(' '.join(parts)))
    wanted = share(sources, count)
    cuts = [index for index in range(1, len(targets)) if finished(targets[index - 1])]
    if not cuts:
        return None
    best = min(cuts, key=lambda index: abs(share(targets, index) - wanted))
    return best if abs(share(targets, best) - wanted) <= tolerance else None
