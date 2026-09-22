"""Check the projected SLAC leaderboard against the replay, connector by connector.

TraditionalAI, AgenticAI, and MultiAgent are exact min(baseline alert, SLAC
fire) paths; RL is unchanged. AIAgent is different: it fuses graded SLAC
evidence on its board, and the naive min formula differed on 16 of 8,820
sessions. project_slac_arm.py therefore uses the completed empirical replay as
the exact AIAgent reference, then adds an earlier hard fire for another rule
mode. This checker mirrors that final method and makes the dependency explicit.

Reports, per detector, how many banked sessions match the prediction exactly and
prints every disagreement with both times. Safe to run repeatedly while the
replay is still going.

    python benchmark/check_projection_vs_replay.py [ckpt_dir]
"""
import collections
import glob
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = ["TraditionalAI", "RL", "AIAgent", "AgenticAI", "MultiAgent"]
ADOPTS = ("TraditionalAI", "MultiAgent", "AgenticAI", "AIAgent")


def predicted(baseline_alerts, key, fires, agent_reference):
    """What project_slac_arm.py says each detector's first alert will be."""
    out = {}
    for d in NAMES:
        cur = baseline_alerts.get(d)
        t = cur["t"] if cur else None
        if d == "AIAgent":
            ref = agent_reference.get(key)
            t = ref["t"] if ref else None
            out[d] = t
            continue
        if d in ADOPTS:
            cand = [fires.get(key)]
            for c in cand:
                if c is not None and (t is None or c < t):
                    t = c
        out[d] = t
    return out


def main(ckpt=r"C:\ev_fleet\ckpt\test"):
    with open(os.path.join(PROJ, "results", "slac_projection.json"),
              encoding="utf-8") as fh:
        p = json.load(fh)
    fires = p["fires"]
    with open(os.path.join(PROJ, "results", "fleet_baseline",
                           "records_test.json"), encoding="utf-8") as fh:
        base = {r["session_key"]: r["alerts"] for r in json.load(fh)}
    with open(os.path.join(PROJ, "results", "fleet_slac",
                           "records_test.json"), encoding="utf-8") as fh:
        agent_reference = {
            r["session_key"]: r["alerts"].get("AIAgent")
            for r in json.load(fh)
        }

    shards = sorted(glob.glob(os.path.join(ckpt, "*", "*.json")))
    if not shards:
        raise SystemExit(f"no banked shards under {ckpt!r} yet")

    ok = collections.Counter()
    bad = collections.Counter()
    misses = []
    n_sessions = 0
    for sp in shards:
        try:
            with open(sp, encoding="utf-8") as fh:
                sh = json.load(fh)
        except (OSError, ValueError):
            continue                      # being written right now
        for rec in sh["records"]:
            key = rec["session_key"]
            if key not in base:
                continue
            n_sessions += 1
            want = predicted(base[key], key, fires, agent_reference)
            for d in NAMES:
                got = rec["alerts"].get(d)
                got_t = got["t"] if got else None
                if got_t == want[d]:
                    ok[d] += 1
                else:
                    bad[d] += 1
                    if len(misses) < 25:
                        misses.append((d, key, want[d], got_t,
                                       (got or {}).get("reason", "")[:60]))

    print(f"{len(shards)} banked connectors, {n_sessions} sessions, "
          f"{len(fires)} rule fires known to the projection\n")
    print(f"{'detector':<15}{'exact':>9}{'differs':>9}{'agreement':>12}")
    for d in NAMES:
        tot = ok[d] + bad[d]
        print(f"{d:<15}{ok[d]:>9}{bad[d]:>9}"
              f"{(100.0 * ok[d] / tot if tot else 0):>11.2f}%")
    if misses:
        print("\ndisagreements (predicted -> replayed):")
        for d, key, w, g, why in misses:
            print(f"  {d:<14}{key[:44]:<46} {w} -> {g}  {why}")
    else:
        print("\nno disagreement on any banked session")
    print("AIAgent uses the completed replay as its graded-evidence reference; "
          "the other four columns are independently projected.")
    return 1 if sum(bad.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else r"C:\ev_fleet\ckpt\test"))
