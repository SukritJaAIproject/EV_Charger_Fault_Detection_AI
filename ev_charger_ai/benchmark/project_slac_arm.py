"""Compute the SLAC arm's leaderboard from the baseline records, without replaying.

A replay of the 8,820-session fleet holdout costs ~6 h. It is also unnecessary
for the leaderboard itself: the SLAC layer is a pure early return in every
detector that has one, so a detector's first alert in the SLAC arm is exactly

    min(its baseline first alert, the time its SLAC path fires)

and the SLAC path's fire time is a function of the session's HomePlug frames
alone. The replay stays authoritative — this exists to read the answer hours
earlier and, once the replay lands, to check it against an independent
implementation of the same rule.

Why the identity holds, detector by detector:

  TraditionalAI  Layer 0b (models/traditional.py:51) returns the instant
                 slac_alert fires, ahead of every DIN rule below it.
  MultiAgent     CommsAgent bumps 0.95 and CRIT is 0.95, so the coordinator
                 alerts on that same event (models/multi_agent.py:172, :273).
                 bump() caps at the author's own ceiling, so the focus-boost
                 sensitivity cannot move it either way.
  AgenticAI      a reflex (models/agentic_ai.py:144), evaluated before any
                 investigation is opened.
  AIAgent        also accumulates sub-critical SLAC/restart evidence on its
                 board. Its completed empirical replay is therefore used as
                 the exact graded-evidence reference; a new rule mode can only
                 add an earlier hard fire. If that reference is unavailable,
                 candidate sessions are replayed through AIAgent itself.
  RL             has no rule layer at all; unchanged by construction.

    python benchmark/project_slac_arm.py [sessions_dir] [workers]

Set ``EV_AI_SLAC_RULE_MODE=normative`` to project the public-source ISO
15118-3 arm (600 ms unanswered-request budget plus the separate 10 s
post-attenuation request window). The default remains ``empirical`` so the
published 10 s experiment is reproducible.
"""
import collections
import csv
import json
import multiprocessing
import os
import sys

