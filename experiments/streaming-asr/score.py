"""Score hypothesis files from zipformer_run.py / whisper_run.py. Prints numbers only, no speech text.

    python3 experiments/streaming-asr/score.py wer SET A.json [B.json ...]      # WER, paired diff of each run vs the first
    python3 experiments/streaming-asr/score.py punct SET A.json [B.json ...]    # punctuation and sentence boundaries
    python3 experiments/streaming-asr/score.py terms SET A.json [B.json ...]    # digits, Latin-script words, number words
    python3 experiments/streaming-asr/score.py noise A.json [B.json ...]        # words produced on synthetic non-speech
    python3 experiments/streaming-asr/score.py examples fleurs A.json B.json    # digit/Latin words, public FLEURS only

Normalisation and WER: experiments/corpus/normalize.py (ivrit.ai leaderboard rules), the same as for the Whisper
numbers in docs/NN_PHASE1_RESULTS.ru.md. Paired 95 % interval: bootstrap over recordings/clips.
"""
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'corpus'))
from normalize import normalize  # noqa: E402

REFS = Path.home() / 'Library' / 'Caches' / 'hebrew-live-refs'


def references(name):
    import csv
    if name == 'fleurs':
        tsv = REFS / 'fleurs-he_il' / 'data' / 'he_il' / 'test.tsv'
        return {row[1]: row[2] for row in csv.reader(tsv.open(encoding='utf-8'), delimiter='\t', quoting=csv.QUOTE_NONE)}
    return json.loads((REFS / f'ivrit-eval-{name}' / 'extracted' / 'texts.json').read_text(encoding='utf-8'))


def load(path):
    data = json.loads(Path(path).read_text())
    data.pop('_meta', None)
    return data


def align(ref, hyp):
    """Levenshtein alignment: list of (ref_word|None, hyp_word|None)."""
    n, m = len(ref), len(hyp)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        row, prev, r = cost[i], cost[i - 1], ref[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j - 1] + (r != hyp[j - 1]), prev[j] + 1, row[j - 1] + 1)
    pairs, i, j = [], n, m
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            pairs.append((ref[i - 1], hyp[j - 1])); i -= 1; j -= 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            pairs.append((ref[i - 1], None)); i -= 1
        else:
            pairs.append((None, hyp[j - 1])); j -= 1
    return pairs[::-1]


def errors(ref, hyp):
    pairs = align(ref, hyp)
    s = sum(1 for a, b in pairs if a is not None and b is not None and a != b)
    d = sum(1 for a, b in pairs if b is None)
    i = sum(1 for a, b in pairs if a is None)
    return s, d, i


def bootstrap(diff, words, rounds=2000, seed=1):
    rng = random.Random(seed)
    n = len(diff)
    stats = sorted(sum(diff[k] for k in pick) / sum(words[k] for k in pick)
                   for pick in ([rng.randrange(n) for _ in range(n)] for _ in range(rounds)))
    return stats[int(.025 * rounds)], stats[int(.975 * rounds)]


def wer(name, paths):
    reference = references(name)
    runs = [load(p) for p in paths]
    keys = [k for k in runs[0] if k in reference and all(k in r for r in runs)]
    base = None
    for path, run in zip(paths, runs):
        per, words, sdi = [], [], [0, 0, 0]
        for k in keys:
            ref = normalize(reference[k]).split()
            e = errors(ref, normalize(run[k]['text']).split())
            sdi = [a + b for a, b in zip(sdi, e)]
            per.append(sum(e)); words.append(len(ref))
        audio = sum(run[k]['audio_seconds'] for k in keys)
        line = (f'{Path(path).stem}: WER {sum(per) / sum(words) * 100:.2f} % (S {sdi[0]}, D {sdi[1]}, I {sdi[2]}) '
                f'over {sum(words)} words, {len(keys)} items, {audio / 60:.1f} min; empty {sum(1 for k in keys if not run[k]["text"].strip())}; '
                f'time/audio {sum(run[k]["seconds"] for k in keys) / audio:.4f}')
        if 'cpu_seconds' in run[keys[0]]:
            line += f', cpu/audio {sum(run[k]["cpu_seconds"] for k in keys) / audio:.4f}'
        if base is None:
            base = per
        else:
            diff = [b - a for a, b in zip(base, per)]
            low, high = bootstrap(diff, words)
            line += f'\n   vs first: {sum(diff) / sum(words) * 100:+.2f} pp (95 % {low * 100:+.2f} .. {high * 100:+.2f})'
        print(line)


SENTENCE_END = re.compile(r'[.?!]["”׳\']?$')


def marked_words(text):
    """[(normalised word, ends_sentence, has_comma)] keeping the punctuation that followed each raw token."""
    out = []
    for raw in text.split():
        words = normalize(raw).split()
        if not words:
            if out and SENTENCE_END.search(raw):
                out[-1] = (out[-1][0], True, out[-1][2])
            continue
        for w in words[:-1]:
            out.append((w, False, False))
        out.append((words[-1], bool(SENTENCE_END.search(raw)), raw.rstrip('"\'”').endswith(',')))
    return out


