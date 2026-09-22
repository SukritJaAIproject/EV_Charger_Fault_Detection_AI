"""Does the headline survive dropping the questionable labels?

`session_abort_audit.py` finds that 44 of 78 held-out SESSION_ABORT sessions
carry no positive evidence of a broken dialog — only a missing SessionStopRes,
which on this fleet is also what a capture ending at a ring-buffer boundary
looks like. Their fault time is the last row of the file, so any earlier alert
books an enormous "lead" (median 616-1633 s vs 0-106 s on corroborated ones).

That is the weakest ground in the whole experiment, and it is the exact family
the standard improved. So: re-score every arm with those sessions removed from
the faulty set entirely, and see whether the ISO effect holds. If it does, the
result does not depend on the labels I distrust.

    python benchmark/robustness_recheck.py [split]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.metrics import score_detectors                   # noqa: E402

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


def main(split="test"):
    audit_p = os.path.join(PROJ, "results", f"session_abort_audit_{split}.json")
    if not os.path.exists(audit_p):
        raise SystemExit("run benchmark/session_abort_audit.py first")

    # rebuild the uncorroborated set the same way the audit did, from its
    # own record of which keys had no evidence
    with open(audit_p, encoding="utf-8") as fh:
        audit = json.load(fh)
    drop = set(audit.get("uncorroborated_keys") or [])
    if not drop:
        raise SystemExit(
            "the audit json carries no uncorroborated_keys — re-run "
            "session_abort_audit.py after the fix that records them")

    print(f"dropping {len(drop)} SESSION_ABORT sessions that rest only on a "
          f"missing SessionStopRes\n")
    rows = {}
    for arm in ARMS:
        recs, tag = load_records(arm, split)
        if recs is None:
            print(f"(no records for {arm})")
            continue
        kept = [r for r in recs if r["session_key"] not in drop]
        res = score_detectors(kept, NAMES)
        rows[arm] = res
        print(f"{arm:<11} scored {len(kept)} of {len(recs)} sessions "
              f"({res['n_faulty']} faulty, {res['n_clean']} clean) "
              f"from records_{tag}.json")

    if len(rows) < 2:
        raise SystemExit("need at least two arms")

    ref = ARMS[0]
    for metric in ("score", "recall", "far"):
        print(f"\n--- {metric}, questionable aborts removed ---")
        head = f"{'detector':<16}"
        for a in rows:
            head += f"{a:>12}" + ("" if a == ref else f"{'diff':>9}")
        print(head)
        for n in sorted(NAMES, key=lambda x: -rows[ARMS[-1]]["detectors"][x]["score"]
                        if ARMS[-1] in rows else 0):
            line = f"{n:<16}"
            base = rows[ref]["detectors"][n][metric]
            for a in rows:
                v = rows[a]["detectors"][n][metric]
                s = f"{100*v:.1f}%" if metric in ("recall", "far") else f"{v:.1f}"
                line += f"{s:>12}"
                if a != ref:
                    d = v - base
                    line += (f"{100*d:>+8.1f}p" if metric in ("recall", "far")
                             else f"{d:>+9.1f}")
            print(line)

    out = os.path.join(PROJ, "results", f"robustness_{split}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"dropped": len(drop),
                   "arms": {a: {"n_faulty": r["n_faulty"], "n_clean": r["n_clean"],
                                "detectors": {n: {k: v for k, v in d.items()
                                                  if k != "by_family"}
                                              for n, d in r["detectors"].items()}}
                            for a, r in rows.items()}}, fh, indent=1, default=float)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test")
