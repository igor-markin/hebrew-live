#!/bin/zsh
# All runs of the Hy-MT2 comparison, one model process at a time, in the order of REPORT.ru.md.
# Outputs go outside the repository. Before each step it waits until memory pressure is normal,
# >= 40 % is free and no other GPU model job of this project runs (another session's Whisper, e.g.);
# finished facts/glossary outputs are skipped, FLORES and prefix runs resume where they stopped.
#   zsh experiments/hy-mt2/run_all.sh            # from the repository root
cd "${0:A:h}"
PY=../../.venv/bin/python
OUT=${HY_MT2_OUT:-$HOME/Library/Caches/hebrew-live-refs/hy-mt2-runs}
mkdir -p $OUT
MLX_JOBS='whisper_run|fleurs_asr|ivrit_eval_asr|e2e_ab|nightly'   # other sessions' GPU model jobs
memory_ok() {
  [[ $(sysctl -n kern.memorystatus_vm_pressure_level) == 1 ]] || return 1
  (( $(memory_pressure | sed -n 's/.*free percentage: \([0-9]*\)%.*/\1/p') >= 40 ))
}
quiet() { memory_ok && ! pgrep -f "$MLX_JOBS" >/dev/null; }
# quality steps are deterministic, so they may share the Mac with CPU jobs; a step is killed when
# memory pressure leaves level 1 and is retried (FLORES and prefix runs resume) once it is quiet again
run() {
  local tries=0
  while (( tries++ < 5 )); do
    until quiet; do echo "waiting for quiet memory / other model job $(date +%H:%M)"; sleep 60; done
    echo "== $*"
    nice $PY "$@" > >(grep -v '^\[transformers\]') 2>&1 &
    local pid=$!
    while kill -0 $pid 2>/dev/null; do
      if ! memory_ok || pgrep -f "$MLX_JOBS" >/dev/null; then echo "!! stopped $1: memory pressure or another model job $(date +%H:%M)"; kill $pid; fi
      sleep 5
    done
    wait $pid && return 0
    sleep 60
  done
  echo "!! gave up on $1 after 5 tries"; return 1
}
once() { [[ -f $1 ]] && echo "skip $1" || { shift; run "$@"; }; }

# 1. FLORES quality: app model, Hy-MT2 greedy (as the app runs) and the card's settings
run flores_run.py milmmt $OUT/flores-milmmt.json
run flores_run.py hy4 $OUT/flores-hy4.json
run flores_run.py hy8 $OUT/flores-hy8.json
run flores_run.py hy4 $OUT/flores-hy4-rec1.json --mode rec --seed 1
run flores_run.py hy4 $OUT/flores-hy4-rec2.json --mode rec --seed 2
run flores_run.py hy4 $OUT/flores-hy4-rp.json --mode rp
# 2. facts checklist
for m in milmmt hy4 hy8; do once $OUT/facts-$m.json facts.py run $m $OUT/facts-$m.json; done
once $OUT/facts-hy4-rec1.json facts.py run hy4 $OUT/facts-hy4-rec1.json --mode rec --seed 1
# 3. growing tail
for m in milmmt hy4 hy8; do run prefixes.py run $m $OUT/prefix-$m.json; done
# 5. context and glossary
run flores_run.py milmmt $OUT/flores-milmmt-ctx.json --context prefix
for s in prefix turns background; do run flores_run.py hy4 $OUT/flores-hy4-ctx-$s.json --context $s; done
for m in milmmt hy4; do once $OUT/glossary-$m.json glossary.py run $m $OUT/glossary-$m.json; done
# unquantized conversion: the ceiling of the 1.8B model in MLX
run flores_run.py hybf16 $OUT/flores-hybf16.json
once $OUT/facts-hybf16.json facts.py run hybf16 $OUT/facts-hybf16.json
# 4. paired speed (appends; delete speed.jsonl to start over)
once $OUT/speed.jsonl speed.py drive $OUT/speed.jsonl --rounds 4
echo "== all done"
