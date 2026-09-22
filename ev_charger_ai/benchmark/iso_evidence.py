"""Does the standard's timing model actually describe this fleet?

Before trusting any ISO threshold, measure what the hardware really does
against it. For each normative limit in Table 109 / Table 111 this reports the
observed distribution and the fraction of sessions that would breach it, split
by ground-truth class — so a limit that fires equally on healthy and broken
sessions is exposed as useless rather than shipped.

    python benchmark/iso_evidence.py [n_per_class]

Reads sessions directly (not the step matrices), so it runs before the ISO arm
is built. Point EV_AI_SESSIONS at the fastest copy available.
"""
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import iso15118 as iso                          # noqa: E402
from core.stream import load_index, load_session_events   # noqa: E402

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PROJ, "results", "iso_evidence.json")


def q(v, p):
    if not v:
        return None
    v = sorted(v)
    return v[min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))]


def main(n_per_class=400, seed=23):
    idx = load_index()
    random.seed(seed)
    clean = [m for m in idx if not m["faults"]]
    faulty = [m for m in idx if m["faults"]]
    sample = (random.sample(clean, min(n_per_class, len(clean)))
              + random.sample(faulty, min(n_per_class, len(faulty))))

    lat = collections.defaultdict(lambda: collections.defaultdict(list))
    seqgap = collections.defaultdict(list)
    ongoing = collections.defaultdict(list)
    breach = collections.defaultdict(collections.Counter)
    n = collections.Counter()
    fam_n = collections.Counter()
    fam_ongoing = collections.Counter()

    for m in sample:
        cls = "faulty" if m["faults"] else "clean"
        n[cls] += 1
        fam = (min(m["faults"], key=lambda f: f[0])[1] if m["faults"] else "")
        if fam:
            fam_n[fam] += 1
        try:
            events = load_session_events(m["session_key"])
        except OSError:
            continue
        pending, last_res_t, ongoing_t0 = {}, None, None
        hit = set()
        for ev in events:
            if ev.kind != "v2g":
                continue
            t, msg = ev.t, ev.msg
            if msg.endswith("Req"):
                pending[msg] = t
                if last_res_t is not None:
                    g = t - last_res_t
                    seqgap[cls].append(g)
                    if g >= iso.SEQ_TIMEOUT_S:
                        hit.add("SEQ_TIMEOUT_60s")
                    elif g >= iso.SEQ_PERFORMANCE_S:
                        hit.add("SEQ_PERF_40s")
            elif msg.endswith("Res"):
                req = msg[:-3] + "Req"
                t0 = pending.pop(req, None)
                if t0 is not None:
                    dl = t - t0
                    lat[cls][req].append(dl)
                    lim = iso.MSG_TIMEOUT_S.get(req)
                    if lim and dl >= lim:
                        hit.add("MSG_TIMEOUT:" + req)
                    perf = iso.RES_PERFORMANCE_S.get(msg)
                    if perf and dl >= perf:
                        hit.add("MSG_PERF:" + msg)
                last_res_t = t
                if ev.evse_processing == "Ongoing":
                    if ongoing_t0 is None:
                        ongoing_t0 = t
                    else:
                        span = t - ongoing_t0
                        if span >= iso.ONGOING_TIMEOUT_S:
                            hit.add("ONGOING_TIMEOUT_60s")
                        elif span >= iso.ONGOING_PERFORMANCE_S:
                            hit.add("ONGOING_PERF_55s")
                elif ev.evse_processing == "Finished" and ongoing_t0 is not None:
                    ongoing[cls].append(t - ongoing_t0)
                    ongoing_t0 = None
        for h in hit:
            breach[cls][h] += 1
        if fam and ("ONGOING_TIMEOUT_60s" in hit or "ONGOING_PERF_55s" in hit):
            fam_ongoing[fam] += 1

    print(f"sampled clean={n['clean']} faulty={n['faulty']}\n")
    print("=== Req->Res latency vs the ISO 15118-2 Table 109 timeout ===")
    print(f"{'message':<30}{'cls':<8}{'n':>9}{'p50':>9}{'p99':>9}{'max':>9}"
          f"{'ISO':>8}{'%over':>8}")
    for msg, lim in iso.MSG_TIMEOUT_S.items():
        for cls in ("clean", "faulty"):
            v = lat[cls].get(msg)
            if not v:
                continue
            over = 100.0 * sum(1 for x in v if x >= lim) / len(v)
            print(f"{msg:<30}{cls:<8}{len(v):>9}{q(v,.5):>9.3f}{q(v,.99):>9.3f}"
                  f"{max(v):>9.2f}{lim:>8}{over:>8.2f}")

    print("\n=== Res->Req sequence gap ===")
    for cls in ("clean", "faulty"):
        v = seqgap[cls]
        if v:
            print(f"{cls:<8}n={len(v):>9} p50={q(v,.5):.3f} p99={q(v,.99):.3f} "
                  f"max={max(v):.1f}  >=40s {100.0*sum(1 for x in v if x>=40)/len(v):.4f}%"
                  f"  >=60s {100.0*sum(1 for x in v if x>=60)/len(v):.4f}%")

    print("\n=== EVSEProcessing Ongoing -> Finished span ===")
    for cls in ("clean", "faulty"):
        v = ongoing[cls]
        if v:
            print(f"{cls:<8}n={len(v):>7} p50={q(v,.5):.2f} p95={q(v,.95):.2f} "
                  f"max={max(v):.1f}")

    print("\n=== % of SESSIONS breaching each ISO criterion ===")
    keys = sorted(set(breach["clean"]) | set(breach["faulty"]))
    print(f"{'criterion':<42}{'clean%':>9}{'faulty%':>9}{'verdict':>28}")
    rows = {}
    for k in keys:
        c = 100.0 * breach["clean"][k] / max(n["clean"], 1)
        f = 100.0 * breach["faulty"][k] / max(n["faulty"], 1)
        if f > 0 and c == 0:
            v = "separates cleanly"
        elif f > 2 * c:
            v = "weak signal"
        elif c >= f:
            v = "USELESS (fires on healthy)"
        else:
            v = "marginal"
        rows[k] = {"clean_pct": c, "faulty_pct": f, "verdict": v}
        print(f"{k:<42}{c:>9.1f}{f:>9.1f}{v:>28}")

    if fam_ongoing:
        print("\nOngoing-timer breaches by fault family: "
              + ", ".join(f"{k}:{v}/{fam_n[k]}"
                          for k, v in fam_ongoing.most_common()))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({
            "n": dict(n), "criteria": rows,
            "latency": {cls: {msg: {"n": len(v), "p50": q(v, .5),
                                    "p99": q(v, .99), "max": max(v),
                                    "iso_timeout_s": iso.MSG_TIMEOUT_S.get(msg)}
                              for msg, v in d.items()}
                        for cls, d in lat.items()},
            "seq_gap": {cls: {"n": len(v), "p50": q(v, .5), "p99": q(v, .99),
                              "max": max(v)}
                        for cls, v in seqgap.items() if v},
            "ongoing_span": {cls: {"n": len(v), "p50": q(v, .5),
                                   "p95": q(v, .95), "max": max(v)}
                             for cls, v in ongoing.items() if v},
            "ongoing_by_family": {k: {"hit": v, "n": fam_n[k]}
                                  for k, v in fam_ongoing.items()},
        }, fh, indent=1, ensure_ascii=False)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 400)
