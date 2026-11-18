#!/bin/bash
# CPU cost of the zipformer stream: normal priority vs `nice` vs background QoS (E-cores), interleaved rounds.
# The same 3 d1 recordings (15 min of audio), int8, one thread, no tracing. Timings are indicative: the Mac is shared.
# Run from the repository root:  bash experiments/streaming-asr/cpu_ab.sh
set -euo pipefail
R="$HOME/Library/Caches/hebrew-live-refs"
S="${TMPDIR:-/tmp}/zf-cpu-ab"
mkdir -p "$S"
PY=("$R/venv-sherpa/bin/python" -I experiments/streaming-asr/zipformer_run.py d1)
for round in 1 2 3; do
  for mode in normal nice background; do
    out="$S/$mode-$round.json"; rm -f "$out"
    case $mode in
      normal) line=$("${PY[@]}" "$out" --limit 3 | tail -1) ;;
      nice) line=$(nice "${PY[@]}" "$out" --limit 3 | tail -1) ;;
      background) line=$(taskpolicy -b "${PY[@]}" "$out" --limit 3 | tail -1) ;;
    esac
    ms=$(python3 -c "import json,statistics as s;d=json.load(open('$out'));d.pop('_meta');print(round(s.median([x for r in d.values() for x in r['decode_ms']]),1))")
    echo "round $round $mode: decode p50 $ms ms per 1.28 s chunk | $line"
  done
done
rm -rf "$S"
