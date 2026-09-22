"""A/B/C the experiment arms on the identical held-out split.

    python benchmark/compare_arms.py [split] [arm,arm,...]

  baseline    33 features, thresholds found by looking at this fleet's data
  iso_rules   the SAME trained weights, plus a rule layer whose every branch
              cites an ISO 15118-2:2014 requirement id
  iso         iso_rules, and the 27 conformance ratios also fed to the learned
              models, everything retrained on them

Every arm replays the same sessions against the same ground truth and the same
holdout stations, so baseline -> iso_rules isolates what the standard's *rules*
are worth, and iso_rules -> iso isolates what its *features* are worth.
"""
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The results root is normally beside this checkout, but a long replay may be
# run from a frozen copy of the code (C:\ev_fleet\code) while its results stay
# in the project. Deriving the path from __file__ alone sent both analysis steps
# looking in the snapshot on 2026-09-16, where they found no arms at all.
RES = os.environ.get("EV_AI_RESULTS_ROOT") or os.path.join(PROJ, "results")
DEFAULT_ARMS = ("baseline", "iso_rules", "iso")
KEYS = ("score", "recall", "far", "earliness", "median_lead_s", "wins")
PCT = {"recall", "far", "earliness"}


def load(arm, tag):
    p = os.path.join(RES, arm, f"leaderboard_{tag}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def fmt(k, v):
    return f"{100 * v:.1f}%" if k in PCT else f"{v:.1f}"


def dlt(k, a, b):
    d = b - a
    return f"{100 * d:+.1f}pp" if k in PCT else f"{d:+.1f}"


def main(tag="test", arms=DEFAULT_ARMS):
    got = [(a, load(a, tag)) for a in arms]
    missing = [a for a, r in got if r is None]
    if missing:
        print(f"(no leaderboard yet for: {', '.join(missing)} — skipping)")
    got = [(a, r) for a, r in got if r is not None]
    if len(got) < 2:
        raise SystemExit("need at least two arms to compare")

    sizes = {(r["n_faulty"], r["n_clean"]) for _, r in got}
    if len(sizes) != 1:
        raise SystemExit(
            "the arms did not score the same sessions "
            + "; ".join(f"{a}: {r['n_faulty']}f/{r['n_clean']}c" for a, r in got)
            + " — the comparison would be meaningless")
    n_faulty, n_clean = sizes.pop()
    ref = got[0][0]

    print(f"split={tag}  faulty={n_faulty}  clean={n_clean}  "
          f"(deltas are vs '{ref}')\n")
    names = sorted(set.intersection(*[set(r["detectors"]) for _, r in got]),
                   key=lambda n: -got[-1][1]["detectors"][n]["score"])
    w = max(len(n) for n in names) + 2

    for metric in ("score", "recall", "far", "median_lead_s"):
        print(f"--- {metric} ---")
        head = f"{'detector':<{w}}"
        for a, _ in got:
            # ASCII only: this runs under a cp1252 console in the driver chain
            head += f"{a:>12}" + ("" if a == ref else f"{'diff':>10}")
        print(head)
        for n in names:
            row = f"{n:<{w}}"
            base = got[0][1]["detectors"][n][metric]
            for a, r in got:
                v = r["detectors"][n][metric]
                row += f"{fmt(metric, v):>12}"
                if a != ref:
                    row += f"{dlt(metric, base, v):>10}"
            print(row)
        print()

    print("--- per-fault-family recall ---")
    fams = sorted({f for _, r in got for n in names
                   for f in r["detectors"][n]["by_family"]})
    print(f"{'detector':<{w}}" + "".join(f"{f[:17]:>19}" for f in fams))
    for n in names:
        row = f"{n:<{w}}"
        for f in fams:
            cells = []
            nn = 0
            for _, r in got:
                d = r["detectors"][n]["by_family"].get(f)
                cells.append(f"{100 * d['recall']:.0f}" if d else "-")
                nn = d["n"] if d else nn
            row += f"{'/'.join(cells) + f' /{nn}':>19}"
        print(row)

    out = {"split": tag, "n_faulty": n_faulty, "n_clean": n_clean,
           "arms": [a for a, _ in got],
           "detectors": {n: {k: {a: r["detectors"][n][k] for a, r in got}
                             for k in KEYS} for n in names}}
    p = os.path.join(RES, f"ab_{tag}.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=float, ensure_ascii=False)
    print(f"\nwrote {p}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test",
         tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else DEFAULT_ARMS)
