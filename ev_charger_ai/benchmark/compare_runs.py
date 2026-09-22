"""Compare two competition runs (two data roots) on the same held-out set.

    python benchmark/compare_runs.py E:\\ev_charger_ai_data E:\\ev_charger_ai_data_v3 [test]

Reads results/leaderboard_<tag>.json and results/records_<tag>.json from both
roots and prints

  * the two leaderboards side by side with deltas (score, recall, FAR,
    earliness, wins, median lead)
  * per-family recall deltas per detector
  * ground-truth drift: sessions matched across runs by (station, connector,
    t_start) since session indices can shift when a ring gained files
  * per-detector session-level agreement on the matched sessions: how many
    faulty sessions flipped detected<->missed and clean sessions flipped
    quiet<->false-alarm

Writes results/compare_<tag>.json into the second (new) root.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.metrics import LATE_GRACE_S  # noqa: E402  same grace as the scorer

DETS = ["AgenticAI", "TraditionalAI", "MultiAgent", "AIAgent", "RL"]


def load(root, tag):
    rdir = os.path.join(root, "results")
    with open(os.path.join(rdir, f"leaderboard_{tag}.json"),
              encoding="utf-8") as fh:
        lb = json.load(fh)
    with open(os.path.join(rdir, f"records_{tag}.json"),
              encoding="utf-8") as fh:
        rec = json.load(fh)
    return lb, rec


def skey(r):
    lab = r["label"]
    # t_start rounded to the second: the same capture replayed twice gives
    # identical stamps, but be tolerant of float formatting drift
    return (lab["station"], lab["connector"], round(lab["t_start"]))


def outcome(r, det):
    """faulty session -> 'tp' | 'late' | 'miss'; clean -> 'quiet' | 'fp'."""
    lab = r["label"]
    a = r["alerts"].get(det)
    if lab["faults"]:
        if a is None:
            return "miss"
        t_fault = min(f[0] for f in lab["faults"])
        return "tp" if a["t"] <= t_fault + LATE_GRACE_S else "late"
    return "fp" if a is not None else "quiet"


def fmt_delta(v, digits=1, pct=False):
    if pct:
        v = v * 100
    s = f"{v:+.{digits}f}"
    return s + ("pp" if pct else "")


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    old_root, new_root = sys.argv[1], sys.argv[2]
    tag = sys.argv[3] if len(sys.argv) > 3 else "test"
    lb_o, rec_o = load(old_root, tag)
    lb_n, rec_n = load(new_root, tag)

    out = {"old_root": old_root, "new_root": new_root, "tag": tag}

    def wall_min(lb):
        ws = lb.get("wall_seconds", 0)
        if isinstance(ws, dict):
            ws = sum(float(v) for v in ws.values())
        return float(ws) / 60

    print(f"OLD {old_root}: faulty {lb_o['n_faulty']}  clean {lb_o['n_clean']}"
          f"  detector compute {wall_min(lb_o):.0f} min (summed)")
    print(f"NEW {new_root}: faulty {lb_n['n_faulty']}  clean {lb_n['n_clean']}"
          f"  detector compute {wall_min(lb_n):.0f} min (summed)")
    print()

    # ---- leaderboard side by side -------------------------------------
    print(f"{'detector':14s} {'score old':>10s} {'new':>7s} {'delta':>7s} | "
          f"{'recall':>13s} | {'FAR':>13s} | {'earli':>13s} | "
          f"{'wins':>13s} | {'med lead s':>13s}")
    rows = {}
    order = sorted(DETS, key=lambda d: -lb_n["detectors"][d]["score"])
    for d in order:
        o, n = lb_o["detectors"][d], lb_n["detectors"][d]
        rows[d] = {k: {"old": o[k], "new": n[k], "delta": n[k] - o[k]}
                   for k in ("score", "recall", "far", "earliness", "wins",
                             "median_lead_s", "tp", "late", "miss", "fp")}
        print(f"{d:14s} {o['score']:10.1f} {n['score']:7.1f} "
              f"{fmt_delta(n['score']-o['score']):>7s} | "
              f"{o['recall']*100:5.1f}>{n['recall']*100:5.1f}"
              f"{fmt_delta(n['recall']-o['recall'], pct=True):>8s} | "
              f"{o['far']*100:5.1f}>{n['far']*100:5.1f}"
              f"{fmt_delta(n['far']-o['far'], pct=True):>8s} | "
              f"{o['earliness']*100:5.1f}>{n['earliness']*100:5.1f}"
              f"{fmt_delta(n['earliness']-o['earliness'], pct=True):>8s} | "
              f"{o['wins']:6.1f}>{n['wins']:6.1f} | "
              f"{o['median_lead_s']:6.1f}>{n['median_lead_s']:6.1f}")
    out["leaderboard"] = rows
    rank_old = [d for d in sorted(DETS,
                                  key=lambda d: -lb_o["detectors"][d]["score"])]
    print(f"\nranking old: {' > '.join(rank_old)}")
    print(f"ranking new: {' > '.join(order)}"
          + ("   (unchanged)" if rank_old == order else "   (CHANGED)"))
    out["ranking"] = {"old": rank_old, "new": order}

    # ---- per-family recall ------------------------------------------------
    fams = sorted({f for d in DETS
                   for f in lb_n["detectors"][d]["by_family"]})
    print(f"\nper-family recall (old > new, n_old/n_new)")
    print(f"{'family':16s}" + "".join(f"{d:>22s}" for d in order))
    fam_rows = {}
    for f in fams:
        cells = []
        fam_rows[f] = {}
        for d in order:
            bo = lb_o["detectors"][d]["by_family"].get(f)
            bn = lb_n["detectors"][d]["by_family"].get(f)
            if bo is None or bn is None:
                cells.append(f"{'-':>22s}")
                continue
            fam_rows[f][d] = {"old": bo["recall"], "new": bn["recall"],
                              "n_old": bo["n"], "n_new": bn["n"]}
            cells.append(f"{bo['recall']*100:5.1f}>{bn['recall']*100:5.1f}"
                         f" ({bo['n']}/{bn['n']})".rjust(22))
        print(f"{f:16s}" + "".join(cells))
    out["by_family"] = fam_rows

    # ---- ground-truth drift ---------------------------------------------
    mo = {skey(r): r for r in rec_o}
    mn = {skey(r): r for r in rec_n}
    common = sorted(set(mo) & set(mn))
    only_old = sorted(set(mo) - set(mn))
    only_new = sorted(set(mn) - set(mo))
    def fault_sig(r):
        # family, detail and time (1 s) of every fault, plus the session
        # extent: a session whose content changed is not "the same session"
        # even if it still carries the same family
        lab = r["label"]
        return (sorted((f[1], f[2], round(f[0])) for f in lab["faults"]),
                round(lab["t_end"]))

    label_changed = []
    for k in common:
        so, sn = fault_sig(mo[k]), fault_sig(mn[k])
        if so != sn:
            fo = [(f[0], f[1]) for f in so[0]]
            fn = [(f[0], f[1]) for f in sn[0]]
            label_changed.append((k, fo, fn))
    print(f"\nground truth: {len(common)} sessions in both runs, "
          f"{len(only_old)} only in old, {len(only_new)} only in new, "
          f"{len(label_changed)} relabelled")
    by_station_new = {}
    for k in only_new:
        by_station_new[k[0]] = by_station_new.get(k[0], 0) + 1
    for st, n in sorted(by_station_new.items(), key=lambda x: -x[1])[:10]:
        print(f"   new sessions at {st}: {n}")
    for k, fo, fn in label_changed[:10]:
        print(f"   relabelled {k[0]}/{k[1]}@{k[2]}: {fo} -> {fn}")
    out["ground_truth"] = {
        "common": len(common), "only_old": len(only_old),
        "only_new": len(only_new), "relabelled": len(label_changed),
        "new_sessions_by_station": by_station_new,
        "relabelled_examples": [
            {"station": k[0], "connector": k[1], "t_start": k[2],
             "old": fo, "new": fn} for k, fo, fn in label_changed[:50]],
    }

    # ---- session-level agreement on the common set ----------------------
    print(f"\nsession-level flips on the {len(common)} common sessions "
          f"(same label in both runs)")
    print(f"{'detector':14s} {'faulty: kept':>12s} {'gained':>8s} {'lost':>6s}"
          f" | {'clean: kept':>12s} {'newFP':>7s} {'fixedFP':>8s}")
    flips = {}
    stable = [k for k in common if fault_sig(mo[k]) == fault_sig(mn[k])]
    for d in order:
        c = {"kept_tp": 0, "gained": 0, "lost": 0,
             "kept_quiet": 0, "new_fp": 0, "fixed_fp": 0, "examples": []}
        for k in stable:
            oo, on = outcome(mo[k], d), outcome(mn[k], d)
            if mo[k]["label"]["faults"]:
                hit_o, hit_n = oo == "tp", on == "tp"
                if hit_o and hit_n:
                    c["kept_tp"] += 1
                elif hit_n and not hit_o:
                    c["gained"] += 1
                elif hit_o and not hit_n:
                    c["lost"] += 1
                    if len(c["examples"]) < 5:
                        c["examples"].append(
                            f"lost {k[0]}/{k[1]}@{k[2]} ({oo}->{on})")
            else:
                if oo == "quiet" and on == "quiet":
                    c["kept_quiet"] += 1
                elif on == "fp" and oo == "quiet":
                    c["new_fp"] += 1
                elif oo == "fp" and on == "quiet":
                    c["fixed_fp"] += 1
        flips[d] = c
        print(f"{d:14s} {c['kept_tp']:12d} {c['gained']:8d} {c['lost']:6d}"
              f" | {c['kept_quiet']:12d} {c['new_fp']:7d} {c['fixed_fp']:8d}")
    out["flips"] = flips

    path = os.path.join(new_root, "results", f"compare_{tag}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=float)
    print(f"\nwritten: {path}")


if __name__ == "__main__":
    main()
