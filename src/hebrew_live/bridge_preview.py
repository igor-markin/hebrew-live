"""Opt-in CPU translation preview for local Hebrew/English/Russian trials.

This engine keeps the current fast Hebrew recognizer and replaces only MT. It
does not load MLX, Torch, or the production MiLMMT model. Model directories
must be supplied explicitly; this is not a public model-selection option.
"""
from __future__ import annotations

from pathlib import Path
import re
import time

from .cli import Engine


class _NoMetal:
    def get_peak_memory(self):
        return 0


def validate_bridge_models(he_en: Path, en_ru: Path) -> tuple[Path, Path]:
    paths = tuple(Path(value).expanduser().resolve() for value in (he_en, en_ru))
    for path in paths:
        missing = [name for name in ("model.bin", "source.spm", "target.spm")
                   if not (path / name).is_file()]
        if missing:
            raise ValueError(f"CTranslate2 preview model in {path} is missing: {', '.join(missing)}")
    return paths


class BridgePreviewEngine(Engine):
    def __init__(self, folder, log, language="he", backend="fast", asr_path=None,
                 translation_path=None, *, bridge_models):
        if backend != "fast" or translation_path is not None or language != "he":
            raise ValueError("Bridge preview requires fast Hebrew ASR and Hebrew source audio")
        try:
            import ctranslate2
        except ModuleNotFoundError as exc:
            raise RuntimeError("Bridge preview requires the optional ctranslate2==4.8.2 package") from exc
        import sentencepiece as spm
        from .fast_asr import FastHebrewOnnx, model_at

        he_en, en_ru = validate_bridge_models(*bridge_models)
        self.log = log
        self.backend = "fast"
        self.translation_size = "bridge-preview"
        self.language = "he"
        self.direction = "he-ru"
        self.topic = "none"
        self.asr_path = str(model_at(folder, asr_path))
        self.asr = FastHebrewOnnx(Path(self.asr_path))
        self.custom_models = True
        self.models_folder = folder
        self.mx = _NoMetal()
        self.encoder_reuse = False
        self.early_reject = False
        self._bridges = []
        started = time.monotonic()
        for path in (he_en, en_ru):
            self._bridges.append((
                spm.SentencePieceProcessor(model_file=str(path / "source.spm")),
                spm.SentencePieceProcessor(model_file=str(path / "target.spm")),
                ctranslate2.Translator(str(path), device="cpu", compute_type="int8",
                                       inter_threads=1, intra_threads=2),
            ))
        self.log.event("translation_loaded", seconds=time.monotonic() - started,
                       backend="bridge-preview")

    def close(self):
        self.asr = None
        self._bridges.clear()

    def switch_models(self, selection):
        raise ValueError("Model switching is unavailable in the bridge preview")

    @staticmethod
    def _sentences(text):
        return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]

    def _translate_one(self, text, bridge):
        source, target, model = bridge
        tokens = source.encode(text, out_type=str) + ["</s>"]
        hypothesis = model.translate_batch(
            [tokens], beam_size=4, max_decoding_length=128,
        )[0].hypotheses[0]
        return target.decode([token for token in hypothesis
                              if token not in ("</s>", "<pad>")]).strip()

    def _translate_sentences(self, text, bridge):
        return " ".join(self._translate_one(part, bridge) for part in self._sentences(text))

    def translate(self, text):
        if self.direction not in ("he-en", "he-ru"):
            raise ValueError("Bridge preview supports Hebrew to English or Russian only")
        english = self._translate_sentences(text, self._bridges[0])
        result = english if self.direction == "he-en" else self._translate_sentences(
            english, self._bridges[1])
        yield result, "stop"
