"""CPU-only Hebrew draft recognition from a pinned GigaAM-He ONNX export.

The model files are build assets, not Python package dependencies.  Exporting
them uses PyTorch once at build time; live inference needs only NumPy and
ONNX Runtime, leaving Metal available for MiLMMT translation.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import onnxruntime as ort


MODEL_FILES = ("multilingual_ctc_ft.onnx", "mel_filters.npy", "vocab.json")
MAX_AUDIO_SECONDS = 20.0


def bundled_model() -> Path | None:
    """Find the model copied beside this module by the macOS app packager."""
    package = Path(__file__).parent
    for candidate in (package / "bundled_models" / "fast-asr", package / "fast_asr_model"):
        if all((candidate / name).is_file() for name in MODEL_FILES):
            return candidate
    return None


def model_at(folder: Path, custom: Path | None = None) -> Path:
    candidate = Path(custom) if custom is not None else bundled_model() or folder / "fast-asr"
    if not all((candidate / name).is_file() for name in MODEL_FILES):
        raise ValueError(f"Fast Hebrew ASR needs {', '.join(MODEL_FILES)} in {candidate}")
    return candidate


class FastHebrewOnnx:
    """Expose the word shape expected by the existing draft/phrase processors."""

    def __init__(self, directory: Path, *, threads: int = 2):
        root = Path(directory)
        self.filters = np.load(root / "mel_filters.npy", allow_pickle=False)
        self.vocab = json.loads((root / "vocab.json").read_text())
        if self.filters.shape != (161, 64) or not isinstance(self.vocab, list):
            raise ValueError("Invalid Fast Hebrew ASR model metadata")
        self.blank = len(self.vocab)
        self.window = np.hanning(321)[:-1].astype(np.float32)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        ort.disable_telemetry_events()
        self.session = ort.InferenceSession(str(root / MODEL_FILES[0]),
                                            sess_options=options,
                                            providers=["CPUExecutionProvider"])

    def features(self, audio: np.ndarray) -> np.ndarray:
        waveform = np.asarray(audio, dtype=np.float32)
        if len(waveform) < 320:
            waveform = np.pad(waveform, (0, 320 - len(waveform)))
        frames = np.lib.stride_tricks.sliding_window_view(waveform, 320)[::160]
        spectrum = np.fft.rfft(frames * self.window, n=320, axis=-1)
        power = (spectrum.real ** 2 + spectrum.imag ** 2).astype(np.float32)
        mel = power @ self.filters
        return np.log(np.clip(mel, 1e-9, 1e9)).T[None, :, :].astype(np.float32)

    def transcribe(self, audio: np.ndarray) -> dict:
        waveform = np.asarray(audio, dtype=np.float32)
        if len(waveform) > MAX_AUDIO_SECONDS * 16000:
            raise ValueError("Fast Hebrew ASR input exceeds 20 seconds")
        features = self.features(waveform)
        lengths = np.array([features.shape[-1]], dtype=np.int64)
        logits, encoded_lengths = self.session.run(
            None, {"features": features, "feature_lengths": lengths})
        encoded_length = int(encoded_lengths[0])
        if encoded_length <= 0:
            return {"language": "he", "segments": [{"text": "", "words": []}]}
        labels = logits.argmax(axis=-1)[0]
        selected: list[int] = []
        frame_indices: list[int] = []
        previous = -1
        for frame, label in enumerate(labels[:encoded_length]):
            token = int(label)
            if token != self.blank and token != previous:
                selected.append(token)
                frame_indices.append(frame)
            previous = token
        text = "".join(self.vocab[token] for token in selected)
        frame_shift = len(waveform) / 16000 / encoded_length
        words: list[dict] = []
        chars: list[str] = []
        frames: list[int] = []
        for token, frame in zip(selected, frame_indices):
            char = self.vocab[token]
            if char == " ":
                if chars:
                    words.append({"word": " " + "".join(chars),
                                  "start": frames[0] * frame_shift,
                                  "end": (frames[-1] + 1) * frame_shift})
                    chars, frames = [], []
            else:
                chars.append(char)
                frames.append(frame)
        if chars:
            words.append({"word": " " + "".join(chars),
                          "start": frames[0] * frame_shift,
                          "end": (frames[-1] + 1) * frame_shift})
        return {"language": "he", "segments": [{"text": text, "words": words}]}