# The projection replays only AIAgent on the small set of sessions that
# contain match requests. Importing FeatureTracker later must therefore attach
# fs.slac even when the caller only supplied the rule-mode variable.
os.environ.setdefault("EV_AI_SLAC", "1")
os.environ.setdefault("EV_AI_ISO", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.metrics import score_detectors                              # noqa: E402
from core import iso15118_3 as iso3                              # noqa: E402
from core.slac_features import (ATTEN_RSP, MATCH_CNF, MATCH_REQ,  # noqa: E402
                                MATCH_SESSION_TIMEOUT_S, MATCH_TIMEOUT_S,
                                NORMATIVE_MATCH_TIMEOUT_S, RULE_MODE,
                                STAGE_INDEX, STAGES, VALIDATE_REQ)

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = ["TraditionalAI", "RL", "AIAgent", "AgenticAI", "MultiAgent"]
# every detector that gains a SLAC path; RL deliberately has none
ADOPTS = ("TraditionalAI", "MultiAgent", "AgenticAI", "AIAgent")
LATE_GRACE_S = 10.0


def scan(path, mode=RULE_MODE, W=MATCH_TIMEOUT_S):
    """Replay one session's frames through the same state machine as
    core/slac_features.SlacTracker and return
    (match_fire_t, match_fire_kind, restart3_t, saw_match_request).

    This is deliberately a second, independent implementation rather than an
    import of the tracker: agreeing with the replay then means two different
    pieces of code read the same frames the same way.
    """
    stage = 0
    seen_late = False
    n_restart = 0
    match_req_t = None
    saw_match_req = False
    match_session_t = None
    v2g = False
    fire = fire_kind = restart3 = None
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("t"):
                continue
            t = float(r["t"])
            kind = r["kind"]
            if kind == "v2g":
                v2g = True
            elif kind == "hpav":
                msg = r["msg"]
                if ATTEN_RSP in msg and match_session_t is None:
                    match_session_t = t
                if VALIDATE_REQ in msg:
                    match_session_t = None
                for name in STAGES:
                    if name in msg:
                        idx = STAGE_INDEX[name]
                        if idx > stage:
                            stage = idx
                        if idx > STAGE_INDEX["SLAC_PARM.CNF"]:
                            seen_late = True
                        if name == MATCH_REQ:
                            saw_match_req = True
                            if match_req_t is None:
                                match_req_t = t
                            match_session_t = None
                        elif name == MATCH_CNF:
                            match_req_t = None          # answered
                        elif name == "SLAC_PARM.REQ" and seen_late:
                            n_restart += 1
                            seen_late = False
                        break
            if v2g:
                # the rule is gated on this session having produced no V2G of
                # its own; the neighbouring connector shares the powerline and
                # its match frames land in our capture too
                break
            if fire is None:
                if (mode in (iso3.RULE_MODE_NORMATIVE, iso3.RULE_MODE_BOTH)
                        and match_req_t is not None
                        and t - match_req_t >= NORMATIVE_MATCH_TIMEOUT_S):
                    fire, fire_kind = t, "match_response"
                elif (mode in (iso3.RULE_MODE_NORMATIVE,
                               iso3.RULE_MODE_BOTH)
                      and match_session_t is not None
                      and t - match_session_t >= MATCH_SESSION_TIMEOUT_S):
                    fire, fire_kind = t, "match_session"
                elif (mode in (iso3.RULE_MODE_EMPIRICAL, iso3.RULE_MODE_BOTH)
                      and match_req_t is not None and t - match_req_t >= W):
                    fire, fire_kind = t, "fleet_policy"
            if restart3 is None and n_restart >= 3:
                restart3 = t
            if fire is not None and restart3 is not None:
                break
    return fire, fire_kind, restart3, saw_match_req


def _scan(arg):
    key, path = arg
    return (key,) + scan(path)


def _exact_ai_agent(records_by_key, candidate_keys, sess):
    """Replay AIAgent only where SLAC evidence can change its first alert.

    A simple ``min(baseline alert, hard-rule time)`` is exact for the other
    three rule adopters. AIAgent also fuses graded SLAC/restart evidence on its
    board; the earlier projection missed 16/8,820 empirical first-alert times.
    Replaying a few hundred candidate sessions is cheap and removes that
    approximation without paying for the five-model full-fleet replay.
    """
    from core.feature_tracker import FeatureTracker
    from core.stream import load_session_events
    from models.ai_agent import AIAgent

    agent = AIAgent()
    out = {}
    for i, key in enumerate(sorted(candidate_keys), 1):
        rec = records_by_key[key]
        meta = rec["label"]
        baseline = rec["alerts"].get("AIAgent")
        baseline_t = baseline["t"] if baseline else None
        agent.reset(meta["station"], meta["connector"])
        tracker = FeatureTracker()
        first = None
        for ev in load_session_events(key, sess_dir=sess):
            alerts = agent.observe(ev, tracker.update(ev))
            if alerts:
                a = alerts[0]
                first = {"t": a.t, "confidence": a.confidence,
                         "reason": a.reason, "fault_guess": a.fault_guess}
                break
            if baseline_t is not None and ev.t >= baseline_t:
                first = baseline
                break
        out[key] = first
        if i % 100 == 0:
            print(f"  exact AIAgent replay {i}/{len(candidate_keys)}",
                  flush=True)
    return out


def main(sess=r"C:\ev_fleet\sessions", workers=4, index_name=""):
    base = os.path.join(PROJ, "results", "fleet_baseline", "records_test.json")
    with open(base, encoding="utf-8") as fh:
        records = json.load(fh)
    if index_name:
        index_path = os.path.join(sess, index_name)
        with open(index_path, encoding="utf-8") as fh:
            labels = {m["session_key"]: m for m in json.load(fh)}
        swapped = []
        for rec in records:
            meta = labels.get(rec["session_key"])
            if meta is None:
                continue
            q = dict(rec)
            q["label"] = meta
            swapped.append(q)
        print(f"label index {index_name}: retained {len(swapped)}/{len(records)} "
              "baseline records", flush=True)
        records = swapped
    print(f"baseline records: {len(records)} sessions; mode={RULE_MODE}; "
          f"fleet wait W={MATCH_TIMEOUT_S}s; sessions={sess!r}", flush=True)

    jobs = [(r["session_key"], os.path.join(sess, r["session_key"] + ".csv"))
            for r in records]
    missing = [k for k, p in jobs if not os.path.exists(p)]
    if missing:
        # a silently-empty scan once produced a clean, well-formatted "0 fires"
        # answer that was pure path mangling; never let that look like a result
        raise SystemExit(f"{len(missing)} of {len(jobs)} session CSVs missing "
                         f"under {sess!r}, e.g. {missing[0]}")

    fires, fire_kinds, restarts, match_seen = {}, {}, {}, set()
    with multiprocessing.Pool(workers) as pool:
        for i, (key, f, fk, r3, saw_match) in enumerate(
                pool.imap_unordered(_scan, jobs, 64), 1):
            if f is not None:
                fires[key] = f
                fire_kinds[key] = fk
            if r3 is not None:
                restarts[key] = r3
            if saw_match:
                match_seen.add(key)
            if i % 2000 == 0:
                print(f"  scanned {i}/{len(jobs)}", flush=True)
    print(f"SLAC rule fires on {len(fires)} sessions "
          f"({dict(collections.Counter(fire_kinds.values()))}); "
          f"3x-restart fires on {len(restarts)}")

    records_by_key = {r["session_key"]: r for r in records}
    exact_agent = {}
    exact_agent_method = "disabled"
    if os.environ.get("EV_AI_PROJECT_EXACT_AGENT", "1") != "0":
        # A completed empirical SLAC replay is the cheapest exact reference
        # for AIAgent's graded evidence board. The normative arm changes only
        # the hard-rule fire time, so its exact result is min(reference, new
        # normative fire). This avoids replaying millions of downstream V2G
        # events and was validated against all 8,820 empirical records.
        ref_arm = os.environ.get("EV_AI_AGENT_REFERENCE_ARM", "fleet_slac")
        ref_path = os.path.join(PROJ, "results", ref_arm,
                                "records_test.json") if ref_arm else ""
        if ref_path and os.path.exists(ref_path):
            with open(ref_path, encoding="utf-8") as fh:
                reference = {r["session_key"]: r for r in json.load(fh)}
            missing_reference = sorted(set(records_by_key) - set(reference))
            if missing_reference:
                raise SystemExit(
                    f"exact AIAgent reference {ref_arm!r} is missing "
                    f"{len(missing_reference)} sessions, e.g. "
                    f"{missing_reference[0]}"
                )
            for key in records_by_key:
                ref = reference.get(key, {}).get("alerts", {}).get("AIAgent")
                fire_t = fires.get(key)
                if (fire_t is not None
                        and (ref is None or fire_t < ref["t"])):
                    ref = {"t": fire_t, "confidence": 0.96,
                           "reason": "ISO 15118-3 SLAC hard rule",
                           "fault_guess": "SLAC_FAILURE"}
                exact_agent[key] = ref
            exact_agent_method = f"empirical reference {ref_arm} + hard fire"
            print(f"exact AIAgent projection from {ref_arm} on "
                  f"{len(exact_agent)} sessions", flush=True)
        else:
            candidates = match_seen | set(restarts)
            print(f"exact AIAgent replay on {len(candidates)} SLAC candidates",
                  flush=True)
            exact_agent = _exact_ai_agent(records_by_key, candidates, sess)
            exact_agent_method = "targeted replay"

    projected = []
    changed = collections.Counter()
    for rec in records:
        q = dict(rec)
        q["alerts"] = dict(rec["alerts"])
        key = rec["session_key"]
        for d in ADOPTS:
            if d == "AIAgent" and key in exact_agent:
                cur = q["alerts"].get(d)
                hit = exact_agent[key]
                if hit is None:
                    q["alerts"].pop(d, None)
                else:
                    q["alerts"][d] = hit
                    if cur is None or hit["t"] != cur["t"]:
                        changed[d] += 1
                continue
            ts = [fires.get(key)]
            if d == "AIAgent":
                ts.append(restarts.get(key))
            ts = [t for t in ts if t is not None]
            if not ts:
                continue
            t = min(ts)
            cur = q["alerts"].get(d)
            if cur is None or t < cur["t"]:
                q["alerts"][d] = {
                    "t": t, "confidence": 0.9,
                    "reason": "SLAC: CM_SLAC_MATCH.REQ unanswered, no V2G",
                    "fault_guess": "SLAC_FAILURE"}
                changed[d] += 1
        projected.append(q)

    old = score_detectors(records, NAMES)
    new = score_detectors(projected, NAMES)
    print(f"\nfaulty={old['n_faulty']} clean={old['n_clean']}\n")
    print(f"{'detector':<15}{'score':>16}{'recall':>19}{'FAR':>19}"
          f"{'SLAC recall':>19}{'changed':>9}")
    for n in NAMES:
        o, p = old["detectors"][n], new["detectors"][n]
        so = o["by_family"].get("SLAC_FAILURE", {})
        sp = p["by_family"].get("SLAC_FAILURE", {})
        print(f"{n:<15}"
              f"{o['score']:7.1f}->{p['score']:6.1f}"
              f"{100*o['recall']:10.1f}%->{100*p['recall']:6.1f}%"
              f"{100*o['far']:10.1f}%->{100*p['far']:6.1f}%"
              f"{100*so.get('recall', 0):10.0f}%->{100*sp.get('recall', 0):6.0f}%"
              f"{changed[n]:>9}")

    strip = lambda d: {k: v for k, v in d.items() if k != "by_family"}  # noqa: E731
    suffix = "" if RULE_MODE == iso3.RULE_MODE_EMPIRICAL else f"_{RULE_MODE}"
    if index_name:
        suffix += "_" + os.path.splitext(os.path.basename(index_name))[0]
    out = os.path.join(PROJ, "results", f"slac_projection{suffix}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"rule_mode": RULE_MODE,
                   "fleet_wait_s": MATCH_TIMEOUT_S,
                   "normative_match_response_budget_s":
                       NORMATIVE_MATCH_TIMEOUT_S,
                   "normative_match_session_s": MATCH_SESSION_TIMEOUT_S,
                   "n_match_fires": len(fires),
                   "n_match_request_sessions": len(match_seen),
                   "fire_kinds": dict(collections.Counter(fire_kinds.values())),
                   "n_restart3_fires": len(restarts),
                   "fires": fires, "fire_kind_by_session": fire_kinds,
                   "restart3": restarts,
                   "exact_ai_agent_replayed": len(exact_agent),
                   "exact_ai_agent_method": exact_agent_method,
                   "arms": {
                       "fleet_baseline": {n: strip(old["detectors"][n])
                                          for n in NAMES},
                       "projected_slac": {n: strip(new["detectors"][n])
                                          for n in NAMES}}},
                  fh, indent=1, default=float)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"C:\ev_fleet\sessions",
         int(sys.argv[2]) if len(sys.argv) > 2 else 4,
         sys.argv[3] if len(sys.argv) > 3 else "")
