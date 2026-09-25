import tempfile
from pathlib import Path
import unittest

import numpy as np

from hebrew_live.fast_asr import FastHebrewOnnx, model_at
from hebrew_live.model_selection import validate


class _Session:
    def __init__(self, labels):
        self.labels = labels

    def run(self, _outputs, _inputs):
        scores = np.eye(4, dtype=np.float32)[self.labels][None, :, :]
        return scores, np.array([len(self.labels)], dtype=np.int64)


class FastAsrTests(unittest.TestCase):
    def test_ctc_collapse_preserves_word_order_and_bounded_times(self):
        model = object.__new__(FastHebrewOnnx)
        model.filters = np.zeros((161, 64), dtype=np.float32)
        model.window = np.hanning(321)[:-1].astype(np.float32)
        model.vocab = ["א", "ב", " "]
        model.blank = 3
        model.session = _Session([0, 0, 3, 1, 1, 2, 3, 0])

        result = model.transcribe(np.zeros(16000, dtype=np.float32))
        segment = result["segments"][0]
        self.assertEqual(segment["text"], "אב א")
        self.assertEqual([word["word"] for word in segment["words"]], [" אב", " א"])
        self.assertEqual([(word["start"], word["end"]) for word in segment["words"]],
                         [(0.0, 0.5), (0.875, 1.0)])

    def test_rejects_audio_longer_than_model_limit(self):
        model = object.__new__(FastHebrewOnnx)
        with self.assertRaisesRegex(ValueError, "20 seconds"):
            model.transcribe(np.zeros(20 * 16000 + 1, dtype=np.float32))

    def test_custom_model_requires_all_three_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("multilingual_ctc_ft.onnx", "mel_filters.npy", "vocab.json"):
                (root / name).touch()
            self.assertEqual(model_at(root / "unused", root), root)
            (root / "vocab.json").unlink()
            with self.assertRaisesRegex(ValueError, "vocab.json"):
                model_at(root / "unused", root)

    def test_model_selection_accepts_installed_fast_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            model = folder / "fast-asr"
            model.mkdir()
            for name in ("multilingual_ctc_ft.onnx", "mel_filters.npy", "vocab.json"):
                (model / name).touch()
            self.assertEqual(validate({"asr": "fast", "translation": "milmmt"})["asr"], "fast")
            (folder / "milmmt-4b-4bit").mkdir()
            self.assertEqual(validate({"asr": "fast", "translation": "milmmt"}, folder)["asr"], "fast")


if __name__ == "__main__":
    unittest.main()
