"""Score existing alert records against a different ground truth.

Detectors never see labels during replay — an alert time is a property of the
stream alone. So a labelling change can be evaluated exactly, on the arms
already run, by swapping the label into each record and re-scoring. No replay,
no retraining, no sampling.

What this does NOT cover: the learned layers (XGBoost horizon targets, the DQN's
rewards, the autoencoder's clean-session pool) were fitted against the OLD
labels. Their behaviour here is therefore unchanged and slightly mis-fitted.
Rule layers, which is where the ISO effect lives, are unaffected either way.

    python benchmark/rescore_labels.py [split] [index_strict.json] [arm,arm,...] [out.json]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.metrics import score_detectors                   # noqa: E402
from core.paths import SESSIONS                            # noqa: E402

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARMS = ("baseline", "iso_rules", "iso")
NAMES = ["TraditionalAI", "RL", "AIAgent", "AgenticAI", "MultiAgent"]


def load_records(arm, split):
    for tag in (f"{split}_s250", split):
        p = os.path.join(PROJ, "results", arm, f"records_{tag}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return json.load(fh), tag
    return None, None


def main(split="test", index_name="index_strict.json", arms=ARMS,
         out_name="rescored_test.json"):
    p = os.path.join(SESSIONS, index_name)
    if not os.path.exists(p):
        raise SystemExit(f"{p} not found — run pipeline/relabel.py first")
    with open(p, encoding="utf-8") as fh:
        new = {m["session_key"]: m for m in json.load(fh)}
    print(f"corrected labels from {index_name}\n")

    old_res, new_res = {}, {}
    for arm in arms:
        recs, tag = load_records(arm, split)
        if recs is None:
            continue
        swapped, missing = [], 0
        for r in recs:
            m = new.get(r["session_key"])
            if m is None:
                missing += 1
                continue
            q = dict(r)
            q["label"] = m
            swapped.append(q)
        old_res[arm] = score_detectors(recs, NAMES)
        new_res[arm] = score_detectors(swapped, NAMES)
        print(f"{arm:<11} {len(swapped)} sessions re-scored from records_{tag}"
              f".json ({missing} not in the new index); faulty "
              f"{old_res[arm]['n_faulty']} -> {new_res[arm]['n_faulty']}, clean "
              f"{old_res[arm]['n_clean']} -> {new_res[arm]['n_clean']}")

    if not new_res:
        raise SystemExit("no records found")

    ref = arms[0]
    for metric, unit in (("score", ""), ("recall", "%"), ("far", "%"),
                         ("median_lead_s", "s")):
        print(f"\n--- {metric} under the corrected labels ---")
        head = f"{'detector':<16}"
        for a in new_res:
            head += f"{a:>12}" + ("" if a == ref else f"{'vs base':>10}")
        print(head)
        for n in NAMES:
            line = f"{n:<16}"
            base = new_res[ref]["detectors"][n][metric]
            for a in new_res:
                v = new_res[a]["detectors"][n][metric]
                s = (f"{100*v:.1f}%" if unit == "%" else
                     (f"{v:.1f}s" if unit == "s" else f"{v:.1f}"))
                line += f"{s:>12}"
                if a != ref:
                    d = v - base
                    line += (f"{100*d:>+9.1f}p" if unit == "%"
                             else f"{d:>+10.1f}")
            print(line)

    print("\n--- what the relabel did to each arm (old label -> new label) ---")
    print(f"{'detector':<16}" + "".join(f"{a:>22}" for a in new_res))
    for n in NAMES:
        line = f"{n:<16}"
        for a in new_res:
            o = old_res[a]["detectors"][n]
            q = new_res[a]["detectors"][n]
            line += f"{o['score']:>9.1f} ->{q['score']:>7.1f}  "
        print(line)

    out = os.path.join(PROJ, "results", out_name)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"index": index_name,
                   "arms": {a: {"n_faulty": r["n_faulty"],
                                "n_clean": r["n_clean"],
                                "detectors": {k: {kk: vv for kk, vv in d.items()
                                                  if kk != "by_family"}
                                              for k, d in r["detectors"].items()}}
                            for a, r in new_res.items()}}, fh, indent=1,
                  default=float)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test",
         sys.argv[2] if len(sys.argv) > 2 else "index_strict.json",
         tuple(sys.argv[3].split(",")) if len(sys.argv) > 3 else ARMS,
         sys.argv[4] if len(sys.argv) > 4 else "rescored_test.json")