def punct(name, paths):
    reference = references(name)
    for path in paths:
        run = load(path)
        keys = [k for k in run if k in reference]
        counts = {'.': 0, ',': 0, '?': 0, '!': 0}
        ref_counts = dict.fromkeys(counts, 0)
        words = ref_words = 0
        tp = fp = fn = 0
        ctp = cfp = cfn = 0
        ends_with_stop = 0
        minutes = sum(run[k]['audio_seconds'] for k in keys) / 60
        for k in keys:
            hyp_text, ref_text = run[k]['text'], reference[k]
            for c in counts:
                counts[c] += hyp_text.count(c)
                ref_counts[c] += ref_text.count(c)
            hyp, ref = marked_words(hyp_text), marked_words(ref_text)
            words += len(hyp); ref_words += len(ref)
            ends_with_stop += bool(SENTENCE_END.search(hyp_text.strip()))
            # boundary agreement on aligned word pairs (substitutions count as aligned positions)
            pairs = align([w for w, _, _ in ref], [w for w, _, _ in hyp])
            i = j = 0
            for a, b in pairs:
                if a is not None and b is not None:
                    r, h = ref[i][1], hyp[j][1]
                    tp += r and h; fp += h and not r; fn += r and not h
                    r, h = ref[i][2], hyp[j][2]
                    ctp += r and h; cfp += h and not r; cfn += r and not h
                i += a is not None
                j += b is not None
        def f1(t, p, n):
            return (t / (t + p) if t + p else 0), (t / (t + n) if t + n else 0)
        pr, rc = f1(tp, fp, fn)
        cpr, crc = f1(ctp, cfp, cfn)
        print(f'{Path(path).stem}: per 100 words hyp . {counts["."] / words * 100:.1f} , {counts[","] / words * 100:.1f} '
              f'? {counts["?"] / words * 100:.2f} | ref . {ref_counts["."] / ref_words * 100:.1f} , {ref_counts[","] / ref_words * 100:.1f} '
              f'? {ref_counts["?"] / ref_words * 100:.2f}; sentence ends per minute hyp {(counts["."] + counts["?"] + counts["!"]) / minutes:.1f} '
              f'ref {(ref_counts["."] + ref_counts["?"] + ref_counts["!"]) / minutes:.1f}; items ending with . ? ! {ends_with_stop}/{len(keys)}\n'
              f'   sentence-end vs reference on aligned words: precision {pr:.2f} recall {rc:.2f} (tp {tp}, fp {fp}, fn {fn}); '
              f'comma precision {cpr:.2f} recall {crc:.2f}')


HEBREW_NUMBER = set(normalize('אחד אחת שתיים שניים שני שתי שלוש שלושה ארבע ארבעה חמש חמישה שש שישה שבע שבעה שמונה תשע תשעה '
                              'עשר עשרה עשרים שלושים ארבעים חמישים שישים שבעים שמונים תשעים מאה מאתיים מאות אלף אלפיים אלפים '
                              'מיליון מיליארד').split())


def terms(name, paths):
    """Recall of reference words written with digits or Latin letters; how often the hypothesis writes digits."""
    reference = references(name)
    for path in paths:
        run = load(path)
        keys = [k for k in run if k in reference]
        stats = {'digits': [0, 0], 'latin': [0, 0], 'number-words': [0, 0]}
        hyp_digit = hyp_latin = hyp_numword = 0
        for k in keys:
            ref, hyp = normalize(reference[k]).split(), normalize(run[k]['text']).split()
            hyp_digit += sum(1 for w in hyp if re.search(r'\d', w))
            hyp_latin += sum(1 for w in hyp if re.search(r'[a-z]', w))
            hyp_numword += sum(1 for w in hyp if w.lstrip('ובלהשמכ') in HEBREW_NUMBER or w in HEBREW_NUMBER)
            for a, b in align(ref, hyp):
                if a is None:
                    continue
                for cat, test in (('digits', re.search(r'\d', a)), ('latin', re.search(r'[a-z]', a)),
                                  ('number-words', a in HEBREW_NUMBER or a.lstrip('ובלהשמכ') in HEBREW_NUMBER)):
                    if test:
                        stats[cat][1] += 1
                        stats[cat][0] += a == b
        print(f'{Path(path).stem}: ' + '; '.join(f'{c} correct {ok}/{n} ({ok / n * 100 if n else 0:.0f} %)' for c, (ok, n) in stats.items())
              + f' | hyp tokens with digits {hyp_digit}, Latin {hyp_latin}, number words {hyp_numword}')


def examples(name, paths, limit=12):
    """FLEURS only (public data): reference words with digits or Latin letters and what each run wrote there."""
    assert name == 'fleurs', 'examples are printed for public FLEURS clips only'
    reference = references(name)
    runs = [load(p) for p in paths]
    shown = 0
    for k in reference:
        if not all(k in r for r in runs):
            continue
        ref = normalize(reference[k]).split()
        if not any(re.search(r'[\d a-z]', w) for w in ref):
            continue
        cols = []
        for run in runs:
            got = {}
            idx = 0
            for a, b in align(ref, normalize(run[k]['text']).split()):
                if a is not None:
                    got[idx] = b
                    idx += 1
            cols.append(got)
        for i, w in enumerate(ref):
            if re.search(r'[\da-z]', w) and any(c.get(i) != w for c in cols):
                print(f'{k[:8]} ref {w!r}: ' + ' | '.join(f'{Path(p).stem} {c.get(i)!r}' for p, c in zip(paths, cols)))
                shown += 1
        if shown >= limit:
            break


def noise(paths):
    for path in paths:
        run = load(path)
        parts = []
        for k, r in run.items():
            n = len(normalize(r['text'].replace('|', ' ')).split())
            parts.append(f'{k} {n}')
        print(f'{Path(path).stem}: words per 60 s: ' + ', '.join(parts))


if __name__ == '__main__':
    kind = sys.argv[1]
    if kind == 'noise':
        noise(sys.argv[2:])
    else:
        {'wer': wer, 'punct': punct, 'terms': terms, 'examples': examples}[kind](sys.argv[2], sys.argv[3:])
