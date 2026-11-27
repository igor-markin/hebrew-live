#!/usr/bin/env bash
# Fetches pinned build inputs for the Android trial build and checks their SHA-256.
# Nothing here is committed: llama.cpp source, the sherpa-onnx AAR and the recognizer model.
set -euo pipefail
cd "$(dirname "$0")/.."

LLAMA_COMMIT=2a8bf0f593472159d8805e9c2a6efb482634db05
SHERPA_AAR=sherpa-onnx-1.12.21.aar
SHERPA_AAR_SHA=4ce353cda9ab9e4c2e398dfd45aeb43cca1b5f97279051d354ebcdbd043e74ef
ASR_REPO=ivrit-ai/zipformer2-66m-streaming-he
ASR_REV=ee769a2a13b887f91572eec349458bfb0fe79e7a

check() {  # file sha
    echo "$2  $1" | shasum -a 256 -c - >/dev/null || { echo "SHA-256 mismatch: $1" >&2; rm -f "$1"; exit 1; }
}

if [ ! -d third_party/llama.cpp/.git ]; then
    mkdir -p third_party
    git init -q third_party/llama.cpp
    git -C third_party/llama.cpp remote add origin https://github.com/ggml-org/llama.cpp
fi
if [ "$(git -C third_party/llama.cpp rev-parse HEAD 2>/dev/null || true)" != "$LLAMA_COMMIT" ]; then
    git -C third_party/llama.cpp fetch -q --depth 1 origin "$LLAMA_COMMIT"
    git -C third_party/llama.cpp checkout -q FETCH_HEAD
fi

mkdir -p app/libs
if [ ! -f "app/libs/$SHERPA_AAR" ]; then
    curl -fsSLo "app/libs/$SHERPA_AAR" "https://huggingface.co/csukuangfj/sherpa-onnx-libs/resolve/main/android/aar/$SHERPA_AAR"
fi
check "app/libs/$SHERPA_AAR" "$SHERPA_AAR_SHA"

mkdir -p app/src/main/assets/asr
while read -r name sha; do
    f="app/src/main/assets/asr/$name"
    [ -f "$f" ] || curl -fsSLo "$f" "https://huggingface.co/$ASR_REPO/resolve/$ASR_REV/sherpa-onnx/$name"
    check "$f" "$sha"
done <<'LIST'
encoder.int8.onnx 6c6febcb74a09435315a1d872a6539f6e7fc2c333533f14c74edc0e85c49ffcd
decoder.int8.onnx feb03e7c8aa761593a9284a6fa1e91259be3702de75f630062256c1a59c5a906
joiner.int8.onnx 1d2c6d8e6dabc5eb52de52e95718e9bdfbffbfe7ead3808fb5ffd74e83bd9cae
tokens.txt e4ebb5e72a6aeef47437a55fa2308ebbedb7c51c557de7a89bf965c23ea9af4a
LIST
echo "deps ok"
