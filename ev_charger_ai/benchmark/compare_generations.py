"""Three generations of the same experiment, side by side.

    gen 1   old labels, weights trained on old labels      results/<arm>/
    gen 1r  NEW labels, weights trained on old labels      results/rescored_test.json
    gen 2   NEW labels, weights trained on NEW labels      results/<arm>_v2/

gen1 -> gen1r isolates what the label fix alone did to the scoring (nothing
about the detectors changed). gen1r -> gen2 isolates what retraining on the
corrected truth did to the detectors (nothing about the scoring changed).
All three are scored on the identical 472-session sample.

    python benchmark/compare_generations.py
"""
import json
import os

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(PROJ, "results")
ARMS = ("baseline", "iso_rules", "iso")
NAMES = ["TraditionalAI", "RL", "AIAgent", "AgenticAI", "MultiAgent"]
TAG = "test_s250"


def lb(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    return d.get("detectors", d)


def main():
    g1 = {a: lb(os.path.join(RES, a, f"leaderboard_{TAG}.json")) for a in ARMS}
    with open(os.path.join(RES, "rescored_test.json"), encoding="utf-8") as fh:
        g1r = {a: v["detectors"] for a, v in json.load(fh)["arms"].items()}
    # gen2 must be the v2 records RE-SCORED against the strict index. The v2
    # replay itself wrote leaderboard_test_s250.json against the old
    # index.json (run_competition reads labels from there), which is why the
    # raw v2 leaderboard reports 222 faulty instead of 182 - do not use it.
    g2 = {}
    p = os.path.join(RES, "rescored_v2_test.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            for a, v in json.load(fh)["arms"].items():
                g2[a.replace("_v2", "")] = v["detectors"]
    gens = [("gen1 old labels/old weights", g1),
            ("gen1r new labels/old weights", g1r)]
    if len(g2) == len(ARMS):
        gens.append(("gen2 new labels/new weights", g2))
    else:
        print(f"(gen2 incomplete: {sorted(g2)} present)")

    for metric, pct in (("score", False), ("recall", True), ("far", True)):
        print(f"\n=== {metric} ===")
        print(f"{'detector':<15}{'arm':<11}" + "".join(f"{g[0][:5]:>9}" for g in gens)
              + f"{'rules d':>10}{'feat d':>9}  (deltas from the last generation)")
        for n in NAMES:
            for a in ARMS:
                row = f"{n:<15}{a:<11}"
                vals = []
                for _, g in gens:
                    v = g[a][n][metric]
                    vals.append(v)
                    row += f"{100*v:8.1f}%" if pct else f"{v:9.1f}"
                last = gens[-1][1]
                if a == "baseline":
                    row += f"{'':>10}{'':>9}"
                elif a == "iso_rules":
                    d = last["iso_rules"][n][metric] - last["baseline"][n][metric]
                    row += (f"{100*d:>+9.1f}p" if pct else f"{d:>+10.1f}") + f"{'':>9}"
                else:
                    d = last["iso"][n][metric] - last["iso_rules"][n][metric]
                    row += f"{'':>10}" + (f"{100*d:>+8.1f}p" if pct else f"{d:>+9.1f}")
                print(row)

    if len(gens) == 3:
        print("\n=== what retraining on the corrected truth did (gen1r -> gen2) ===")
        print(f"{'detector':<15}" + "".join(f"{a:>22}" for a in ARMS))
        for n in NAMES:
            row = f"{n:<15}"
            for a in ARMS:
                s0, s1 = g1r[a][n]["score"], g2[a][n]["score"]
                r0, r1 = g1r[a][n]["recall"], g2[a][n]["recall"]
                row += f"{s0:6.1f}->{s1:5.1f} ({100*(r1-r0):+.1f}p rec)"
            print(row)

    out = {g[0]: {a: {n: {k: g[1][a][n][k] for k in ("score", "recall", "far",
                                                      "median_lead_s", "wins")}
                      for n in NAMES} for a in g[1]} for g in gens}
    p = os.path.join(RES, "generations.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(f"\nwrote {p}")


if __name__ == "__main__":
    main()
