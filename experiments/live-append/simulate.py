"""Append-only live screen, simulated on a recording: Hebrew and translation are only ever added to.

Two ways to get Hebrew words that never change once shown:
  hybrid  the streaming zipformer (sherpa-onnx, CPU) writes words; it never rewrites them.
  agree   Whisper runs every --step seconds on the not yet committed audio; a word is shown when
          two passes in a row agree on it (LocalAgreement-2).
Shown words are translated in chunks that are only appended: each chunk is translated as the
continuation of the chunks before it (translation.prompt `pairs`), so a shown translation is
never redone. A chunk is sent when its first word was spoken --span seconds ago or a word ends
with punctuation (span 0: every time new words are shown).

Timing is a discrete-event simulation on the audio clock: model calls really run, one at a time,
and their measured time is placed on one GPU timeline (Whisper and the translator share it; the
zipformer runs on the CPU in parallel). Latency of a word = when it (or its translation) is shown
minus when it was spoken (end of the word in the audio: zipformer token time or Whisper word end).

    .venv/bin/python experiments/live-append/simulate.py A.wav --mode hybrid --span 0 \
        --zipformer DIR [--reference A.txt] [--text-dir OUT]

Prints one JSON line of numbers per recording; speech text goes only to --text-dir.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments' / 'corpus'))
from metrics import chrf, corpus_wer  # noqa: E402

RATE = 16000
MODELS = Path.home() / 'Library' / 'Application Support' / 'Hebrew Live CLI' / 'models'
END = re.compile(r'[.?!…]$')
PUNCT = re.compile(r'[.,?!…:;]$')


class Log:
    def __init__(self):
        self.events = []

    def event(self, name, **data):
        self.events.append((name, data))

    def bind(self, *_):
        pass


def stats(values):
    values = sorted(values)
    if not values:
        return {}
    pick = lambda q: values[min(len(values) - 1, int(q * len(values)))]
    return dict(p50=round(pick(.5), 3), p95=round(pick(.95), 3), max=round(values[-1], 3),
                within_2s=round(sum(v <= 2. for v in values) / len(values), 3))


class Gpu:
    """One model call at a time, on the audio clock."""

    def __init__(self):
        self.free = 0.
        self.busy = 0.

    def run(self, ready, call):
        start = max(ready, self.free)
        began = time.perf_counter()
        result = call()
        seconds = time.perf_counter() - began
        self.free = start + seconds
        self.busy += seconds
        return result, self.free


class Translator:
    def __init__(self, engine, gpu, span, context):
        self.engine, self.gpu, self.span, self.context = engine, gpu, span, context
        self.pending, self.pairs, self.words = [], [], []
        self.chunks = self.capped = 0
        self.poisoned = False
        self.shown = []

    def offer(self, words, now, final=False):
        """Words newly shown at `now`; send a chunk when the rule says so."""
        self.pending.extend(words)
        while self.pending:
            first = self.pending[0]
            cut = next((i + 1 for i, w in enumerate(self.pending) if PUNCT.search(w['text'])), None)
            if cut is None:
                if not (final or now - first['spoken'] >= self.span):
                    return
                cut = len(self.pending)
            chunk, self.pending = self.pending[:cut], self.pending[cut:]
            self.send(chunk, now)

    def send(self, chunk, ready):
        text = ' '.join(w['text'] for w in chunk)
        pairs = tuple(self.pairs[-self.context:]) if self.context else ()
        translation, shown = self.gpu.run(ready, lambda: self.generate(text, pairs))
        self.chunks += 1
        self.shown.append((text, translation))
        # A cut-off runaway stays on screen but is not given to the next chunks as their context.
        if not self.poisoned:
            self.pairs.append((text, translation))
        self.poisoned = False
        for w in chunk:
            w['translated'] = shown
        self.words.extend(chunk)

    def generate(self, text, pairs):
        """The chunk's continuation, stopped once it is three times longer than the chunk: past that
        the model is retelling the context, not translating the chunk."""
        out, words, chars = '', 3 * len(text.split()) + 3, 3 * len(text) + 20
        for piece, _ in self.engine.translate(text, context=pairs):
            out += piece
            if len(out.split()) > words or len(out) > chars:
                self.capped += 1
                self.poisoned = True
                break
        return out.strip()

    def text(self):
        return ' '.join(t for _, t in self.shown)


def hybrid(audio, folder, translator, piece=.1, tail=1.):
    import sherpa_onnx
    folder = Path(folder) / 'sherpa-onnx'
    recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(folder / 'tokens.txt'), encoder=str(folder / 'encoder.int8.onnx'),
        decoder=str(folder / 'decoder.int8.onnx'), joiner=str(folder / 'joiner.int8.onnx'),
        model_type='zipformer2', num_threads=1, decoding_method='greedy_search')
    stream = recognizer.create_stream()
    samples = np.concatenate([audio, np.zeros(int(tail * RATE), np.float32)])
    step = int(piece * RATE)
    seen, words, current, idle = 0, [], None, 0
    for start in range(0, len(samples), step):
        stream.accept_waveform(RATE, samples[start:start + step])
        began = time.perf_counter()
        decoded = False
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
            decoded = True
        result = recognizer.get_result_all(stream)
        now = (start + step) / RATE + time.perf_counter() - began
        done = []
        fresh = len(result.tokens) > seen
        for token, stamp in zip(result.tokens[seen:], result.timestamps[seen:]):
            starts = token.startswith((' ', '▁'))
            if starts and current is not None:
                done.append(current)
                current = None
            if current is None:
                current = dict(text='', shown=now)
            current['text'] += token.replace('▁', ' ').strip()
            current['spoken'] = min(float(stamp) + .04, len(audio) / RATE)
        seen = len(result.tokens)
        # Nothing new for a while: the last word is finished (the speaker paused).
        # A word goes on in the next token unless it starts with a space, so it is finished when the
        # next word starts, or when two decoded chunks in a row brought nothing (a pause).
        idle = 0 if fresh else idle + decoded
        if current is not None and idle >= 2:
            done.append(current)
            current = None
        for w in done:
            w['shown'] = now  # a word is complete when the next one starts
        words.extend(done)
        translator.offer(done, now)
    if current is not None:
        current['shown'] = len(samples) / RATE
        words.append(current)
        translator.offer([current], current['shown'], final=True)
    translator.offer([], len(samples) / RATE, final=True)
    return words


def agree(audio, engine, gpu, translator, step=.5, trim=8.):
    """LocalAgreement-2 over Whisper passes on the uncommitted audio."""
    words, previous, base, t = [], [], 0, step
    norm = lambda w: w.strip().strip('.,?!…"\'').strip()
    total = len(audio) / RATE

    def decode(until):
        clip = audio[base:int(until * RATE)]
        text = engine.recognize(clip, 0., preliminary=False, mode='phrases', align_words=True)
        found = getattr(engine, 'recognition_words', None) or []
        return [dict(text=w['word'].strip(), start=base / RATE + w['start'], end=base / RATE + w['end'])
                for w in found if w['word'].strip()] if text else []

    while True:
        final = t >= total
        until = min(t, total)
        hypothesis, done = gpu.run(until, lambda: decode(until))
        if final:
            new = hypothesis
        else:
            agreed = 0
            while (agreed < len(previous) and agreed < len(hypothesis)
                   and norm(previous[agreed]['text']) == norm(hypothesis[agreed]['text'])):
                agreed += 1
            new = hypothesis[:agreed]
        committed = [dict(text=w['text'], spoken=w['end'], shown=done) for w in new]
        words.extend(committed)
        translator.offer(committed, done, final=final)
        if final:
            break
        if new:
            base = int(new[-1]['end'] * RATE)  # the next pass starts after the committed words
            previous = hypothesis[len(new):]
        else:
            previous = hypothesis
            if until - base / RATE > trim and hypothesis:
                base = int(hypothesis[0]['start'] * RATE)
        # the next pass starts when the GPU is free again, but not before new audio arrived
        t = max(t + step, gpu.free)
    return words


def whole(engine, text, context):
    """Sentence by sentence, each as one piece, with the previous sentences as context."""
    sentences = [s.strip() for s in re.findall(r'[^.?!…]+[.?!…]*', text) if s.strip()] or [text]
    pairs = []
    for sentence in sentences:
        out = ''.join(p for p, _ in engine.translate(sentence, context=tuple(pairs[-context:]))).strip()
        pairs.append((sentence, out))
    return ' '.join(t for _, t in pairs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('wavs', nargs='+', type=Path)
    parser.add_argument('--mode', choices=['hybrid', 'agree'], required=True)
    parser.add_argument('--span', type=float, default=0., help='seconds of speech before a chunk is sent')
    parser.add_argument('--step', type=float, default=.5, help='agree: seconds between Whisper passes')
    parser.add_argument('--context', type=int, default=4, help='previous chunks given as pairs')
    parser.add_argument('--zipformer', type=Path)
    parser.add_argument('--text-dir', type=Path)
    args = parser.parse_args()
    from hebrew_live.cli import Engine
    engine = Engine(MODELS, Log())
    engine.language, engine.direction, engine.topic = 'he', 'he-ru', 'none'
    engine.warmup()
    for wav in args.wavs:
        audio, rate = soundfile.read(wav, dtype='float32')
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if rate != RATE:
            import soxr
            audio = soxr.resample(audio, rate, RATE).astype(np.float32)
        gpu = Gpu()
        translator = Translator(engine, gpu, args.span, args.context)
        began = time.perf_counter()
        if args.mode == 'hybrid':
            words = hybrid(audio, args.zipformer, translator)
        else:
            words = agree(audio, engine, gpu, translator, args.step)
        hebrew = ' '.join(w['text'] for w in words)
        chunked = translator.text()
        reference_translation = whole(engine, hebrew, 2)
        row = dict(wav=wav.name, mode=args.mode, span=args.span, step=args.step if args.mode == 'agree' else None,
                   seconds=round(len(audio) / RATE, 1), wall=round(time.perf_counter() - began, 1),
                   words=len(words), chunks=translator.chunks, capped=translator.capped,
                   words_per_chunk=round(len(translator.words) / max(1, translator.chunks), 2),
                   hebrew_lag=stats([w['shown'] - w['spoken'] for w in words]),
                   translation_lag=stats([w['translated'] - w['spoken'] for w in translator.words]),
                   gpu_busy=round(gpu.busy / (len(audio) / RATE), 3), erased_words=0,
                   chrf_chunked_vs_whole=round(chrf(chunked, reference_translation), 1))
        reference = wav.with_suffix('.txt')
        if reference.is_file():
            row['wer'] = round(corpus_wer([(reference.read_text(), hebrew)])[0], 4)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if args.text_dir:
            args.text_dir.mkdir(parents=True, exist_ok=True)
            name = f'{wav.stem}.{args.mode}.{args.span}'
            (args.text_dir / f'{name}.json').write_text(json.dumps(dict(
                hebrew=hebrew, chunks=translator.shown, whole=reference_translation,
                words=[{k: w.get(k) for k in ('text', 'spoken', 'shown', 'translated')} for w in translator.words]),
                ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
