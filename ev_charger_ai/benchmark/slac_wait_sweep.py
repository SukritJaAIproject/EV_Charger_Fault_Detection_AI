"""How much does the SLAC rule's one free parameter actually matter?

W (core/slac_features.MATCH_TIMEOUT_S, env EV_AI_SLAC_WAIT) is how long an
unanswered CM_SLAC_MATCH.REQ must stand before the rule calls the session
failed. It was picked at 10 s from a cost curve measured on the held-out fleet
split — which is test-set selection, and has to be reported as such.

This sweeps W across two orders of magnitude and projects the full leaderboard
at each value. TraditionalAI, AgenticAI, and MultiAgent are exact min paths at
every point. AIAgent also has a graded evidence board, so points at or below the
shipped 10 s operating point use the completed empirical replay as an exact
reference and add only an earlier hard fire. Points above 10 s are retained as
an explicitly marked approximation; they are not used to select or justify the
normative 600 ms point.

One pass over the sessions serves every W: the fire time for a given W is the
first event where the pending-match age crosses it, so the ages are collected
once and thresholded afterwards.

    python benchmark/slac_wait_sweep.py [sessions_dir] [workers]
"""
import bisect
import collections
import csv
import json
import multiprocessing
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.metrics import score_detectors                              # noqa: E402
from core.slac_features import (MATCH_CNF, MATCH_REQ, STAGE_INDEX,     # noqa: E402
                                STAGES)

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = ["TraditionalAI", "RL", "AIAgent", "AgenticAI", "MultiAgent"]
ADOPTS = ("TraditionalAI", "MultiAgent", "AgenticAI", "AIAgent")
REFERENCE_WAIT_S = 10.0
WAITS = (0.2, 0.4, 0.6, 0.8, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0,
         15.0, 20.0, 30.0, 45.0, 60.0)


def trace(path):
    """One pass -> (ages, restart3) where ages is the ascending list of
    (pending_age, t) pairs seen while the session had produced no V2G.

    Only the running maximum matters: the first crossing of any W is the first
    event whose age exceeds it, and age grows monotonically between match
    requests, so recording each new high-water age with its time is enough.
    """
    stage = 0
    seen_late = False
    n_restart = 0
    match_req_t = None
    restart3 = None
    ages, peak = [], 0.0
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("t"):
                continue
            t = float(r["t"])
            kind = r["kind"]
            if kind == "v2g":
                break                       # rule is gated on no V2G
            if kind == "hpav":
                msg = r["msg"]
                for name in STAGES:
                    if name in msg:
                        idx = STAGE_INDEX[name]
                        if idx > stage:
                            stage = idx
                        if idx > STAGE_INDEX["SLAC_PARM.CNF"]:
                            seen_late = True
                        if name == MATCH_REQ:
                            if match_req_t is None:
                                match_req_t = t
                        elif name == MATCH_CNF:
                            match_req_t = None
                        elif name == "SLAC_PARM.REQ" and seen_late:
                            n_restart += 1
                            seen_late = False
                        break
            if match_req_t is not None:
                age = t - match_req_t
                if age > peak:
                    peak = age
                    ages.append((age, t))
            if restart3 is None and n_restart >= 3:
                restart3 = t
    return ages, restart3


def _scan(arg):
    key, path = arg
    ages, r3 = trace(path)
    return key, ages, r3


def fire_at(ages, W):
    """First time the pending age reached W (ages is ascending in both)."""
    i = bisect.bisect_left([a for a, _ in ages], W)
    return ages[i][1] if i < len(ages) else None


