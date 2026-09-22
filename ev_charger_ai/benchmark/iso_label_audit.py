"""Secondary analysis: would ISO 15118-2 call the same sessions faulty?

The A/B benchmark deliberately keeps ONE ground truth so the two arms are
comparable. This script asks the other half of the question: if the labels
themselves were written from the standard's error criteria instead of from
thresholds chosen by looking at this fleet, which sessions would change side?

It reads the ISO arm's step matrices (which already carry every conformance
ratio per step, computed online by IsoTracker) and reduces them per session,
so the whole fleet is audited in seconds instead of a multi-hour replay.

    python benchmark/iso_label_audit.py [train|test|both]

Requires EV_AI_DATA to point at the ISO arm's data root and EV_AI_ISO=1.
"""
import collections
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.feature_tracker import FeatureState                # noqa: E402
from core.iso_features import IsoState                       # noqa: E402
from core.npy_stream import load_steps, session_spans        # noqa: E402
from core.stream import load_index                           # noqa: E402
from core.paths import DATA_ROOT as DATA                     # noqa: E402

COL = {n: FeatureState.N_BASE_FEATURES + i
       for i, n in enumerate(IsoState.FEATURE_NAMES)}

# Each ISO criterion, and whether the standard makes it a hard error.
# "reached 1.0" always means the standard's own limit was met, because every
# one of these features is stored as elapsed/limit.
CRITERIA = [
    ("V2G2-711 EVSEProcessing Ongoing > 60 s", "iso_ongoing_ratio", 1.0),
    ("V2G2-443 sequence idle > 60 s", "iso_seq_timeout_ratio", 1.0),
    ("V2G2-448 no SessionSetupRes in 20 s", "iso_comm_setup_ratio", 1.0),
    ("V2G2-702 CableCheck > 40 s", "iso_cablecheck_breach", 1.0),
    ("V2G2-706 PreCharge > 7 s", "iso_precharge_breach", 1.0),
    ("Table 109 message timeout", "iso_msg_timeout_ratio", 1.0),
    ("Fig.102 illegal successor", "iso_seq_illegal", 1.0),
    ("Fig.102 dialog reopened", "iso_n_redialog", 1.0),
    ("8.8.3 ResponseCode FAILED", "iso_rc_sev", 1.0),
    ("Table 98 EVSE hard status", "iso_evse_status_sev", 1.0),
    ("8.5 isolation Fault", "iso_isolation_sev", 1.0),
    ("8.5 EVErrorCode set", "iso_ev_err_sev", 1.0),
]
# The subset the fleet-tuned labeller has no equivalent of at all.
NEW_TO_ISO = {c[0] for c in CRITERIA[:8]}


def audit(split):
    st = load_steps(DATA, split)
    X, sid = st["X"], st["sid"]
    if X.shape[1] != FeatureState.N_FEATURES:
        raise SystemExit(
            f"{split}_X.npy has {X.shape[1]} columns, expected "
            f"{FeatureState.N_FEATURES} — run with EV_AI_ISO=1 against the "
            "ISO arm's data root")
    with open(os.path.join(DATA, f"{split}_sessions.json"), encoding="utf-8") as fh:
        sessions = json.load(fh)
    by_sid = {m["sid"]: m for m in sessions}
    sids, los, his = session_spans(sid)

    hits = {name: np.zeros(len(sids), dtype=bool) for name, _, _ in CRITERIA}
    # stream session by session so the memmap is never materialised
    for k, (lo, hi) in enumerate(zip(los, his)):
        block = np.asarray(X[lo:hi])
        for name, col, thr in CRITERIA:
            if block[:, COL[col]].max(initial=0.0) >= thr:
                hits[name][k] = True

    # fault family lives in the session index, not in the step-matrix meta
    family_of = {m["session_key"]: (min(m["faults"], key=lambda f: f[0])[1]
                                    if m["faults"] else "")
                 for m in load_index()}
    faulty = np.array([bool(by_sid[int(s)]["faulty"]) for s in sids])
    fam = [family_of.get(by_sid[int(s)]["session_key"], "") for s in sids]

    iso_any = np.zeros(len(sids), dtype=bool)
    iso_new = np.zeros(len(sids), dtype=bool)
    for name, _, _ in CRITERIA:
        iso_any |= hits[name]
        if name in NEW_TO_ISO:
            iso_new |= hits[name]

    n = len(sids)
    print(f"\n=== {split}: {n} sessions, {int(faulty.sum())} faulty under the "
          f"fleet-tuned ground truth ===")
    print(f"{'ISO criterion':<40}{'sessions':>10}{'of them':>10}"
          f"{'on clean':>10}{'%clean':>9}")
    print("-" * 79)
    for name, _, _ in CRITERIA:
        h = hits[name]
        on_clean = int((h & ~faulty).sum())
        print(f"{name:<40}{int(h.sum()):>10}{int((h & faulty).sum()):>10}"
              f"{on_clean:>10}{100.0 * on_clean / max(int(h.sum()), 1):>8.1f}%")

    print(f"\nany ISO criterion      : {int(iso_any.sum())} sessions "
          f"({int((iso_any & faulty).sum())} already faulty, "
          f"{int((iso_any & ~faulty).sum())} currently labelled clean)")
    print(f"ISO-only criteria      : {int(iso_new.sum())} sessions "
          f"({int((iso_new & faulty).sum())} already faulty, "
          f"{int((iso_new & ~faulty).sum())} currently labelled clean)")
    print(f"faulty with NO ISO hit : {int((faulty & ~iso_any).sum())} "
          "(the standard alone would miss these)")

    miss = collections.Counter(fam[i] for i in range(n)
                               if faulty[i] and not iso_any[i])
    if miss:
        print("  by family:", dict(miss.most_common()))
    return {"split": split, "n": n, "n_faulty": int(faulty.sum()),
            "iso_any": int(iso_any.sum()),
            "iso_any_on_clean": int((iso_any & ~faulty).sum()),
            "iso_new": int(iso_new.sum()),
            "iso_new_on_clean": int((iso_new & ~faulty).sum()),
            "faulty_no_iso_hit": int((faulty & ~iso_any).sum()),
            "per_criterion": {name: {"sessions": int(hits[name].sum()),
                                     "on_faulty": int((hits[name] & faulty).sum()),
                                     "on_clean": int((hits[name] & ~faulty).sum())}
                              for name, _, _ in CRITERIA}}


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    splits = ["train", "test"] if which == "both" else [which]
    out = [audit(s) for s in splits]
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "results", "iso_label_audit.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print(f"\nwrote {p}")
