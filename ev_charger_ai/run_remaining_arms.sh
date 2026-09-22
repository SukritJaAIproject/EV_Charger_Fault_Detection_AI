#!/usr/bin/env bash
# Wait for the arms already in flight, then run the rest, then analyse.
#
# The three benchmarks cannot run at once: each worker costs ~1.3 GB of Windows
# commit and only ~6 GB is free, so they are serialised here rather than left to
# fight over it. Everything scores the identical 472-session sample.
set -u
PROJ="F:/pcap_downloads/ev_charger_ai"
cd "$PROJ" || exit 1
LOG="$PROJ/logs/chain.log"
export EV_AI_CLEAN_SAMPLE=250
export EV_AI_BENCH_WORKERS=4
TAG="test_s250"

say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

wait_for() {   # wait_for <file> <label>
  local f="$1" label="$2"
  if [ -f "$f" ]; then say "$label already present"; return; fi
  say "waiting for $label ..."
  until [ -f "$f" ]; do sleep 30; done
  say "$label ready"
}

# 1) the baseline benchmark is already running
wait_for "$PROJ/results/baseline/leaderboard_${TAG}.json" "baseline leaderboard"

# 2) iso_rules: baseline's own weights, ISO rule layer switched on
say "=== arm iso_rules: benchmark ==="
bash run_arm.sh iso_rules benchmark
say "iso_rules rc=$?"

# early read on the question that matters most
say "--- baseline vs iso_rules ---"
"C:/Users/user1/anaconda3/envs/ev_ai/python.exe" benchmark/compare_arms.py \
  "$TAG" baseline,iso_rules 2>&1 | tee -a "$LOG"

# 3) iso: needs its own trained weights (train_rl writes dqn.pt last)
wait_for "C:/ev_iso/artifacts/dqn.pt" "iso trained weights"

say "=== arm iso: benchmark ==="
bash run_arm.sh iso benchmark
say "iso rc=$?"

say "=== full analysis ==="
bash run_analysis.sh "$TAG" 2>&1 | tee -a "$LOG"
say "=== chain complete ==="
