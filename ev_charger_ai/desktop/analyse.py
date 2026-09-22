"""Analyse uploaded pcap files the same way the fleet pipeline does.

One call takes a handful of pcaps from one charger connector, decodes them with
tshark + the dsV2Gshark dissector, splits the stream into charging sessions, and
labels every fault using `pipeline.ground_truth` - the exact labeller behind the
numbers on the dashboard, so an uploaded file is judged by the same rules as the
fleet. When the trained artifacts are present it also replays the five
detectors over each session and reports what each of them would have caught.

Used by the desktop app's "analyse a file" tab, which runs this file as a
SUBPROCESS: the detectors need torch and xgboost, which live in the conda env,
while the app itself stays stdlib-only. Progress lines go to stdout prefixed
with "#" so the parent can show them live.

    python analyse.py ethlog1.pcap ethlog1.r1.pcap
    python analyse.py --json out.json --no-ai ethlog1.pcap
"""
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)

MAX_FILES = 12
MAX_BYTES = 400 * 1024 * 1024
TSHARK_HINT = r"C:\Program Files\Wireshark\tshark.exe"

# Each detector is imported only if it is picked: Multi-Agent is rules-only and
# runs anywhere, while the other four pull in torch or joblib and need their
# trained artifact on disk.
FACTORY = {
    "AgenticAI":     ("models.agentic_ai", "AgenticAI", ["lstm_ae.pt", "gru_fore.pt"]),
    "TraditionalAI": ("models.traditional", "TraditionalAI", ["traditional.joblib"]),
    "MultiAgent":    ("models.multi_agent", "MultiAgent", []),
    "AIAgent":       ("models.ai_agent", "AIAgent", ["lstm_ae.pt", "gru_fore.pt"]),
    "RL":            ("models.rl_detector", "RLDetector", ["dqn.pt"]),
}
ALL_MODELS = list(FACTORY)


def _project_on_path(data_root=None):
    """Put the pipeline on sys.path and point core.paths at the run we use.

    core.paths reads the environment at import time, so the data root has to be
    set before anything under pipeline/ or models/ is imported.
    """
    if data_root:
        os.environ.setdefault("EV_AI_DATA", data_root)
    if PROJECT not in sys.path:
        sys.path.insert(0, PROJECT)


def tshark_path():
    from pipeline import extract_worker
    return getattr(extract_worker, "TSHARK", TSHARK_HINT)


# --------------------------------------------------------------------------
def _extract(pcap_paths, tel_dir, note):
    """pcap -> telemetry CSV, one file at a time. Returns file descriptors."""
    from pipeline.extract_worker import extract

    os.makedirs(tel_dir, exist_ok=True)
    files = []
    for i, src in enumerate(pcap_paths, 1):
        base = os.path.basename(src)
        note("decoding %d/%d: %s" % (i, len(pcap_paths), base))
        out = os.path.join(tel_dir, base + ".csv")
        t0 = time.time()
        rows = extract(src, out)
        meta = {}
        meta_path = out[:-4] + ".meta.json"
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        files.append({
            "file": base, "csv": out, "rows": rows,
            "first": meta.get("first"), "last": meta.get("last"),
            "seconds": round(time.time() - t0, 1),
            "bytes": os.path.getsize(src),
        })
    return files


def _order_and_dedupe(files):
    """Chronological order, dropping ring re-downloads already covered.

    A charger's ring buffer is fetched repeatedly, so `ethlog7.pcap` and
    `ethlog7.r3.pcap` can hold the same packets. The manifest step of the fleet
    pipeline drops a file whose time span is already covered; do the same here
    so a session is not counted twice.
    """
    dated = [f for f in files if f.get("first") is not None]
    undated = [f for f in files if f.get("first") is None]
    dated.sort(key=lambda f: (f["first"], -(f["last"] or 0), -f["rows"]))
    keep, dropped = [], []
    for f in dated:
        if keep and (f["last"] or 0) <= (keep[-1]["last"] or 0):
            dropped.append(f["file"])
            continue
        keep.append(f)
    for f in undated:                       # no timestamps at all: empty file
        dropped.append(f["file"])
    return keep, dropped


