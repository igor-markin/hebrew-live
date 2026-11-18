"""Run ivrit-ai/zipformer2-66m-streaming-he through sherpa-onnx as a live stream and save hypotheses.

    R=~/Library/Caches/hebrew-live-refs
    $R/venv-sherpa/bin/python -I experiments/streaming-asr/zipformer_run.py {d1,whatsapp,fleurs,synthetic} OUT.json \
        [--precision int8|fp32|fp16] [--threads 1] [--level -40] [--endpoint] [--trace] [--limit N]

Audio is pushed in 0.1 s pieces, as a microphone would deliver it, and the recognizer decodes whenever a
1.28 s chunk is ready. After the audio, --tail seconds of zeros (default 1.5) flush the last chunk (as in the model card).
  --endpoint  sherpa-onnx endpoint detection on (default rules: 2.4 s / 1.2 s trailing silence, 20 s cap);
              each endpoint closes a segment and resets the stream, as an app would. Off: one stream per file.
  --level D   scale each recording so its active-speech level is D dBFS (quiet far speaker test).
  --trace     keep every change of the partial text with the audio time when it appeared (for latency and
              rewrite analysis in streaming_metrics.py).
OUT.json maps key -> {text, segments?, seconds, cpu_seconds, audio_seconds, level_db, gain_db, decode_ms[], trace?}.
It holds speech text: keep it outside the repository (common.OUT). Process-wide peak RSS goes to OUT.json['_meta'].
"""
import argparse
import resource
import sys
import time
from pathlib import Path

import numpy as np
import sherpa_onnx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('set', choices=['d1', 'whatsapp', 'fleurs', 'synthetic'])
parser.add_argument('out', type=Path)
parser.add_argument('--precision', choices=['int8', 'fp32', 'fp16'], default='int8')
parser.add_argument('--threads', type=int, default=1)
parser.add_argument('--level', type=float)
parser.add_argument('--floor', type=float, help='add a pink-noise floor at this RMS dBFS after levelling')
parser.add_argument('--endpoint', action='store_true')
parser.add_argument('--trace', action='store_true')
parser.add_argument('--limit', type=int)
parser.add_argument('--tail', type=float, default=1.5, help='seconds of zeros after the audio before input_finished')
parser.add_argument('--piece', type=float, default=0.1, help='seconds of audio pushed at a time')
args = parser.parse_args()

if args.precision == 'int8':
    folder, suffix = common.MODEL / 'sherpa-onnx', '.int8.onnx'
else:
    folder, suffix = common.MODEL / 'onnx', '.onnx' if args.precision == 'fp32' else '.fp16.onnx'
recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=str(folder / 'tokens.txt'), encoder=str(folder / f'encoder{suffix}'),
    decoder=str(folder / f'decoder{suffix}'), joiner=str(folder / f'joiner{suffix}'),
    model_type='zipformer2', num_threads=args.threads, decoding_method='greedy_search',
    enable_endpoint_detection=args.endpoint)

if args.set == 'synthetic':
    items = common.SYNTHETIC[:args.limit]

    def load(key):
        return common.synthetic(key)
else:
    items = common.keys(args.set, args.limit)

    def load(key):
        return common.load(args.set, key)

result = common.json.loads(args.out.read_text()) if args.out.is_file() else {}
piece = int(args.piece * common.RATE)
tail = np.zeros(int(args.tail * common.RATE), np.float32)


def run(audio):
    stream = recognizer.create_stream()
    segments, trace, decode_ms = [], [], []
    last = ''
    fed = 0
    stream_audio = np.concatenate([audio, tail])
    for start in range(0, len(stream_audio), piece):
        chunk = stream_audio[start:start + piece]
        stream.accept_waveform(common.RATE, chunk)
        fed += len(chunk)
        if start + piece >= len(stream_audio):
            stream.input_finished()
        while recognizer.is_ready(stream):
            began = time.perf_counter()
            recognizer.decode_stream(stream)
            decode_ms.append(round((time.perf_counter() - began) * 1000, 2))
        text = recognizer.get_result(stream)
        if args.trace and text != last:
            r = recognizer.get_result_all(stream)
            trace.append(dict(t=round(fed / common.RATE, 2), seg=len(segments), text=text,
                              tokens=list(r.tokens), ts=[round(x, 2) for x in r.timestamps], start=round(r.start_time, 2)))
        last = text
        if args.endpoint and recognizer.is_endpoint(stream):
            if text.strip():
                segments.append(dict(text=text, end=round(fed / common.RATE, 2)))
            recognizer.reset(stream)
            last = ''
    text = recognizer.get_result(stream)
    if text.strip():
        segments.append(dict(text=text, end=round(fed / common.RATE, 2)))
    return segments, trace, decode_ms


first = load(items[0])[:common.RATE * 5]
run(first)  # warm-up, not recorded
for done, key in enumerate(items):
    if key in result:
        continue
    audio = load(key)
    level = common.active_level(audio) if args.set != 'synthetic' else None
    gain = 0.
    if args.level is not None:
        audio, gain = common.set_level(audio, args.level)
    if args.floor is not None:
        audio = common.add_floor(audio, args.floor, seed=done)
    wall, cpu = time.perf_counter(), time.process_time()
    segments, trace, decode_ms = run(audio)
    row = dict(text=' '.join(s['text'].strip() for s in segments), seconds=time.perf_counter() - wall,
               cpu_seconds=time.process_time() - cpu, audio_seconds=len(audio) / common.RATE,
               level_db=level, gain_db=gain, decode_ms=decode_ms,
               speech_end=common.speech_end(audio) if args.set != 'synthetic' else None)
    if args.endpoint:
        row['segments'] = segments
    if args.trace:
        row['trace'] = trace
    result[key] = row
    if done % 25 == 24 or args.set != 'fleurs':
        result['_meta'] = dict(vars(args), out=str(args.out), sherpa_onnx=sherpa_onnx.__version__,
                               peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20)
        common.save(args.out, result)
        print(f'{done + 1}/{len(items)}', flush=True)
result['_meta'] = dict(vars(args), out=str(args.out), sherpa_onnx=sherpa_onnx.__version__,
                       peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20)
common.save(args.out, result)
rows = [r for k, r in result.items() if k != '_meta']
audio_s = sum(r['audio_seconds'] for r in rows)
print(f'{len(rows)} items, {audio_s:.0f} s audio, wall {sum(r["seconds"] for r in rows):.1f} s, '
      f'cpu {sum(r["cpu_seconds"] for r in rows):.1f} s = {sum(r["cpu_seconds"] for r in rows) / audio_s * 100:.1f} % of one core, '
      f'peak RSS {result["_meta"]["peak_rss_mb"]:.0f} MB')
