#!/usr/bin/env bash
# Everything that turns finished leaderboards into the write-up, in one go.
#
#   ./run_analysis.sh [split]
#
# Safe to run when only some arms exist — each step skips what is missing.
set -u
SPLIT="${1:-test}"
PROJ="F:/pcap_downloads/ev_charger_ai"
PY="C:/Users/user1/anaconda3/envs/ev_ai/python.exe"

export EV_AI_SESSIONS="${EV_AI_SESSIONS:-C:\\ev_iso\\sessions}"
export EV_AI_SPLIT='F:\pcap_downloads\ev_charger_ai\data\split.json'
export EV_AI_RESULTS='F:\pcap_downloads\ev_charger_ai\results'
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1
cd "$PROJ" || exit 1

hdr() { printf '\n\n=============== %s ===============\n' "$1"; }

hdr "A/B/C leaderboard"
"$PY" benchmark/compare_arms.py "$SPLIT" || true

hdr "alert attribution — which rule spoke first"
"$PY" benchmark/attribute_alerts.py "$SPLIT" || true

hdr "ISO label audit — would the standard label these sessions the same way?"
# needs the ISO arm's 60-column matrices
EV_AI_ISO=1 EV_AI_DATA='C:\ev_iso\data' "$PY" benchmark/iso_label_audit.py both || true

hdr "per-source-group generalisation, per arm"
for arm in baseline iso_rules iso; do
  if [ -f "$PROJ/results/$arm/records_${SPLIT}.json" ]; then
    echo "--- arm: $arm ---"
    EV_AI_RESULTS="F:\\pcap_downloads\\ev_charger_ai\\results\\$arm" \
      "$PY" benchmark/analyze.py "$SPLIT" || true
  fi
done

hdr "collected report data"
"$PY" benchmark/collect_report_data.py "$SPLIT" || true
