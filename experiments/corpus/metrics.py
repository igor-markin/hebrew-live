"""Dependency-free ASR and MT metrics for the corpus runs (WER, chrF++, stability helpers).

`chrf` follows the chrF++ definition (character n-grams to order 6 and word n-grams to order
2, beta 2, whitespace removed from character n-grams, punctuation split off words). It is a
local implementation: use it to compare variants against each other, and cross-check with
sacrebleu before quoting absolute numbers next to published results.
"""
from collections import Counter

from normalize import normalize


def edit_counts(reference, hypothesis):
    """(substitutions, deletions, insertions) of a minimum word edit alignment."""
    rows = len(reference) + 1
    previous = [(j, (0, 0, j)) for j in range(len(hypothesis) + 1)]
    for i in range(1, rows):
        current = [(i, (0, i, 0))]
        for j in range(1, len(hypothesis) + 1):
            same = reference[i - 1] == hypothesis[j - 1]
            options = []
            cost, (s, d, n) = previous[j - 1]
            options.append((cost + (0 if same else 1), (s + (0 if same else 1), d, n)))
            cost, (s, d, n) = previous[j]
            options.append((cost + 1, (s, d + 1, n)))
            cost, (s, d, n) = current[j - 1]
            options.append((cost + 1, (s, d, n + 1)))
            current.append(min(options, key=lambda item: item[0]))
        previous = current
    return previous[-1][1]


def wer(reference, hypothesis, fold_finals=False):
    """Word error rate of normalised texts; None when the reference has no words."""
    ref = normalize(reference, fold_finals).split()
    hyp = normalize(hypothesis, fold_finals).split()
    if not ref:
        return None
    s, d, i = edit_counts(ref, hyp)
    return (s + d + i) / len(ref)


def corpus_wer(pairs, fold_finals=False):
    """Micro-averaged WER over (reference, hypothesis) pairs, and the reference word count."""
    errors = words = 0
    for reference, hypothesis in pairs:
        ref = normalize(reference, fold_finals).split()
        hyp = normalize(hypothesis, fold_finals).split()
        s, d, i = edit_counts(ref, hyp)
        errors += s + d + i
        words += len(ref)
    return (errors / words if words else None), words


def _ngrams(items, order):
    return Counter(tuple(items[i:i + order]) for i in range(len(items) - order + 1))


def _words(text):
    tokens = []
    for word in text.split():
        trailing = []
        while len(word) > 1 and not word[-1].isalnum():
            trailing.append(word[-1])
            word = word[:-1]
        leading = []
        while len(word) > 1 and not word[0].isalnum():
            leading.append(word[0])
            word = word[1:]
        tokens += leading + [word] + trailing[::-1]
    return tokens


def chrf(hypothesis, reference, char_order=6, word_order=2, beta=2):
    """chrF++ in [0, 100]."""
    beta2 = beta * beta
    precisions, recalls = [], []
    sides = (hypothesis, reference)
    for n in range(1, char_order + 1):
        h, r = (_ngrams(''.join(text.split()), n) for text in sides)
        precisions.append((sum((h & r).values()), sum(h.values())))
        recalls.append((sum((h & r).values()), sum(r.values())))
    for n in range(1, word_order + 1):
        h, r = (_ngrams(_words(text), n) for text in sides)
        precisions.append((sum((h & r).values()), sum(h.values())))
        recalls.append((sum((h & r).values()), sum(r.values())))
    total = 0.
    counted = 0
    for (match_p, size_p), (match_r, size_r) in zip(precisions, recalls):
        if size_p == 0 or size_r == 0:
            continue
        p, r = match_p / size_p, match_r / size_r
        counted += 1
        total += 0. if p + r == 0 else (1 + beta2) * p * r / (beta2 * p + r)
    return 100. * total / counted if counted else 0.
