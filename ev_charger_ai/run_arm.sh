#!/usr/bin/env bash
# Run one experiment arm end-to-end on the 37-station corrected dataset.
#
#   ./run_arm.sh baseline  [stages...]   33 features, no ISO knowledge at all
#   ./run_arm.sh iso_rules [stages...]   baseline's own weights + the ISO rule layer
#   ./run_arm.sh iso       [stages...]   ISO rules AND 27 ISO features, retrained
#
# All three arms share sessions/, index.json and split.json, so the ground truth
# and the train/test holdout are byte-identical and the leaderboards compare.
# iso_rules also shares the baseline's trained weights, which is what makes it a
# clean isolation of the rule layer: nothing else about the system changed.
# Stages default to: dataset train_traditional train_nn train_rl benchmark
set -u

ARM="${1:-baseline}"
shift || true
STAGES="${*:-dataset train_traditional train_nn train_rl benchmark}"

PROJ="F:/pcap_downloads/ev_charger_ai"
PY="C:/Users/user1/anaconda3/envs/ev_ai/python.exe"

export EV_AI_PCAPS='F:\pcap_downloads'
# Sessions are read from an NVMe copy of F:\...\data\sessions, verified
# byte-identical (same 6,443 index entries, no missing files). F: is a USB
# volume that the fleet extraction, the on-access virus scanner and the
# trainers all hit at once; through it the replay collapses to ~0.1 MB/s and a
# single benchmark run projects to 13 hours. Same input, ~10x the throughput.
export EV_AI_SESSIONS="${EV_AI_SESSIONS:-C:\\ev_iso\\sessions}"
export EV_AI_SPLIT='F:\pcap_downloads\ev_charger_ai\data\split.json'
export EV_AI_RESULTS="F:\\pcap_downloads\\ev_charger_ai\\results\\$ARM"
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

case "$ARM" in
  baseline)
    # reuses the step matrices already built from the same feature code
    export EV_AI_DATA='F:\pcap_downloads\ev_charger_ai\data'
    export EV_AI_ARTIFACTS='F:\pcap_downloads\ev_charger_ai\artifacts_baseline'
    export EV_AI_ISO=0
    ;;
  iso_rules)
    # deliberately the baseline's data root AND the baseline's weights: the
    # vector stays 33 wide (EV_AI_ISO_VEC=0) so those weights still load, and
    # the only thing that changed is that the rule layers can see fs.iso.
    export EV_AI_DATA='F:\pcap_downloads\ev_charger_ai\data'
    export EV_AI_ARTIFACTS='F:\pcap_downloads\ev_charger_ai\artifacts_baseline'
    export EV_AI_ISO=1
    export EV_AI_ISO_VEC=0
    ;;
  iso)
    # byte-identical sessions, staged on the NVMe: same input, no contention
    : # sessions already default to the NVMe copy
    export EV_AI_DATA='C:\ev_iso\data'
    export EV_AI_ARTIFACTS='C:\ev_iso\artifacts'
    export EV_AI_ISO=1
    ;;
  *) echo "unknown arm: $ARM" >&2; exit 2 ;;
esac

LOG="$PROJ/logs/${ARM}.log"
mkdir -p "$PROJ/logs"
"$PY" -c "import os,sys
for d in sys.argv[1:]: os.makedirs(d, exist_ok=True)" \
  "$EV_AI_DATA" "$EV_AI_ARTIFACTS" "$EV_AI_RESULTS"

say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

run() {
  local name="$1"; shift
  say "--- START $name : $*"
  ( cd "$PROJ" && "$PY" "$@" ) >>"$LOG" 2>&1
  local rc=$?
  say "--- END   $name rc=$rc"
  [ $rc -eq 0 ] || exit $rc
}

say "=== arm=$ARM stages='$STAGES' DATA=$EV_AI_DATA ART=$EV_AI_ARTIFACTS ==="

for s in $STAGES; do
  case "$s" in
    dataset)           run dataset           train/build_dataset.py --workers "${EV_AI_DS_WORKERS:-8}" ;;
    train_traditional) run train_traditional train/train_traditional.py ;;
    train_nn)          run train_nn          train/train_nn_tools.py ;;
    train_rl)          run train_rl          train/train_rl.py ;;
    benchmark)         run benchmark         benchmark/run_competition.py test 0 "${EV_AI_BENCH_WORKERS:-6}" ;;
    *) say "!! unknown stage $s"; exit 2 ;;
  esac
done
say "=== arm=$ARM done ==="
