"""Post-run analysis of a competition leaderboard.

Beyond the headline table this answers the deployment question directly: the
held-out test set is stratified over the data sources, so each source is
scored separately —
  legacy   the 10 stations held out since the 16/37-station runs
  main     other held-out stations of the main fleet download
  v2g2024  held-out PT stations, 2024 round (different operator / hardware era)
  v2g2025  held-out PT stations, 2025 round
If a detector scores similarly across sources it generalises to new sites.
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.metrics import score_detectors  # noqa: E402
from core.paths import RESULTS, SPLIT_FILE, station_group  # noqa: E402

NAMES = ["TraditionalAI", "RL", "AIAgent", "AgenticAI", "MultiAgent"]


def table(title, res, cols=("score", "recall", "far", "median_lead_s",
                           "wins", "tp", "late", "miss", "fp")):
    print(f"\n=== {title}  (faulty {res['n_faulty']} / clean {res['n_clean']})")
    print(f"{'detector':15s}" + "".join(f"{c:>14s}" for c in cols))
    ranked = sorted(res["detectors"].items(),
                    key=lambda kv: -kv[1]["score"])
    for name, s in ranked:
        row = f"{name:15s}"
        for c in cols:
            v = s[c]
            row += f"{v:>14.3f}" if isinstance(v, float) else f"{v:>14d}"
        print(row)


def main(tag="test"):
    with open(os.path.join(RESULTS, f"records_{tag}.json"),
              encoding="utf-8") as fh:
        records = json.load(fh)
    legacy = set()
    if os.path.exists(SPLIT_FILE):
        with open(SPLIT_FILE, encoding="utf-8") as fh:
            legacy = set(json.load(fh).get("legacy_test", []))

    overall = score_detectors(records, NAMES)
    table("OVERALL", overall)

    def source(r):
        st = r["label"]["station"]
        return "legacy" if st in legacy else station_group(st)

    per = {}
    for src in ("legacy", "main", "v2g2024", "v2g2025"):
        sub = [r for r in records if source(r) == src]
        if sub:
            per[src] = score_detectors(sub, NAMES)
            table(f"source: {src}", per[src])

    if len(per) >= 2:
        print("\n=== score by source (generalisation view)")
        srcs = list(per)
        print(f"{'detector':15s}" + "".join(f"{s:>12s}" for s in srcs)
              + f"{'spread':>10s}")
        for n in NAMES:
            vals = [per[s]["detectors"][n]["score"] for s in srcs]
            print(f"{n:15s}" + "".join(f"{v:>12.1f}" for v in vals)
                  + f"{max(vals)-min(vals):>10.1f}")

    fams = sorted({f for s in overall["detectors"].values()
                   for f in s["by_family"]})
    print("\n=== recall by fault family")
    print(f"{'detector':15s}" + "".join(f"{f[:13]:>15s}" for f in fams))
    for n in NAMES:
        row = f"{n:15s}"
        for f in fams:
            v = overall["detectors"][n]["by_family"].get(f)
            row += f"{(str(v['tp']) + '/' + str(v['n'])) if v else '-':>15s}"
        print(row)

    by_station = defaultdict(lambda: [0, 0])
    for r in records:
        st = by_station[r["label"]["station"]]
        st[0] += 1
        if r["label"]["faults"]:
            st[1] += 1
    print("\n=== noisiest held-out stations (ground-truth fault rate)")
    for st, (n, f) in sorted(by_station.items(),
                             key=lambda kv: -kv[1][1] / max(kv[1][0], 1))[:15]:
        print(f"{st[:44]:44s} {f:4d}/{n:4d}  {f/max(n,1)*100:5.1f}%")

    with open(os.path.join(RESULTS, f"analysis_{tag}.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"overall": overall, "by_source": per}, fh, indent=1,
                  default=float, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test")