PHASES = ["supportedAppProtocol", "SessionSetup", "ServiceDiscovery",
          "ServicePaymentSelection", "ContractAuthentication",
          "ChargeParameterDiscovery", "CableCheck", "PreCharge",
          "PowerDelivery", "CurrentDemand", "WeldingDetection", "SessionStop"]
PHASE_RANK = {m: i for i, m in enumerate(PHASES)}


def _observations(rows, lab):
    """Findings worth telling a person, whether or not they are faults.

    Returned as {code, args} so the page can render them in either language.
    """
    out = []
    v2g = [r for r in rows if r["kind"] == "v2g"]
    if not v2g:
        return out
    t_end = rows[-1]["t"]

    def base(msg):
        return msg[:-3] if msg[-3:] in ("Req", "Res") else msg

    # "how far did the charge get" must ignore the closing handshake, or every
    # session that stopped politely reports its furthest phase as SessionStop
    CHARGING = PHASE_RANK["CurrentDemand"]
    reached = max((PHASE_RANK.get(base(r["msg"]), -1) for r in v2g
                   if PHASE_RANK.get(base(r["msg"]), 99) <= CHARGING), default=-1)
    phase = PHASES[reached] if reached >= 0 else "?"

    # how far it got, when no power ever flowed
    if not lab["reached_current_demand"]:
        out.append({"code": "no_current_demand", "args": [phase]})

    # silence at the end while the powerline modem kept polling
    last_v2g = v2g[-1]["t"]
    quiet = t_end - last_v2g
    if quiet >= 10.0 and base(v2g[-1]["msg"]) != "SessionStop":
        after = sum(1 for r in rows if r["t"] > last_v2g)
        out.append({"code": "silent_after",
                    "args": [base(v2g[-1]["msg"]), round(quiet, 1), after]})

    # the insulation check having to retry
    cc = [r for r in v2g if r["msg"].startswith("CableCheck")]
    iso_rows = [r for r in cc if r.get("isolation")]
    bad = sum(1 for r in iso_rows if r["isolation"] not in ("Valid", ""))
    if iso_rows and bad:
        out.append({"code": "isolation_invalid", "args": [bad, len(iso_rows)]})
    if cc and (cc[-1]["t"] - cc[0]["t"]) > 10.0:
        out.append({"code": "cablecheck_long",
                    "args": [round(cc[-1]["t"] - cc[0]["t"], 1),
                             sum(1 for r in cc if r["msg"].endswith("Req"))]})

    # pre-charge that never reached the voltage the car asked for
    pc = [r for r in v2g if r["msg"].startswith("PreCharge")]
    target = None
    for r in pc:
        if r.get("ev_target_v"):
            try:
                target = float(r["ev_target_v"])
            except ValueError:
                pass
    reached_v = None
    for r in pc:
        if r.get("evse_v"):
            try:
                reached_v = float(r["evse_v"])
            except ValueError:
                pass
    if target and reached_v is not None and target - reached_v > 5.0:
        out.append({"code": "precharge_short",
                    "args": [round(reached_v, 1), round(target, 1),
                             round(target - reached_v, 1)]})

    # how long the powerline took to pair, when it is worth remarking on
    slac = [r for r in rows if r["kind"] == "hpav"
            and ("SLAC" in r["msg"] or "ATTEN_CHAR" in r["msg"])]
    if slac and v2g[0]["t"] > slac[0]["t"]:
        pair = v2g[0]["t"] - slac[0]["t"]
        if pair > 20.0:
            out.append({"code": "slac_slow", "args": [round(pair, 1)]})
    return out


