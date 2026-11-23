"""Live Hebrew draft from a streaming recognizer on the CPU (hybrid mode, opt-in).

ivrit-ai/zipformer2-66m-streaming-he through sherpa-onnx writes the open group's text as the
audio grows and never rewrites what it has written (experiments/streaming-asr/REPORT.ru.md).
Whisper still recognises the closed group once; only the drafts come from here, so the GPU is
left to the translator while a phrase is open.

    HEBREW_LIVE_HYBRID=1  HEBREW_LIVE_HYBRID_MODEL=/path/to/zipformer2-66m-streaming-he

The folder holds sherpa-onnx/{encoder,decoder,joiner}.int8.onnx and tokens.txt (or those files
directly). When sherpa-onnx or the model is missing, `load` returns None and Whisper keeps
writing the drafts.
"""
import os
import time
from pathlib import Path

import numpy as np

RATE = 16000
FILES = ('encoder.int8.onnx', 'decoder.int8.onnx', 'joiner.int8.onnx', 'tokens.txt')


def model_folder(path):
    path = Path(path)
    for folder in (path / 'sherpa-onnx', path):
        if all((folder / name).is_file() for name in FILES):
            return folder
    return None


class StreamingDraft:
    """One stream per open group, fed only the samples it has not seen yet."""

    def __init__(self, folder, threads=1):
        import sherpa_onnx
        folder = Path(folder)
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(folder / 'tokens.txt'), encoder=str(folder / 'encoder.int8.onnx'),
            decoder=str(folder / 'decoder.int8.onnx'), joiner=str(folder / 'joiner.int8.onnx'),
            model_type='zipformer2', num_threads=threads, decoding_method='greedy_search')
        self.key = None
        self.stream = None
        self.fed = 0
        self.seconds = 0.
        self.heard_until = 0.  # seconds into the group where the last written token was heard

    def text(self, key, audio):
        """Text of `audio` (16 kHz float32, the whole group so far) for group `key`. A new key
        or a shorter group (it was cut) starts a new stream."""
        began = time.perf_counter()
        if key != self.key or len(audio) < self.fed:
            self.stream = self.recognizer.create_stream()
            self.key, self.fed = key, 0
        if len(audio) > self.fed:
            self.stream.accept_waveform(RATE, np.asarray(audio[self.fed:], dtype=np.float32))
            self.fed = len(audio)
            while self.recognizer.is_ready(self.stream):
                self.recognizer.decode_stream(self.stream)
        result = self.recognizer.get_result_all(self.stream)
        self.heard_until = float(result.timestamps[-1]) if result.timestamps else 0.
        self.seconds = time.perf_counter() - began
        return result.text.strip()


def load(log=None):
    """The streaming draft when hybrid mode is on and its model is available, else None."""
    if os.environ.get('HEBREW_LIVE_HYBRID', '0') != '1':
        return None
    path = os.environ.get('HEBREW_LIVE_HYBRID_MODEL', '')
    folder = model_folder(path) if path else None
    try:
        if folder is None:
            raise FileNotFoundError('streaming model files not found')
        draft = StreamingDraft(folder, int(os.environ.get('HEBREW_LIVE_HYBRID_THREADS', '1')))
    except Exception as error:  # an optional prototype must never stop the session
        if log is not None:
            log.event('hybrid_unavailable', error=type(error).__name__, detail=str(error)[:200])
        return None
    if log is not None:
        log.event('hybrid_ready', model=folder.name if folder.name != 'sherpa-onnx' else folder.parent.name)
    return draft
