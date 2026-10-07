"""Reference transcript of a recording with ivrit.ai Large-v3 in the leaderboard configuration.

Plan 4.2: beam 5, temperature fallback, condition_on_previous_text, VAD segmentation, full 30 s
windows, through faster-whisper/CTranslate2 on the CPU (int8 to keep memory near 2 GB; it is an
oracle for relative comparisons, not a product path). Run it with the separate environment that
holds faster-whisper (not the project venv):

    ~/Library/Caches/hebrew-live-refs/venv/bin/python experiments/corpus/make_asr_reference.py \
        AUDIO.wav OUT.json [--model DIR] [--threads 3]

OUT.json contains speech text: keep it in the app data root, never in the repository or a report.
The script prints counts only. Run under `nice`; one model job at a time.
"""
import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
from faster_whisper import WhisperModel

DEFAULT_MODEL = Path.home() / 'Library' / 'Caches' / 'hebrew-live-refs' / 'whisper-large-v3-ct2'

parser = argparse.ArgumentParser()
parser.add_argument('audio', type=Path)
parser.add_argument('out', type=Path)
parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
parser.add_argument('--threads', type=int, default=3)
args = parser.parse_args()

def load_16k(path):
    """Mono float32 at 16 kHz, resampled block by block (PyAV is not used)."""
    with sf.SoundFile(path) as source:
        stream = soxr.ResampleStream(source.samplerate, 16000, 1, dtype='float32')
        blocks = []
        for block in source.blocks(blocksize=source.samplerate * 30, dtype='float32', always_2d=True):
            blocks.append(stream.resample_chunk(block.mean(axis=1)))
        blocks.append(stream.resample_chunk(np.zeros(0, dtype='float32'), last=True))
    return np.concatenate(blocks)


began = time.time()
audio = load_16k(args.audio)
model = WhisperModel(str(args.model), device='cpu', compute_type='int8', cpu_threads=args.threads, num_workers=1)
segments, info = model.transcribe(
    audio, language='he', task='transcribe', beam_size=5,
    temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0], condition_on_previous_text=True,
    compression_ratio_threshold=2.4, log_prob_threshold=-1.0, no_speech_threshold=0.6,
    vad_filter=True, word_timestamps=True)
result = []
for segment in segments:
    result.append(dict(start=segment.start, end=segment.end, text=segment.text,
                       avg_logprob=segment.avg_logprob, no_speech_prob=segment.no_speech_prob,
                       words=[dict(start=w.start, end=w.end, word=w.word, probability=w.probability)
                              for w in segment.words or []]))
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(dict(
    model=args.model.name, compute_type='int8', beam_size=5, duration=info.duration,
    language=info.language, segments=result), ensure_ascii=False))
os.chmod(args.out, 0o600)
print(f'{len(result)} segments, {sum(len(s["words"]) for s in result)} words, audio {info.duration:.0f} s, '
      f'took {time.time() - began:.0f} s')
