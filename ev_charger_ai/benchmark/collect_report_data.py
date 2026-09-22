"""Gather every artefact of the ISO experiment into one JSON for reporting.

    python benchmark/collect_report_data.py [split]

Pulls together the per-arm leaderboards, the A/B/C deltas, the alert
attribution, the pre-training timing evidence and the ISO label audit, so the
write-up cites files rather than remembered numbers.
"""
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(PROJ, "results")
ARMS = ("baseline", "iso_rules", "iso")


def maybe(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(tag="test"):
    out = {"split": tag, "arms": {}, "present": [], "missing": []}
    for arm in ARMS:
        lb = maybe(os.path.join(RES, arm, f"leaderboard_{tag}.json"))
        if lb is None:
            out["missing"].append(f"{arm}/leaderboard_{tag}.json")
            continue
        out["present"].append(arm)
        out["arms"][arm] = {
            "n_faulty": lb["n_faulty"], "n_clean": lb["n_clean"],
            "wall_seconds": lb.get("wall_seconds"),
            "detectors": {n: {k: v for k, v in d.items() if k != "leads"}
                          for n, d in lb["detectors"].items()},
        }
    for name, path in (("ab", f"ab_{tag}.json"),
                       ("attribution", f"attribution_{tag}.json"),
                       ("iso_evidence", "iso_evidence.json"),
                       ("iso_label_audit", "iso_label_audit.json")):
        v = maybe(os.path.join(RES, path))
        if v is None:
            out["missing"].append(path)
        else:
            out[name] = v

    p = os.path.join(RES, f"report_data_{tag}.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=float, ensure_ascii=False)
    print(f"wrote {p}")
    print("arms present:", ", ".join(out["present"]) or "(none)")
    if out["missing"]:
        print("missing:", ", ".join(out["missing"]))
    for arm, a in out["arms"].items():
        ranked = sorted(a["detectors"].items(), key=lambda kv: -kv[1]["score"])
        print(f"\n{arm}: faulty={a['n_faulty']} clean={a['n_clean']}")
        for n, d in ranked:
            print(f"  {n:<16}score={d['score']:6.1f}  recall={100*d['recall']:5.1f}%"
                  f"  FAR={100*d['far']:5.1f}%  lead(med)={d['median_lead_s']:7.1f}s"
                  f"  wins={d['wins']:5.1f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test")
