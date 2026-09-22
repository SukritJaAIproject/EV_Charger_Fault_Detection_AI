"""Aggregate a finished run into one compact JSON for the ops dashboard.

    python build_data.py [DATA_ROOT] [OUT.json]

DATA_ROOT defaults to $EV_AI_DATA, then E:\\ev_charger_ai_data_v3, then
E:\\ev_charger_ai_data. Ground truth (sessions/index.json) covers every
station; detector alerts (results/records_test.json) cover only the held-out
stations, so anything AI-derived is tagged and kept separate.
"""
import collections
import datetime
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
try:
    # Drive letters move when a USB volume re-enumerates, so find the tree
    # by name and contents. stdlib only, so the system Python can use it.
    from core.findroot import find_dir
except ImportError:                     # running away from the checkout
    find_dir = None

ROOT_NAMES = ["ev_charger_ai_data_v4", "ev_charger_ai_data_v3",
              "ev_charger_ai_data"]
MARKER = os.path.join("sessions", "index.json")


def _candidates():
    out = [os.environ.get("EV_AI_DATA")]
    if find_dir:
        out += [find_dir(nm, MARKER) for nm in ROOT_NAMES]
    for drive in ("G:\\", "E:\\", "D:\\", "F:\\"):
        out += [os.path.join(drive, nm) for nm in ROOT_NAMES]
    return [c for c in out if c]


CANDIDATES = _candidates()

FAMILIES = ["SESSION_ABORT", "PROTOCOL_FAILED", "SLAC_FAILURE",
            "NO_POWER_DELIVERED", "EV_ERROR", "EVSE_FAULT", "COMM_FREEZE",
            "ISOLATION_FAULT"]
DETS = ["AgenticAI", "TraditionalAI", "MultiAgent", "AIAgent", "RL"]
LATE_GRACE_S = 10.0


def find_root(explicit=None):
    """First candidate that actually holds a finished sessionize run."""
    for c in ([explicit] if explicit else []) + CANDIDATES:
        if c and os.path.exists(os.path.join(c, "sessions", "index.json")):
            return c
    return None


def year_of(t):
    try:
        return datetime.datetime.utcfromtimestamp(t).year
    except (OverflowError, OSError, ValueError):
        return -1


def display(key):
    """Human label + short tag from a station key."""
    if key.startswith("2024__") or key.startswith("2025__"):
        round_, rest = key.split("__", 1)
        rest = rest.split("_", 1)[1] if "_" in rest else rest
        return rest.strip(), round_
    if "_" in key and key.split("_", 1)[0].isdigit():
        no, rest = key.split("_", 1)
        return rest.replace("_", " ").strip(), no
    return key, ""


