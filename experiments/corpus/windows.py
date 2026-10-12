"""Real-speech ASR windows replayed from a session archive.

Every `live_asr` event of a session records the audio range the app transcribed and the text
it got. `windows()` turns those into (audio at 16 kHz, recorded text) pairs, so a new ASR
variant can be compared with what the shipped build produced on exactly the same audio.
Nothing here prints or stores speech: callers report counts and rates only.
"""
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr


def windows(session_dir, part=1, statuses=('accepted',), min_seconds=0.5):
    session_dir = Path(session_dir)
    audio_path = next(session_dir.glob(f'{part:03d}-*.audio.wav'))
    diagnostics = next(session_dir.glob(f'{part:03d}-*.diagnostics.jsonl'))
    info = sf.info(audio_path)
    result = []
    with audio_path.open('rb') as stream, sf.SoundFile(stream) as audio:
        for line in diagnostics.open(encoding='utf-8'):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('event') != 'live_asr' or event.get('status') not in statuses:
                continue
            start, end = event['start'], event['end']
            if end - start < min_seconds:
                continue
            audio.seek(int(start * info.samplerate))
            data = audio.read(int((end - start) * info.samplerate), dtype='float32', always_2d=False)
            if data.ndim == 2:
                data = data.mean(axis=1)
            data = soxr.resample(data, info.samplerate, 16000).astype(np.float32)
            result.append(dict(start=start, end=end, final=event.get('final'), audio=data,
                               text=event.get('source', ''), seconds=event.get('seconds'),
                               input_seconds=event.get('input_seconds')))
    return result
