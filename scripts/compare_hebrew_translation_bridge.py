#!/usr/bin/env python3
"""Compare local Hebrew→English→Russian models on a recorded session.

All model paths must be local. The script never sends session text to a service.
The detailed report contains private transcript text; write it outside the repo.
The CTranslate2 mode requires the optional ctranslate2 Python package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import resource
import statistics
import sys
import time
from pathlib import Path


def session_samples(path: Path) -> list[dict]:
    latest: dict[int, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") == "live_mt" and event.get("source"):
            latest[event["segment"]] = event
    return sorted(latest.values(), key=lambda item: item["elapsed"])


def spread_samples(samples: list[dict], limit: int) -> list[dict]:
    if len(samples) <= limit:
        return samples
    return [samples[round(index * (len(samples) - 1) / (limit - 1))]
            for index in range(limit)]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def measure(values: list[float]) -> dict:
    return {"median_s": round(statistics.median(values), 3),
            "p95_s": round(percentile(values, 0.95), 3),
            "max_s": round(max(values), 3)}


def model_fingerprint(path: Path, weights_name: str) -> dict:
    required = ("config.json", "source.spm", "target.spm", "vocab.json",
                weights_name)
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing model files in {path}: {', '.join(missing)}")
    weights = path / weights_name
    with weights.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {"weights_file": weights_name, "weights_bytes": weights.stat().st_size,
            "weights_sha256": digest}


def load_model(path: Path, *, safetensors: bool, device: str):
    import torch
    from transformers import MarianMTModel, MarianTokenizer

    if not path.is_dir():
        raise FileNotFoundError(f"local model directory missing: {path}")
    tokenizer = MarianTokenizer.from_pretrained(str(path), local_files_only=True)
    model = MarianMTModel.from_pretrained(
        str(path), local_files_only=True, trust_remote_code=False,
        use_safetensors=safetensors, weights_only=True, dtype=torch.float32,
    ).to(device).eval()
    return tokenizer, model


def load_ct2_model(path: Path, *, threads: int):
    import ctranslate2
    import sentencepiece as spm

    source = spm.SentencePieceProcessor(model_file=str(path / "source.spm"))
    target = spm.SentencePieceProcessor(model_file=str(path / "target.spm"))
    model = ctranslate2.Translator(
        str(path), device="cpu", compute_type="int8",
        inter_threads=1, intra_threads=threads,
    )
    return source, target, model


def translate(text: str, tokenizer, model, *, device: str, beams: int) -> tuple[str, float]:
    import torch

    started = time.perf_counter()
    encoded = tokenizer(text, return_tensors="pt", truncation=True,
                        max_length=256).to(device)
    with torch.inference_mode():
        ids = model.generate(**encoded, num_beams=beams, max_new_tokens=128)
    if device == "mps":
        torch.mps.synchronize()
    result = tokenizer.decode(ids[0], skip_special_tokens=True)
    return result, time.perf_counter() - started


def translate_ct2(text: str, source, target, model, *, beams: int) -> tuple[str, float]:
    started = time.perf_counter()
    # The source EOS is required by this Marian conversion. Omitting it makes
    # the decoder repeat indefinitely on short conversational phrases.
    tokens = source.encode(text, out_type=str) + ["</s>"]
    hypothesis = model.translate_batch(
        [tokens], beam_size=beams, max_decoding_length=128,
    )[0].hypotheses[0]
    result = target.decode([token for token in hypothesis
                            if token not in ("</s>", "<pad>")])
    return result, time.perf_counter() - started


def translate_sentences(text: str, translate_one) -> tuple[str, float]:
    parts = [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
    outputs = [translate_one(part) for part in parts]
    return " ".join(value for value, _ in outputs), sum(elapsed for _, elapsed in outputs)


def write_private_report(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics", required=True, type=Path)
    parser.add_argument("--he-en", type=Path, help="local Hebrew-to-English model directory")
    parser.add_argument("--he-en-backend", choices=("transformers", "ctranslate2"),
                        default="transformers")
    parser.add_argument("--en-ru", type=Path, help="local Helsinki-NLP/opus-mt_tiny_eng-rus directory")
    parser.add_argument("--en-ru-backend", choices=("transformers", "ctranslate2"),
                        default="transformers")
    parser.add_argument("--report", type=Path, help="new private JSON file outside the repo")
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--beams", type=int, default=1)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--split-sentences", action="store_true")
    parser.add_argument("--probe", action="store_true", help="inspect fixture shape without loading models")
    args = parser.parse_args()
    if args.limit < 2 or args.beams < 1 or args.threads < 1:
        parser.error("limit must be >=2; beams and threads must be >=1")
    samples = session_samples(args.diagnostics)
    if not samples:
        parser.error("no live_mt entries with Hebrew source text")
    chosen = spread_samples(samples, args.limit)
    if args.probe:
        print(json.dumps({"segments_available": len(samples),
                          "segments_selected": len(chosen),
                          "source_characters": [len(row["source"]) for row in chosen]}))
        return
    if not args.he_en or not args.en_ru or not args.report:
        parser.error("--he-en, --en-ru, and --report are required for a full run")
    if args.report.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("private report must be outside the source repository")
    fingerprints = {
        "he_en": model_fingerprint(
            args.he_en, "pytorch_model.bin" if args.he_en_backend == "transformers"
            else "model.bin"),
        "en_ru": model_fingerprint(args.en_ru, "model.bin" if args.en_ru_backend == "ctranslate2"
                                   else "model.safetensors"),
    }

    if "ctranslate2" in (args.he_en_backend, args.en_ru_backend) and args.device != "cpu":
        parser.error("ctranslate2 test currently supports CPU only")
    if "transformers" in (args.he_en_backend, args.en_ru_backend):
        import torch
        torch.set_num_threads(args.threads)
        if args.device == "mps" and not torch.backends.mps.is_available():
            parser.error("MPS is unavailable")
    load_started = time.perf_counter()
    if args.he_en_backend == "ctranslate2":
        he_en_source, he_en_target, he_en_model = load_ct2_model(
            args.he_en, threads=args.threads)

        def he_en_translate(source_text: str) -> tuple[str, float]:
            return translate_ct2(source_text, he_en_source, he_en_target,
                                 he_en_model, beams=args.beams)
    else:
        he_en_tokenizer, he_en_model = load_model(args.he_en, safetensors=False,
                                                  device=args.device)

        def he_en_translate(source_text: str) -> tuple[str, float]:
            return translate(source_text, he_en_tokenizer, he_en_model,
                             device=args.device, beams=args.beams)
    if args.en_ru_backend == "ctranslate2":
        en_ru_source, en_ru_target, en_ru_model = load_ct2_model(args.en_ru,
                                                                  threads=args.threads)

        def en_ru_translate(source_text: str) -> tuple[str, float]:
            return translate_ct2(source_text, en_ru_source, en_ru_target,
                                 en_ru_model, beams=args.beams)
    else:
        en_ru_tokenizer, en_ru_model = load_model(args.en_ru, safetensors=True,
                                                  device=args.device)

        def en_ru_translate(source_text: str) -> tuple[str, float]:
            return translate(source_text, en_ru_tokenizer, en_ru_model,
                             device=args.device, beams=args.beams)
    load_s = time.perf_counter() - load_started
    if args.split_sentences:
        he_en_one = he_en_translate
        he_en_translate = lambda source_text: translate_sentences(source_text, he_en_one)

    if args.split_sentences:
        en_ru_one = en_ru_translate
        en_ru_translate = lambda source_text: translate_sentences(source_text, en_ru_one)
    he_en_translate(chosen[0]["source"])
    rows = []
    for item in chosen:
        english, he_en_s = he_en_translate(item["source"])
        russian, en_ru_s = en_ru_translate(english)
        rows.append({"segment": item["segment"], "source_he": item["source"],
                     "baseline_ru_not_ground_truth": item.get("translation", ""),
                     "english": english, "russian": russian,
                     "english_s": round(he_en_s, 3),
                     "russian_extra_s": round(en_ru_s, 3),
                     "russian_total_s": round(he_en_s + en_ru_s, 3)})
    result = {
        "provenance": {"diagnostics": str(args.diagnostics),
                       "he_en_dir": str(args.he_en), "en_ru_dir": str(args.en_ru),
                       "models": fingerprints},
        "settings": {"device": args.device, "he_en_backend": args.he_en_backend,
                     "en_ru_backend": args.en_ru_backend,
                     "he_en_compute_type": ("int8" if args.he_en_backend == "ctranslate2"
                                            else "float32"),
                     "en_ru_dtype": ("int8" if args.en_ru_backend == "ctranslate2"
                                     else "float32"), "beams": args.beams,
                     "threads": args.threads,
                     "split_sentences": args.split_sentences,
                     "samples": len(rows)},
        "load_s": round(load_s, 3),
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "english_first": measure([row["english_s"] for row in rows]),
        "russian_total": measure([row["russian_total_s"] for row in rows]),
        "rows": rows,
    }
    write_private_report(args.report, result)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"},
                     ensure_ascii=False, indent=2))
    print(f"Private translation report: {args.report}", file=sys.stderr)


if __name__ == "__main__":
    main()
