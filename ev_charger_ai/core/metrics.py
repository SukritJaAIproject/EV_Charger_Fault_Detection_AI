"""Competition scoring.

Per faulty session (first hard fault at T_f):
  on-time detection : first alert <= T_f + LATE_GRACE_S   (lead = T_f - t_alert, >= 0)
  late detection    : first alert in (T_f + LATE_GRACE_S, session end]
  miss              : no alert
Per clean session: any alert = false alarm.

Score (0..100) = 50*Recall + 30*(1-FAR) + 20*Earliness
  Recall     = on-time detections / faulty sessions
  FAR        = false alarms / clean sessions
  Earliness  = mean over faulty sessions of min(lead, LEAD_CAP)/LEAD_CAP
               (missed / late sessions contribute 0)

Head-to-head: per faulty session, earliest on-time detector wins the session
(ties within TIE_S share the win).
"""
LEAD_CAP = 120.0
LATE_GRACE_S = 10.0
TIE_S = 0.1


def score_detectors(records, detector_names):
    per = {d: {"tp": 0, "late": 0, "miss": 0, "fp": 0, "leads": [],
               "earliness_sum": 0.0, "wins": 0.0, "by_family": {}}
           for d in detector_names}
    n_faulty = n_clean = 0

    for rec in records:
        label = rec["label"]
        faulty = bool(label["faults"])
        if faulty:
            n_faulty += 1
            t_f = min(f[0] for f in label["faults"])
            family = min(label["faults"], key=lambda f: f[0])[1]
            ontime = {}
            for d in detector_names:
                fam_stats = per[d]["by_family"].setdefault(
                    family, {"tp": 0, "n": 0})
                fam_stats["n"] += 1
                a = rec["alerts"].get(d)
                if a is None:
                    per[d]["miss"] += 1
                    continue
                t_a = a["t"]
                if t_a <= t_f + LATE_GRACE_S:
                    lead = max(0.0, t_f - t_a)
                    per[d]["tp"] += 1
                    per[d]["leads"].append(lead)
                    per[d]["earliness_sum"] += min(lead, LEAD_CAP) / LEAD_CAP
                    fam_stats["tp"] += 1
                    ontime[d] = t_a
                else:
                    per[d]["late"] += 1
            if ontime:
                best = min(ontime.values())
                winners = [d for d, t in ontime.items() if t - best <= TIE_S]
                for d in winners:
                    per[d]["wins"] += 1.0 / len(winners)
        else:
            n_clean += 1
            for d in detector_names:
                if rec["alerts"].get(d) is not None:
                    per[d]["fp"] += 1

    out = {}
    for d in detector_names:
        s = per[d]
        recall = s["tp"] / n_faulty if n_faulty else 0.0
        far = s["fp"] / n_clean if n_clean else 0.0
        earliness = s["earliness_sum"] / n_faulty if n_faulty else 0.0
        leads = sorted(s["leads"])
        median_lead = leads[len(leads) // 2] if leads else 0.0
        out[d] = {
            "recall": recall, "far": far, "earliness": earliness,
            "score": 50 * recall + 30 * (1 - far) + 20 * earliness,
            "tp": s["tp"], "late": s["late"], "miss": s["miss"], "fp": s["fp"],
            "median_lead_s": median_lead,
            "mean_lead_s": sum(leads) / len(leads) if leads else 0.0,
            "wins": round(s["wins"], 2),
            "by_family": {
                fam: {"recall": v["tp"] / v["n"] if v["n"] else 0.0, **v}
                for fam, v in s["by_family"].items()},
        }
    return {"n_faulty": n_faulty, "n_clean": n_clean, "detectors": out}
