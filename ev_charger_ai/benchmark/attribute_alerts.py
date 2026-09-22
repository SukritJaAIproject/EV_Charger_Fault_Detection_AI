"""Which rule actually spoke first? Attribution over an arm's alert records.

The leaderboard says an arm got better. This says *why*: it buckets every
first-alert reason string by the mechanism that produced it, so an improvement
can be traced to a specific ISO requirement id rather than to "the model
learned something".

    python benchmark/attribute_alerts.py [split] [arm,arm,...]
"""
import collections
import json
import os
import re
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The results root is normally beside this checkout, but a long replay may be
# run from a frozen copy of the code (C:\ev_fleet\code) while its results stay
# in the project. Deriving the path from __file__ alone sent both analysis steps
# looking in the snapshot on 2026-09-16, where they found no arms at all.
RES = os.environ.get("EV_AI_RESULTS_ROOT") or os.path.join(PROJ, "results")

# ordered: first pattern that matches a reason string wins
BUCKETS = [
    ("ISO Ongoing timer [V2G2-711/713]", r"V2G2-711|EVSEProcessing Ongoing|Ongoing \d"),
    ("ISO sequence timer [V2G2-443]", r"V2G2-443|sequence idle|no request for"),
    ("ISO comm setup [V2G2-448]", r"V2G2-448|SessionSetupRes within|setup \d+s/20s"),
    # Anchor on the requirement id or the ISO "elapsed/limit" formatting only.
    # A bare /precharge \d/ also matches the BASELINE rule's own
    # "precharge 12s" evidence string, which would credit the standard with
    # detections it had nothing to do with.
    ("ISO CableCheck [V2G2-702]", r"V2G2-702|CableCheck \d+s/40s"),
    ("ISO PreCharge [V2G2-706]", r"V2G2-706|PreCharge [\d.]+s/7s"),
    ("ISO re-dialog [8.8.1]", r"dialog reopened"),
    ("ISO sequence legality [Fig.102]", r"Fig\.102|legal successor"),
    ("ISO message timeout [Table 109]", r"Table 109"),
    ("ISO response/status semantics", r"ISO 8\.8\.3|ISO Table 98|ISO 8\.5"),
    ("baseline rule: ResponseCode", r"rule: ResponseCode|resp FAILED|resp \w*FAILED"),
    ("baseline rule: EVSE status", r"rule: EVSE_|EVSE_Malfunction|EVSE_EmergencyShutdown"),
    ("baseline rule: isolation", r"isolation Fault|insulation"),
    ("baseline rule: EV error", r"EVErrorCode|EVError "),
    ("baseline rule: cablecheck 40s", r"CableCheck > 40s|cablecheck \d"),
    ("baseline rule: dialog gap", r"msg gap|dialog gap|dt_v2g"),
    ("baseline rule: PLC/SLAC/TCP", r"SLAC|PLC link|TCP RST|retx"),
    ("baseline rule: electrical", r"V above EV max|V over EV|I collapse|precharge gap|ripple"),
    ("learned: xgboost", r"^xgb|xgb:"),
    ("learned: isolation forest", r"iforest"),
    ("learned: RL policy", r"^policy:|Q\(alert\)"),
    ("learned: autoencoder / forecast", r"AE z=|forecast z=|belief .*AE"),
    ("agent: investigation", r"investigation '"),
    ("agent: goal failure", r"goal '"),
    ("agent: belief fusion", r"^belief "),
    ("multi-agent: consensus", r"consensus \["),
    ("multi-agent: critical", r"critical:"),
]
COMPILED = [(n, re.compile(p, re.I)) for n, p in BUCKETS]


def bucket(reason):
    for name, rx in COMPILED:
        if rx.search(reason or ""):
            return name
    return "other"


def run(arm, tag):
    p = os.path.join(RES, arm, f"records_{tag}.json")
    if not os.path.exists(p):
        print(f"(no records for arm {arm})")
        return None
    with open(p, encoding="utf-8") as fh:
        records = json.load(fh)
    per = collections.defaultdict(lambda: collections.Counter())
    fam_by_bucket = collections.defaultdict(lambda: collections.Counter())
    for rec in records:
        faults = rec["label"]["faults"]
        faulty = bool(faults)
        t_f = min(f[0] for f in faults) if faulty else None
        fam = min(faults, key=lambda f: f[0])[1] if faulty else "clean"
        for det, a in rec["alerts"].items():
            b = bucket(a.get("reason", ""))
            if not faulty:
                per[det][("FALSE ALARM", b)] += 1
            elif a["t"] <= t_f + 10.0:
                per[det][("on-time", b)] += 1
                fam_by_bucket[det][(b, fam)] += 1
            else:
                per[det][("late", b)] += 1
    print(f"\n================ arm: {arm} ({tag}) ================")
    for det in sorted(per):
        c = per[det]
        tot_ok = sum(v for (k, _), v in c.items() if k == "on-time")
        tot_fp = sum(v for (k, _), v in c.items() if k == "FALSE ALARM")
        print(f"\n{det}   on-time={tot_ok}  false-alarms={tot_fp}")
        for kind in ("on-time", "FALSE ALARM", "late"):
            rows = sorted(((v, b) for (k, b), v in c.items() if k == kind),
                          reverse=True)
            if not rows:
                continue
            print(f"  {kind}:")
            for v, b in rows:
                fams = fam_by_bucket[det]
                detail = ""
                if kind == "on-time":
                    ff = [(n, f) for (bb, f), n in fams.items() if bb == b]
                    if ff:
                        detail = "  " + ", ".join(
                            f"{f}:{n}" for n, f in sorted(ff, reverse=True)[:4])
                print(f"    {v:>5}  {b}{detail}")
    return {det: {f"{k}|{b}": v for (k, b), v in c.items()}
            for det, c in per.items()}


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "test"
    arms = (tuple(sys.argv[2].split(","))
            if len(sys.argv) > 2 else ("baseline", "iso_rules", "iso"))
    out = {a: run(a, tag) for a in arms}
    p = os.path.join(RES, f"attribution_{tag}.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in out.items() if v}, fh, indent=1,
                  ensure_ascii=False)
    print(f"\nwrote {p}")
