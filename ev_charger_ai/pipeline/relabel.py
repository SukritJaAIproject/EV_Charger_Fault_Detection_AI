"""Recompute ground truth over already-sessionized data, and diff it.

Labels do not enter the feature matrices, and detectors never see them during
replay — so a labelling change can be evaluated by re-scoring existing alert
records rather than by re-running anything. This produces the new index and
reports exactly what moved.

    python pipeline/relabel.py                 # strict (evidence required)
    EV_AI_STRICT_ABORT=0 python pipeline/relabel.py --out index_legacy.json
    EV_AI_LABEL_PROFILE=iso_reviewed python pipeline/relabel.py \
      --out index_iso_reviewed.json --all-out index_iso_reviewed_all.json \
      --drop-censored

Writes <sessions>/index_strict.json by default, leaving index.json alone so the
published numbers stay reproducible. The immutable index may predate the
current strict code path; use ``benchmark/label_profile_audit.py`` to keep that
lineage visible rather than assuming the two snapshots are identical.
"""
import argparse
import collections
import concurrent.futures as cf
import csv
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from pipeline.ground_truth import (LABEL_PROFILE, STRICT_ABORT,  # noqa: E402
                                   label_session)
from core.paths import SESSIONS                                # noqa: E402

_FLOATS = ("soc", "evse_v", "evse_i", "ev_target_v", "ev_target_i", "ev_max_v",
           "ev_max_i", "evse_max_v", "evse_max_i", "remaining_full_min",
           "remaining_bulk_min")


def rows_of(session_key):
    path = os.path.join(SESSIONS, session_key + ".csv")
    out = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("t"):
                continue
            row["t"] = float(row["t"])
            for k in _FLOATS:
                v = row.get(k)
                row[k] = float(v) if v else None
            out.append(row)
    return out


def relabel_one(meta):
    try:
        rows = rows_of(meta["session_key"])
    except OSError:
        return None
    if not rows:
        return None
    lab = label_session(meta["session_key"], meta["station"],
                        meta["connector"], rows)
    if lab is None:
        return None
    d = dict(meta)
    d["faults"] = [list(f) for f in lab.faults]
    d["graceful_close"] = lab.graceful_close
    d["reached_current_demand"] = lab.reached_current_demand
    d["censored"] = lab.censored
    d["censor_reason"] = lab.censor_reason
    d["quality_flags"] = lab.quality_flags
    d["label_profile"] = lab.label_profile
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="index_strict.json")
    ap.add_argument("--drop-censored", action="store_true",
                    help="exclude unknown/censored sessions from the index")
    ap.add_argument("--all-out", default="",
                    help="optional second index retaining censored sessions")
    a = ap.parse_args()

    src = os.path.join(SESSIONS, "index.json")
    with open(src, encoding="utf-8") as fh:
        old = json.load(fh)
    print(f"LABEL_PROFILE={LABEL_PROFILE} STRICT_ABORT={STRICT_ABORT}  "
          f"relabelling {len(old)} sessions "
          f"from {SESSIONS} with {a.workers} workers", flush=True)

    t0 = time.time()
    new_all = []
    with cf.ProcessPoolExecutor(max_workers=a.workers) as ex:
        for i, d in enumerate(ex.map(relabel_one, old, chunksize=16), 1):
            if d is not None:
                new_all.append(d)
            if i % 1000 == 0:
                print(f"  {i}/{len(old)} ({(time.time()-t0)/60:.1f} min)",
                      flush=True)

    n_censored = sum(bool(m.get("censored")) for m in new_all)
    new = ([m for m in new_all if not m.get("censored")]
           if a.drop_censored else new_all)
    if a.all_out:
        all_dst = os.path.join(SESSIONS, a.all_out)
        with open(all_dst, "w", encoding="utf-8") as fh:
            json.dump(new_all, fh, ensure_ascii=False)
        print(f"wrote {all_dst} ({len(new_all)} sessions including "
              f"{n_censored} censored)")

    dst = os.path.join(SESSIONS, a.out)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(new, fh, ensure_ascii=False)

    def fam(m):
        return min(m["faults"], key=lambda f: f[0])[1] if m["faults"] else "clean"

    o = {m["session_key"]: m for m in old}
    n = {m["session_key"]: m for m in new}
    shared = sorted(set(o) & set(n))
    old_shared = [o[k] for k in shared]
    moved = collections.Counter()
    dt_anchor = []
    for k in shared:
        a_, b_ = fam(o[k]), fam(n[k])
        if a_ != b_:
            moved[(a_, b_)] += 1
        elif a_ != "clean":
            ta = min(f[0] for f in o[k]["faults"])
            tb = min(f[0] for f in n[k]["faults"])
            if abs(ta - tb) > 0.5:
                dt_anchor.append(tb - ta)

    n_unavailable = len(old) - len(new_all)
    print(f"\nwrote {dst}  ({len(new)} sessions, {n_censored} censored"
          f"{' dropped' if a.drop_censored else ' retained'}, "
          f"{(time.time()-t0)/60:.1f} min)")
    if n_unavailable:
        print(f"note: {n_unavailable} index entries had no CSV in this sessions "
              "directory; the comparison below uses only shared/evaluated rows")
    print(f"{'':<22}{'before':>10}{'after':>10}{'diff':>9}")
    fams = sorted({fam(m) for m in old_shared} | {fam(m) for m in new})
    # Compare like with like. A portable/test sessions directory may carry the
    # fleet-wide index but only the held-out CSVs; counting all old metadata
    # against the available subset produced a meaningless 40k-vs-8k table.
    cb = collections.Counter(fam(m) for m in old_shared)
    ca = collections.Counter(fam(m) for m in new)
    for f in fams:
        print(f"{f:<22}{cb[f]:>10}{ca[f]:>10}{ca[f]-cb[f]:>+9}")
    print(f"{'TOTAL FAULTY':<22}{sum(v for k,v in cb.items() if k!='clean'):>10}"
          f"{sum(v for k,v in ca.items() if k!='clean'):>10}"
          f"{sum(v for k,v in ca.items() if k!='clean')-sum(v for k,v in cb.items() if k!='clean'):>+9}")

    if moved:
        print("\nreclassified:")
        for (a_, b_), c in moved.most_common():
            print(f"  {a_:<18} -> {b_:<18}{c:>6}")
    if dt_anchor:
        dt_anchor.sort()
        print(f"\nfault-time re-anchored on {len(dt_anchor)} sessions: "
              f"median {dt_anchor[len(dt_anchor)//2]:+.1f}s, "
              f"range {dt_anchor[0]:+.0f}..{dt_anchor[-1]:+.0f}s")


if __name__ == "__main__":
    main()