def build(root, out_path):
    idx = json.load(open(os.path.join(root, "sessions", "index.json"),
                         encoding="utf-8"))
    split_path = os.path.join(root, "split.json")
    test_stations = set()
    if os.path.exists(split_path):
        test_stations = set(json.load(open(split_path,
                                           encoding="utf-8"))["test"])

    by_st = collections.defaultdict(list)
    for m in idx:
        by_st[m["station"]].append(m)

    # ---- per-station detector outcomes (held-out stations only) ----------
    det_by_st = collections.defaultdict(
        lambda: {d: {"tp": 0, "miss": 0, "fp": 0} for d in DETS})
    recs = os.path.join(root, "results", "records_test.json")
    if os.path.exists(recs):
        for r in json.load(open(recs, encoding="utf-8")):
            lab, al = r["label"], r["alerts"]
            faulty = bool(lab["faults"])
            t_f = min(f[0] for f in lab["faults"]) if faulty else None
            for d in DETS:
                a = al.get(d)
                cell = det_by_st[lab["station"]][d]
                if faulty:
                    if a is not None and a["t"] <= t_f + LATE_GRACE_S:
                        cell["tp"] += 1
                    else:
                        cell["miss"] += 1
                elif a is not None:
                    cell["fp"] += 1

    stations = []
    for key, ms in sorted(by_st.items()):
        name, tag = display(key)
        fam = collections.Counter()
        conn = collections.defaultdict(lambda: {"n": 0, "f": 0})
        faulty = 0
        for m in ms:
            c = conn[m["connector"]]
            c["n"] += 1
            if m["faults"]:
                faulty += 1
                c["f"] += 1
                for f in m["faults"]:
                    fam[f[1]] += 1
        med_t = statistics.median(m["t_start"] for m in ms)
        c1 = conn.get("connector1", {"n": 0, "f": 0})
        c2 = conn.get("connector2", {"n": 0, "f": 0})

        row = {
            "key": key, "name": name, "tag": tag, "group": ms[0]["group"],
            "n": len(ms), "faulty": faulty,
            "rate": round(faulty / len(ms), 4),
            "c1n": c1["n"], "c1f": c1["f"], "c2n": c2["n"], "c2f": c2["f"],
            "delivered": round(sum(1 for m in ms
                                   if m["reached_current_demand"]) / len(ms), 3),
            "graceful": round(sum(1 for m in ms
                                  if m["graceful_close"]) / len(ms), 3),
            "med_min": round(statistics.median(
                m["t_end"] - m["t_start"] for m in ms) / 60, 1),
            "clock": 1 if 2024 <= year_of(med_t) <= 2026 else 0,
            "held_out": 1 if key in test_stations else 0,
            "fam": {k: fam[k] for k in FAMILIES if fam[k]},
            "skew": None,
        }
        # A connector failing much more than its twin is a hardware lead: same
        # cabinet, same supply, similar traffic - the difference is the gun.
        if c1["n"] >= 30 and c2["n"] >= 30:
            r1, r2 = c1["f"] / c1["n"], c2["f"] / c2["n"]
            worse, better = (r1, r2) if r1 >= r2 else (r2, r1)
            if worse >= 0.05 and worse - better >= 0.05:
                row["skew"] = {"conn": 1 if r1 >= r2 else 2,
                               "worse": round(worse, 4),
                               "better": round(better, 4)}
        if key in det_by_st:
            row["ai"] = {d: det_by_st[key][d] for d in DETS}
        stations.append(row)

    fleet_fam = collections.Counter()
    for s in stations:
        for k, v in s["fam"].items():
            fleet_fam[k] += v

    detectors, held = {}, {}
    lb_path = os.path.join(root, "results", "leaderboard_test.json")
    if os.path.exists(lb_path):
        lb = json.load(open(lb_path, encoding="utf-8"))
        held = {"stations": len(test_stations),
                "faulty": lb["n_faulty"], "clean": lb["n_clean"]}
        for d in DETS:
            v = lb["detectors"][d]
            detectors[d] = {
                "score": round(v["score"], 1), "recall": round(v["recall"], 4),
                "far": round(v["far"], 4), "tp": v["tp"], "miss": v["miss"],
                "fp": v["fp"], "lead": round(v["median_lead_s"], 1),
                # per-family recall feeds the fault reference tab
                "fam": {k: [b["tp"], b["n"]]
                        for k, b in v.get("by_family", {}).items()},
            }

    # telemetry is often shared between run roots, so look past this one
    pcaps = 0
    shared = find_dir("ev_charger_ai_data", MARKER) if find_dir else None
    for tel in [os.environ.get("EV_AI_TELEMETRY"),
                os.path.join(root, "telemetry"),
                os.path.join(shared, "telemetry") if shared else None]:
        man = os.path.join(tel, "manifest.json") if tel else None
        if man and os.path.exists(man):
            pcaps = sum(len(v) for v in
                        json.load(open(man, encoding="utf-8")).values())
            break

    out = {
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "root": root,
        "fleet": {
            "stations": len(stations),
            "connectors": sum(1 for s in stations
                              for c in ("c1n", "c2n") if s[c] > 0),
            "sessions": sum(s["n"] for s in stations),
            "faulty": sum(s["faulty"] for s in stations),
            "clock_bad": sum(1 for s in stations if not s["clock"]),
            "skewed": sum(1 for s in stations if s["skew"]),
            "pcaps": pcaps,
            "families": dict(fleet_fam.most_common()),
        },
        "held_out": held,
        "detectors": detectors,
        "stations": stations,
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    return out


def main():
    root = find_root(sys.argv[1] if len(sys.argv) > 1 else None)
    if not root:
        raise SystemExit("no finished run found - looked for sessions\\index.json "
                         "under: " + ", ".join(c for c in CANDIDATES if c))
    out_path = (sys.argv[2] if len(sys.argv) > 2
                else os.path.join(HERE, "build", "fleet.json"))
    out = build(root, out_path)
    print("root      :", root)
    print("stations  :", out["fleet"]["stations"],
          " sessions:", out["fleet"]["sessions"],
          " faulty:", out["fleet"]["faulty"])
    print("flags     : clock_bad", out["fleet"]["clock_bad"],
          " connector-skew", out["fleet"]["skewed"])
    print("written   :", out_path, os.path.getsize(out_path), "bytes")


if __name__ == "__main__":
    main()
