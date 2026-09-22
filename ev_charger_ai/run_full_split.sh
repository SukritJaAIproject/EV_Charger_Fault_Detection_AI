#!/usr/bin/env bash
# All three arms over the COMPLETE 1,909-session held-out split.
#
# The earlier `test_s250` results sampled 250 of 1,687 clean sessions to fit
# three arms into an afternoon; every one of the 222 faulty sessions was already
# included, so that run was only ever coarse on FAR. This one removes the
# caveat. Results land under leaderboard_test.json / records_test.json and do
# not touch the *_s250 files, so the two remain separately citable.
#
# Serialised, not parallel: each worker costs ~1.3 GB of Windows commit and only
# a few GB is free, so three concurrent benchmarks would be capped down to one
# worker each and finish no sooner.
set -u
PROJ="F:/pcap_downloads/ev_charger_ai"
PY="C:/Users/user1/anaconda3/envs/ev_ai/python.exe"
cd "$PROJ" || exit 1
LOG="$PROJ/logs/full_split.log"
unset EV_AI_CLEAN_SAMPLE
export EV_AI_BENCH_WORKERS="${EV_AI_BENCH_WORKERS:-4}"

say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

say "=== full held-out split, 3 arms, ${EV_AI_BENCH_WORKERS} workers ==="
for arm in baseline iso_rules iso; do
  if [ -f "$PROJ/results/$arm/leaderboard_test.json" ]; then
    say "skip $arm (leaderboard_test.json already present)"
    continue
  fi
  say "--- arm $arm ---"
  bash run_arm.sh "$arm" benchmark
  say "arm $arm rc=$?"
done

say "--- comparison ---"
PYTHONIOENCODING=utf-8 "$PY" benchmark/compare_arms.py test 2>&1 | tee -a "$LOG"
say "--- attribution ---"
PYTHONIOENCODING=utf-8 "$PY" benchmark/attribute_alerts.py test 2>&1 | tee -a "$LOG"
say "--- collected ---"
PYTHONIOENCODING=utf-8 "$PY" benchmark/collect_report_data.py test 2>&1 | tee -a "$LOG"
say "=== full split complete ==="
