#!/bin/bash
# Paired Whisper Turbo runs (app settings) on the same inputs. GPU/MLX, ~2.2 GB; run alone, after the zipformer runs.
# Run from the repository root:  bash experiments/streaming-asr/run_whisper_all.sh
set -euo pipefail
O="$HOME/Library/Caches/hebrew-live-refs/streaming-asr-out"
run() { nice .venv/bin/python experiments/streaming-asr/whisper_run.py "$@" | tail -1; }

for s in d1 whatsapp fleurs; do run $s "$O/wh-$s.json"; done
run synthetic "$O/wh-synthetic.json"
for s in d1 whatsapp; do run $s "$O/wh-$s-L-40.json" --level -40; done
for s in d1 whatsapp; do run $s "$O/wh-$s-L-40-F-55.json" --level -40 --floor -55; done
