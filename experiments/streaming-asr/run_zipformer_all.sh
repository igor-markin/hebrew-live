#!/bin/bash
# All zipformer runs of the report (CPU only, one process at a time, ~10 min on an M5 Air).
# Run from the repository root:  bash experiments/streaming-asr/run_zipformer_all.sh
set -euo pipefail
R="$HOME/Library/Caches/hebrew-live-refs"
O="$R/streaming-asr-out"
run() { nice "$R/venv-sherpa/bin/python" -I experiments/streaming-asr/zipformer_run.py "$@" | tail -1; }

for s in d1 whatsapp fleurs; do run $s "$O/zf-int8-$s.json" --trace; done          # main runs, partials traced
for s in d1 whatsapp fleurs; do run $s "$O/zf-int8-notrace-$s.json"; done           # int8 without tracing: CPU time
for s in d1 whatsapp fleurs; do run $s "$O/zf-fp32-$s.json" --precision fp32; done  # full precision
for s in d1 whatsapp fleurs; do run $s "$O/zf-int8-ep-$s.json" --endpoint; done    # endpoint detection + reset, as in an app
run synthetic "$O/zf-int8-synthetic.json" --trace                                  # silence and noise
for level in -33 -40 -45 -50; do                                                    # quiet far speaker
  for s in d1 whatsapp; do run $s "$O/zf-int8-$s-L$level.json" --level $level; done
done
for s in d1 whatsapp; do run $s "$O/zf-int8-$s-L-25.json" --level -25; done        # near-speaker level as control
run fleurs "$O/zf-int8-fleurs-t2.json" --threads 2                                  # two threads: per-chunk time
run fleurs "$O/zf-int8-fleurs-tail4.json" --trace --tail 4                           # 4 s of trailing silence: last-word lag
for s in d1 whatsapp; do run $s "$O/zf-int8-$s-L-40-F-60.json" --level -40 --floor -60; done   # quiet + noise floor, SNR ~20 dB
for s in d1 whatsapp; do run $s "$O/zf-int8-$s-L-40-F-55.json" --level -40 --floor -55; done   # SNR ~15 dB
