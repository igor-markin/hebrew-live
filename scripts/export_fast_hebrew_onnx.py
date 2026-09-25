#!/usr/bin/env python3
"""Convert the pinned GigaAM-He checkpoint into the desktop CPU ASR asset.

Run in a build environment with the official GigaAM package, PyTorch,
torchaudio, and ONNX installed. None of those are required by the app at run
time. The output hashes are checked against fast_asr_manifest.json so a
different exporter or checkpoint cannot silently enter a packaged app.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "src" / "hebrew_live" / "fast_asr_manifest.json").read_text())


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--vocab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checkpoint = args.checkpoint.expanduser().resolve()
    vocab = args.vocab.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if digest(checkpoint) != MANIFEST["source_checkpoint_sha256"]:
        raise SystemExit("Checkpoint hash does not match the pinned GigaAM-He model")
    if digest(vocab) != MANIFEST["files"]["vocab.json"]["sha256"]:
        raise SystemExit("Vocabulary hash does not match the pinned GigaAM-He model")
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)

    import gigaam
    import numpy as np
    import torch

    model = gigaam.load_model(str(checkpoint), fp16_encoder=False, device="cpu")
    model.to_onnx(dir_path=str(output), dtype=torch.float32)
    filters = model.preprocessor.featurizer[0].mel_scale.fb.detach().cpu().numpy()
    np.save(output / "mel_filters.npy", filters)
    shutil.copyfile(vocab, output / "vocab.json")
    for name, expected in MANIFEST["files"].items():
        target = output / name
        if target.stat().st_size != expected["bytes"] or digest(target) != expected["sha256"]:
            raise SystemExit(f"Export differs from the pinned desktop artifact: {name}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
