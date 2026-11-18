"""Streaming behaviour from zipformer_run.py --trace files. Prints numbers only.

    python3 experiments/streaming-asr/streaming_metrics.py TRACE.json [TRACE.json ...]

Per item, the trace holds every change of the partial result with `t` = seconds of audio pushed so far, and the
token list with each token's emission time `ts` (seconds from stream start, as the model reports it).
  rewrites       a later partial whose token list does not start with the previous one (text taken back)
  word delay     t when a word's last token first shows minus that token's own emission time: the chunking delay
                 (audio arrives in 0.1 s pieces, the encoder runs on 1.28 s chunks)
  last-word lag  t when the last word shows minus the energy-based end of speech: what a listener waits after the
                 speaker stops; `ts - speech_end` of that word is the model's own emission lag
  punctuation    t when . , ? shows minus t when the word before it showed (does the mark wait for the next chunk?)
Last-word lag counts only items with at least 2.9 s between the end of speech and input_finished (run with
--tail 4; 1.28 s chunk + lookahead + 0.1 s piece fit in it), and only words that show before that final flush;
words that need the flush are counted separately.
"""
import json
import statistics as st
import sys


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else float('nan')


def summary(label, values, unit='s'):
    if not values:
        return f'{label}: n=0'
    return (f'{label}: n={len(values)}, p10 {pct(values, .1):.2f}, p50 {st.median(values):.2f}, '
            f'p90 {pct(values, .9):.2f}, max {max(values):.2f} {unit}')


for path in sys.argv[1:]:
    data = json.loads(open(path).read())
    meta = data.pop('_meta', {})
    rewrites = changes = taken_back = 0
    word_delay, last_lag, emit_lag, punct_wait, first_word = [], [], [], {'.': [], ',': [], '?': []}, []
    decode_ms = []
    needed_flush = 0
    for key, row in data.items():
        decode_ms += row.get('decode_ms', [])
        trace = [e for e in row.get('trace', []) if e['seg'] == 0]
        if not trace:
            continue
        for prev, cur in zip(trace, trace[1:]):
            changes += 1
            if cur['tokens'][:len(prev['tokens'])] != prev['tokens']:
                rewrites += 1
                same = 0
                while same < min(len(prev['tokens']), len(cur['tokens'])) and prev['tokens'][same] == cur['tokens'][same]:
                    same += 1
                taken_back += len(prev['tokens']) - same
        final = trace[-1]
        tokens, ts = final['tokens'], final['ts']
        # first time each token index is present (append-only streams; rewrites are counted above)
        shown = []
        for e in trace:
            while len(shown) < len(e['tokens']):
                shown.append(e['t'])
        # words: a token starting with a space opens a word; punctuation tokens belong to no word
        ends = []
        for i, tok in enumerate(tokens):
            if tok.strip() in {'.', ',', '?', '!'}:
                if ends:
                    punct_wait[tok.strip()].append(shown[i] - shown[ends[-1]])
                continue
            if tok.startswith(' ') or not ends:
                ends.append(i)
            else:
                ends[-1] = i
        for i in ends:
            word_delay.append(shown[i] - ts[i])
        if ends:
            first_word.append(shown[ends[0]] - ts[ends[0]])
        end = row.get('speech_end')
        total = row['audio_seconds'] + meta.get('tail', 1.5)
        if ends and end is not None and total - end >= 2.9:
            if shown[ends[-1]] < total - 0.05:
                last_lag.append(shown[ends[-1]] - end)
                emit_lag.append(ts[ends[-1]] - end)
            else:
                needed_flush += 1
    print(path.rsplit('/', 1)[-1], f"(threads {meta.get('threads')}, precision {meta.get('precision')}, peak RSS {meta.get('peak_rss_mb', 0):.0f} MB)")
    print(f'  partial changes {changes}, rewrites {rewrites} ({taken_back} tokens taken back)')
    print('  ' + summary('word delay (shown - emitted)', word_delay))
    print('  ' + summary('last word after end of speech', last_lag))
    print('  ' + summary('emission time of last word - end of speech', emit_lag) + f'; last word only at the final flush: {needed_flush}')
    for mark, values in punct_wait.items():
        print('  ' + summary(f'"{mark}" shown after its word', values))
    print('  ' + summary('decode call per 1.28 s chunk', decode_ms, 'ms'))
