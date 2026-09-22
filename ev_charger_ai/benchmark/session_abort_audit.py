"""Is SESSION_ABORT a real fault, or the absence of evidence?

Every point the standard bought in this experiment landed in this one family, so
the headline rests on its labels being right. They are the weakest ones we have:
`ground_truth.py` raises SESSION_ABORT when a session simply never produced a
SessionStopRes. On this fleet idle means zero packets and nearly every session
ends at a ring-buffer boundary, so "no SessionStop" can equally mean "the capture
stopped", which is not a fault at all.

This splits the family by what positive evidence each session actually carries —
a TCP RST, a re-SLAC, or one of the standard's own timers expiring — and then
asks whether the detectors behave differently on the corroborated half. If the
uncorroborated sessions are label noise, recall on them should collapse.

    python benchmark/session_abort_audit.py [split] [arm[,arm...]]

Needs EV_AI_ISO=1 and EV_AI_DATA pointing at the ISO arm's 60-column matrices.
"""
import collections
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.feature_tracker import FeatureState              # noqa: E402
from core.iso_features import IsoState                     # noqa: E402
from core.npy_stream import load_steps, session_spans      # noqa: E402
from core.stream import load_index                         # noqa: E402
from core.paths import DATA_ROOT as DATA                   # noqa: E402

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COL = {n: FeatureState.N_BASE_FEATURES + i
       for i, n in enumerate(IsoState.FEATURE_NAMES)}

# Positive evidence that the dialog was *broken*, not merely *not captured*.
# Each is something that had to happen on the wire; none can be produced by a
# capture simply ending.
EVIDENCE = [
    ("tcp_rst", "TCP RST on the wire", None),
    ("re_slac", "re-SLAC mid-session (link drop)", None),
    ("iso_msg_timeout", "a request unanswered past its Table 109 timeout",
     ("iso_msg_timeout_ratio_max", 1.0)),
    ("iso_seq_timeout", "60 s with no request [V2G2-443]",
     ("iso_seq_timeout_ratio", 1.0)),
    ("iso_ongoing", "EVSEProcessing stuck Ongoing [V2G2-711]",
     ("iso_ongoing_ratio", 55.0 / 60.0)),
    ("redialog", "the dialog reopened [8.8.1]", ("iso_n_redialog", 1.0)),
]


def main(split="test", arms=("baseline", "iso_rules", "iso")):
    idx = {m["session_key"]: m for m in load_index()}
    st = load_steps(DATA, split)
    X, sid = st["X"], st["sid"]
    if X.shape[1] != FeatureState.N_FEATURES:
        raise SystemExit(f"{split}_X.npy is {X.shape[1]} wide; run with "
                         "EV_AI_ISO=1 against the ISO arm's data root")
    with open(os.path.join(DATA, f"{split}_sessions.json"), encoding="utf-8") as fh:
        metas = json.load(fh)
    by_sid = {m["sid"]: m for m in metas}
    sids, los, his = session_spans(sid)

    # --- per-session ISO peaks, streamed ------------------------------
    peak = {}
    for k, (lo, hi) in enumerate(zip(los, his)):
        key = by_sid[int(sids[k])]["session_key"]
        block = np.asarray(X[lo:hi])
        peak[key] = {n: float(block[:, COL[n]].max(initial=0.0))
                     for n in ("iso_msg_timeout_ratio_max", "iso_seq_timeout_ratio",
                               "iso_ongoing_ratio", "iso_n_redialog")}

    aborts = [m for m in idx.values()
              if m["session_key"] in peak and m["faults"]
              and min(m["faults"], key=lambda f: f[0])[1] == "SESSION_ABORT"]
    print(f"=== {split}: {len(aborts)} sessions labelled SESSION_ABORT ===\n")

    # --- classify ------------------------------------------------------
    tags = {}
    counts = collections.Counter()
    for m in aborts:
        key = m["session_key"]
        detail = " ".join(str(f[2]) for f in m["faults"])
        p = peak[key]
        got = []
        for name, _desc, rule in EVIDENCE:
            if rule is None:
                if name == "tcp_rst" and "RST" in detail:
                    got.append(name)
                elif name == "re_slac" and "re-SLAC" in detail:
                    got.append(name)
            elif p[rule[0]] >= rule[1]:
                got.append(name)
        tags[key] = got
        counts[tuple(got) if got else ("NONE",)] += 1

    print(f"{'evidence':<44}{'sessions':>10}{'share':>9}")
    print("-" * 63)
    per_ev = collections.Counter()
    for key, got in tags.items():
        for g in got:
            per_ev[g] += 1
    for name, desc, _ in EVIDENCE:
        n = per_ev[name]
        print(f"{desc:<44}{n:>10}{100.0*n/max(len(aborts),1):>8.1f}%")
    n_none = sum(1 for g in tags.values() if not g)
    print(f"{'NONE — only the missing SessionStopRes':<44}{n_none:>10}"
          f"{100.0*n_none/max(len(aborts),1):>8.1f}%")

    # --- does detection behave differently? ----------------------------
    print(f"\n{'':<16}{'corroborated':>26}{'uncorroborated':>26}")
    print(f"{'detector':<16}{'n':>6}{'recall':>10}{'medlead':>10}"
          f"{'n':>6}{'recall':>10}{'medlead':>10}")
    print("-" * 68)
    out = {"split": split, "n_aborts": len(aborts), "n_uncorroborated": n_none,
           "evidence_counts": {k: per_ev[k] for k, _, _ in EVIDENCE},
           # named so a downstream re-score can drop exactly these
           "uncorroborated_keys": sorted(k for k, g in tags.items() if not g),
           "corroborated_keys": sorted(k for k, g in tags.items() if g),
           "evidence_by_session": {k: g for k, g in tags.items() if g},
           "detectors": {}}
    for arm in arms:
        for tag in (f"{split}_s250", split):
            p = os.path.join(PROJ, "results", arm, f"records_{tag}.json")
            if os.path.exists(p):
                break
        else:
            continue
        with open(p, encoding="utf-8") as fh:
            recs = {r["session_key"]: r for r in json.load(fh)}
        print(f"[{arm}]  (from records_{tag}.json)")
        # union over all records: a session with no alerts at all contributes
        # no keys, and the first one often is exactly that
        dets = sorted({d for r in recs.values() for d in r["alerts"]})
        for det in dets:
            grp = {True: [], False: []}
            for m in aborts:
                r = recs.get(m["session_key"])
                if r is None:
                    continue
                t_f = min(f[0] for f in m["faults"])
                a = r["alerts"].get(det)
                ok = a is not None and a["t"] <= t_f + 10.0
                lead = max(0.0, t_f - a["t"]) if ok else None
                grp[bool(tags[m["session_key"]])].append((ok, lead))
            row = f"  {det:<14}"
            for corro in (True, False):
                g = grp[corro]
                n = len(g)
                rec = 100.0 * sum(1 for ok, _ in g if ok) / max(n, 1)
                leads = sorted(l for ok, l in g if ok and l is not None)
                med = leads[len(leads) // 2] if leads else 0.0
                row += f"{n:>6}{rec:>9.1f}%{med:>10.1f}"
                out["detectors"].setdefault(f"{arm}/{det}", {})[
                    "corroborated" if corro else "uncorroborated"] = {
                        "n": n, "recall": rec / 100.0, "median_lead_s": med}
            print(row)
        print()

    q = os.path.join(PROJ, "results", f"session_abort_audit_{split}.json")
    with open(q, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print(f"wrote {q}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test",
         tuple(sys.argv[2].split(",")) if len(sys.argv) > 2
         else ("baseline", "iso_rules", "iso"))