def _iter_rows(files):
    for f in files:
        with open(f["csv"], encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("t"):
                    row["t"] = float(row["t"])
                    yield row


# --------------------------------------------------------------------------
def _build(names, note):
    """Instantiate just the chosen detectors. -> (detectors, {name: why not})"""
    import importlib
    from core.paths import ARTIFACTS

    built, skipped = [], {}
    for name in names:
        mod, cls, needs = FACTORY[name]
        missing = [f for f in needs
                   if not os.path.exists(os.path.join(ARTIFACTS, f))]
        if missing:
            skipped[name] = "missing " + ", ".join(missing)
            continue
        try:
            built.append(getattr(importlib.import_module(mod), cls)())
        except Exception as exc:        # a missing library, not a reason to stop
            skipped[name] = str(exc) or exc.__class__.__name__
    for k, v in skipped.items():
        note("cannot run %s: %s" % (k, v))
    return built, skipped


def _replay(sess_dir, labels, names, note):
    """Replay the chosen detectors over the labelled sessions.

    Returns (alerts_by_session, ran, skipped). `ran` names the detectors that
    actually observed the stream, so the caller can tell "raised no alert" from
    "never ran".
    """
    from core.stream import load_session_events
    from core.feature_tracker import FeatureTracker

    detectors, skipped = _build(names, note)
    if not detectors:
        return None, [], skipped
    out = {}
    for i, lab in enumerate(labels, 1):
        note("replaying the models %d/%d" % (i, len(labels)))
        events = load_session_events(lab["session_key"], sess_dir=sess_dir)
        tracker = FeatureTracker()
        for d in detectors:
            d.reset(lab["station"], lab["connector"])
        first = {}
        for ev in events:
            fs = tracker.update(ev)
            for d in detectors:
                try:
                    alerts = d.observe(ev, fs)
                except Exception:               # a detector must not sink the run
                    alerts = []
                if alerts and d.name not in first:
                    a = alerts[0]
                    first[d.name] = {"t": a.t, "confidence": a.confidence,
                                     "reason": a.reason,
                                     "fault_guess": a.fault_guess}
        for d in detectors:
            d.end_session(lab["station"], lab["connector"])
        out[lab["session_key"]] = first
    return out, [d.name for d in detectors], skipped


# --------------------------------------------------------------------------
def analyse(pcap_paths, workdir=None, run_ai=True, models=None,
            data_root=None, progress=None):
    """Decode, sessionise, label, and (optionally) replay the detectors."""
    notes = []

    def note(msg):
        notes.append(msg)
        if progress:
            progress(msg)

    if not pcap_paths:
        raise ValueError("no files")
    if len(pcap_paths) > MAX_FILES:
        raise ValueError("too many files (max %d)" % MAX_FILES)
    total_bytes = sum(os.path.getsize(p) for p in pcap_paths)
    if total_bytes > MAX_BYTES:
        raise ValueError("upload too large (max %d MB)" % (MAX_BYTES >> 20))

    _project_on_path(data_root)
    tsh = tshark_path()
    if not os.path.exists(tsh):
        raise RuntimeError("tshark not found at %s - install Wireshark with the "
                           "dsV2Gshark plugin" % tsh)

    own_dir = workdir is None
    workdir = workdir or tempfile.mkdtemp(prefix="egat_analyse_")
    tel_dir = os.path.join(workdir, "telemetry")
    sess_dir = os.path.join(workdir, "sessions")
    os.makedirs(sess_dir, exist_ok=True)
    t0 = time.time()

    try:
        files = _extract(pcap_paths, tel_dir, note)
        ordered, dropped = _order_and_dedupe(files)
        if dropped:
            note("skipped %d file(s) already covered by another: %s"
                 % (len(dropped), ", ".join(dropped)))
        if not ordered:
            return {"ok": True, "files": files, "sessions": [], "notes": notes,
                    "summary": {"files": len(files), "used": 0, "events": 0,
                                "sessions": 0, "faulty": 0, "seconds": 0}}

        from pipeline.sessionize import iter_sessions
        from pipeline.ground_truth import label_session
        from pipeline.extract_worker import COLUMNS

        note("splitting the stream into charging sessions")
        station, conn = "upload", "connector1"
        labels, n_events, n_noise = [], 0, 0
        for i, sess in enumerate(iter_sessions(_iter_rows(ordered))):
            skey = "%s__%s__%04d" % (station, conn, i)
            lab = label_session(skey, station, conn, sess)
            if lab is None:
                n_noise += 1
                continue
            with open(os.path.join(sess_dir, skey + ".csv"), "w", newline="",
                      encoding="utf-8") as fh:
                wr = csv.DictWriter(fh, fieldnames=COLUMNS,
                                    extrasaction="ignore")
                wr.writeheader()
                wr.writerows(sess)
            d = dict(lab.__dict__)
            d["faults"] = [[float(f[0]), f[1], f[2]] for f in d.get("faults", [])]
            d["obs"] = _observations(sess, d)
            labels.append(d)
            n_events += len(sess)

        note("%d session(s), %d with a fault" %
             (len(labels), sum(1 for x in labels if x["faults"])))

        want = [m for m in (models if models is not None else ALL_MODELS)
                if m in FACTORY]
        ai, ai_ran, ai_skipped = None, [], {}
        if run_ai and labels and want:
            try:
                ai, ai_ran, ai_skipped = _replay(sess_dir, labels, want, note)
            except Exception as exc:            # never fail the whole analysis
                note("AI replay failed: %s" % exc)
                ai_skipped = {m: str(exc) for m in want}

        fams = {}
        for lab in labels:
            for f in lab["faults"]:
                fams[f[1]] = fams.get(f[1], 0) + 1

        return {
            "ok": True,
            "files": [{k: v for k, v in f.items() if k != "csv"} for f in files],
            "used": [f["file"] for f in ordered],
            "dropped": dropped,
            "sessions": labels,
            "ai": ai,
            "ai_asked": want,
            "ai_ran": ai_ran,
            "ai_skipped": ai_skipped,
            "families": fams,
            "notes": notes,
            "summary": {
                "files": len(files), "used": len(ordered),
                "events": n_events, "noise_chunks": n_noise,
                "sessions": len(labels),
                "faulty": sum(1 for x in labels if x["faults"]),
                "faults": sum(len(x["faults"]) for x in labels),
                "seconds": round(time.time() - t0, 1),
            },
        }
    finally:
        if own_dir:
            shutil.rmtree(workdir, ignore_errors=True)


def main():
    args = sys.argv[1:]
    out_json, run_ai, data_root = None, True, None
    models = None
    files = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            i += 1; out_json = args[i]
        elif a == "--no-ai":
            run_ai = False
        elif a == "--models":
            i += 1
            models = [x for x in args[i].split(",") if x]
        elif a == "--data-root":
            i += 1; data_root = args[i]
        elif a.startswith("-"):
            raise SystemExit("unknown option %s" % a)
        else:
            files.append(a)
        i += 1
    if not files:
        raise SystemExit(__doc__)

    def emit(msg):
        print("#" + msg, flush=True)

    res = analyse(files, run_ai=run_ai, models=models, data_root=data_root,
                  progress=emit)
    if out_json:
        with io.open(out_json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False)
        print("#wrote " + out_json, flush=True)
        return
    s = res["summary"]
    print("\nfiles %d (used %d) · events %s · sessions %d · faulty %d · %.1fs"
          % (s["files"], s["used"], "{:,}".format(s["events"]), s["sessions"],
             s["faulty"], s["seconds"]))
    for lab in res["sessions"]:
        mark = "FAULT" if lab["faults"] else "ok   "
        print("  %s %s  %d events" % (mark, lab["session_key"], lab["n_events"]))
        for f in lab["faults"]:
            print("        %-16s %s" % (f[1], f[2]))
        for o in lab.get("obs", []):
            print("        note: %-12s %s" % (o["code"], o["args"]))
    if res.get("families"):
        print("\nfault families:", res["families"])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