def main(sess=r"C:\ev_fleet\sessions", workers=3):
    base = os.path.join(PROJ, "results", "fleet_baseline", "records_test.json")
    with open(base, encoding="utf-8") as fh:
        records = json.load(fh)
    # AIAgent fuses sub-critical SLAC evidence with other tools. Reusing its
    # completed W=10 replay makes every W<=10 exact: changing W downward can
    # only add an earlier hard fire, so the answer is min(reference, new fire).
    agent_ref_path = os.path.join(
        PROJ, "results", "fleet_slac", "records_test.json"
    )
    agent_reference = {}
    if os.path.exists(agent_ref_path):
        with open(agent_ref_path, encoding="utf-8") as fh:
            agent_reference = {
                r["session_key"]: r["alerts"].get("AIAgent")
                for r in json.load(fh)
            }
        missing_ref = [r["session_key"] for r in records
                       if r["session_key"] not in agent_reference]
        if missing_ref:
            raise SystemExit(
                f"AIAgent reference is missing {len(missing_ref)} sessions, "
                f"e.g. {missing_ref[0]}"
            )
    jobs = [(r["session_key"], os.path.join(sess, r["session_key"] + ".csv"))
            for r in records]
    missing = [k for k, p in jobs if not os.path.exists(p)]
    if missing:
        raise SystemExit(f"{len(missing)} of {len(jobs)} session CSVs missing "
                         f"under {sess!r}, e.g. {missing[0]}")

    ages, restarts = {}, {}
    with multiprocessing.Pool(workers) as pool:
        for i, (key, a, r3) in enumerate(pool.imap_unordered(_scan, jobs, 64), 1):
            if a:
                ages[key] = a
            if r3 is not None:
                restarts[key] = r3
            if i % 3000 == 0:
                print(f"  scanned {i}/{len(jobs)}", flush=True)
    print(f"sessions with a pending match: {len(ages)}; "
          f"3x-restart: {len(restarts)}\n")

    fam = {r["session_key"]:
           (min(r["label"]["faults"], key=lambda f: f[0])[1]
            if r["label"]["faults"] else "clean") for r in records}
    base_score = score_detectors(records, NAMES)
    rows = []
    for W in WAITS:
        fires = {k: t for k, t in
                 ((k, fire_at(a, W)) for k, a in ages.items()) if t is not None}
        projected = []
        for rec in records:
            q = dict(rec)
            q["alerts"] = dict(rec["alerts"])
            key = rec["session_key"]
            for d in ADOPTS:
                if (d == "AIAgent" and agent_reference
                        and W <= REFERENCE_WAIT_S):
                    hit = agent_reference[key]
                    fire_t = fires.get(key)
                    if fire_t is not None and (hit is None
                                               or fire_t < hit["t"]):
                        hit = {"t": fire_t, "confidence": 0.96,
                               "reason": "SLAC hard rule",
                               "fault_guess": "SLAC_FAILURE"}
                    if hit is None:
                        q["alerts"].pop(d, None)
                    else:
                        q["alerts"][d] = hit
                    continue
                ts = [t for t in (fires.get(key),
                                  restarts.get(key) if d == "AIAgent" else None)
                      if t is not None]
                if not ts:
                    continue
                t = min(ts)
                cur = q["alerts"].get(d)
                if cur is None or t < cur["t"]:
                    q["alerts"][d] = {"t": t, "confidence": 0.9,
                                      "reason": "SLAC match unanswered",
                                      "fault_guess": "SLAC_FAILURE"}
            projected.append(q)
        sc = score_detectors(projected, NAMES)
        n_clean_fire = sum(1 for k in fires if fam[k] == "clean")
        agent_exact = bool(agent_reference and W <= REFERENCE_WAIT_S)
        rows.append((W, sc, len(fires), n_clean_fire, agent_exact))

    print(f"{'W':>5}{'fires':>7}{'clean':>7}"
          + "".join(f"{n[:9]:>11}" for n in NAMES)
          + f"{'mean delta':>12}")
    b = {n: base_score["detectors"][n]["score"] for n in NAMES}
    print(f"{'base':>5}{'-':>7}{'-':>7}"
          + "".join(f"{b[n]:>11.1f}" for n in NAMES) + f"{0.0:>12.2f}")
    best = None
    for W, sc, nf, nc, agent_exact in rows:
        d = {n: sc["detectors"][n]["score"] for n in NAMES}
        mean_delta = sum(d[n] - b[n] for n in NAMES) / len(NAMES)
        print(f"{W:>5g}{nf:>7}{nc:>7}"
              + "".join(f"{d[n]:>11.1f}" for n in NAMES)
              + f"{mean_delta:>12.2f}"
              + ("" if agent_exact else "  AIAgent~"))
        if agent_exact and (best is None or mean_delta > best[1]):
            best = (W, mean_delta)
    chosen = next(r for r in rows if r[0] == 10.0)
    chosen_delta = sum(chosen[1]["detectors"][n]["score"] - b[n]
                       for n in NAMES) / len(NAMES)
    normative = next(r for r in rows if r[0] == 0.6)
    normative_delta = sum(normative[1]["detectors"][n]["score"] - b[n]
                           for n in NAMES) / len(NAMES)
    print(f"\nbest W on this holdout: {best[0]:g}s (mean +{best[1]:.2f}); "
          f"the W=10s actually shipped: mean +{chosen_delta:.2f} "
          f"-> holdout optimum exceeds it by "
          f"{best[1] - chosen_delta:+.2f} score points (not an out-of-sample "
          "gain)")
    print(f"public-source ISO 15118-3 response budget W=0.6s: "
          f"mean {normative_delta:+.2f} vs baseline")
    if any(not r[4] for r in rows):
        print("AIAgent points above 10 s are approximate; all other detector "
              "columns and all AIAgent points through 10 s are exact.")

    out = os.path.join(PROJ, "results", "slac_wait_sweep.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"waits": list(WAITS),
                   "normative_response_budget_s": 0.6,
                   "baseline": b,
                   "ai_agent_reference_wait_s": REFERENCE_WAIT_S,
                   "rows": [{"W": W, "fires": nf, "clean_fires": nc,
                             "ai_agent_exact": agent_exact,
                             "scores": {n: sc["detectors"][n]["score"]
                                        for n in NAMES},
                             "slac_recall": {
                                 n: sc["detectors"][n]["by_family"]
                                 .get("SLAC_FAILURE", {}).get("recall", 0.0)
                                 for n in NAMES},
                             "far": {n: sc["detectors"][n]["far"]
                                     for n in NAMES}}
                            for W, sc, nf, nc, agent_exact in rows]},
                  fh, indent=1,
                  default=float)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"C:\ev_fleet\sessions",
         int(sys.argv[2]) if len(sys.argv) > 2 else 3)
