"""Reconstruct charging sessions from extracted telemetry CSVs.

Per connector: order ring-buffer files chronologically (manifest), stream the
rows through a session splitter, and emit each session as soon as it closes.
Session boundaries are defined on *activity* rows (v2g / sdp / SLAC / tcp),
because idle periods contain only LINK_STATUS polling:

  - a new session starts at the first activity row after an idle gap
    (> IDLE_GAP_S between consecutive activity rows), or at a
    supportedAppProtocolReq that follows a closed V2G session
  - all rows (including LINK_STATUS) between start and end belong to the session

Streaming matters at fleet scale: a row costs ~1.6 kB as a dict, so the
largest connector (411 ring files) would need ~9 GB held at once, and several
such workers would exhaust the Windows commit limit mid-run. Emitting sessions
as they close caps a worker at one session (tens of MB). It is exactly
equivalent to load-all-then-sort because ring files never overlap in time and
rows are monotonic within a file (both verified on the real telemetry).

Outputs: sessions/<station>__<connector>__<idx>.csv and sessions/index.json
(with ground-truth labels from ground_truth.py).

    python pipeline/sessionize.py
    python pipeline/sessionize.py --stations 2024__,2025__   # subset by key
    python pipeline/sessionize.py --workers 6
"""
import argparse
import concurrent.futures as cf
import csv
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from pipeline.ground_truth import label_session  # noqa: E402
from pipeline.extract_worker import COLUMNS  # noqa: E402
from core import paths  # noqa: E402

TELEMETRY = paths.TELEMETRY
OUT = paths.SESSIONS
SIZE_CAP_B = 4_500_000   # ethlog ring rotates at ~4.6 MB

IDLE_GAP_S = 60.0
ACTIVITY_KINDS = {"v2g", "sdp", "tcp"}
SLAC_ACTIVITY = ("SLAC", "ATTEN_CHAR", "SET_KEY", "VALIDATE")
# a capture that opens on one of these starts a dialog cleanly; anything else
# means the file resumed mid-dialog, i.e. packets before it are missing
V2G_OPENERS = ("supportedAppProtocolReq", "supportedAppProtocolRes",
               "SessionSetupReq")
WORKERS = 4


def is_activity(row):
    if row["kind"] in ACTIVITY_KINDS:
        return True
    if row["kind"] == "hpav":
        return any(k in row["msg"] for k in SLAC_ACTIVITY)
    return False


def first_v2g_msg(csv_path):
    """First v2g message name in a telemetry file, cached in its sidecar.

    Only needed for the ring-seam test. Cached because a file with no v2g row
    at all has to be read to the end to establish that.
    """
    meta_path = csv_path[:-4] + ".meta.json"
    meta = None
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        if "first_v2g" in meta:
            return meta["first_v2g"]
    except (OSError, ValueError):
        meta = None
    fv = None
    try:
        with open(csv_path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("kind") == "v2g":
                    fv = row["msg"]
                    break
    except OSError:
        return None
    # Only ever augment a sidecar we actually read: rows/first/last in it are
    # the manifest's source of truth, and rewriting from scratch would erase
    # them and drop the file from every future manifest.
    if isinstance(meta, dict):
        meta["first_v2g"] = fv
        try:
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh)
        except OSError:
            pass
    return fv


def connector_cuts(station, conn, entries):
    """Timestamps where data is provably missing, so a session ending there
    cannot be judged. Idle periods emit no packets, so nearly every session
    ends at a file boundary followed by an hours-long hole — that is NORMAL.
    A cut is only a file rotated at the size cap mid-activity whose
    continuation was not downloaded, a file that resumes mid-dialog, or the
    very end of the capture."""
    src_dir = os.path.join(paths.station_src_dir(station), conn)
    tel_dir = os.path.join(TELEMETRY, station, conn)
    bounds = []
    for ent in entries:
        pcap = os.path.join(src_dir, ent["file"].replace(".csv", ".pcap"))
        try:
            size = os.path.getsize(pcap)
        except OSError:
            size = 0
        bounds.append((ent["first"], ent["last"], size,
                       first_v2g_msg(os.path.join(tel_dir, ent["file"]))))
    cuts = []
    if bounds:
        for (f1, l1, sz1, m1), (f2, l2, sz2, m2) in zip(bounds, bounds[1:]):
            if f2 - l1 <= 60.0:
                continue
            resumed_mid = m2 is not None and m2 not in V2G_OPENERS
            if sz1 >= SIZE_CAP_B or resumed_mid:
                cuts.append(l1)
        cuts.append(bounds[-1][1])
    return cuts


def iter_rows(station, conn, entries):
    """Rows of a connector in chronological order, one file open at a time."""
    tel_dir = os.path.join(TELEMETRY, station, conn)
    for ent in entries:
        with open(os.path.join(tel_dir, ent["file"]), encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("t"):
                    row["t"] = float(row["t"])
                    yield row


def iter_sessions(rows):
    """Stream rows -> yield one list per session.

    Folds together what used to be two passes: the idle-gap split, and the
    split at a new dialog opener that follows a closed V2G dialog.
    `seen_close` resets at every idle-gap boundary, matching the old code's
    per-raw-session second pass.
    """
    cur = []
    last_activity_t = None
    session_open = False
    pending_quiet = []
    seen_close = False

    def start_chunk(row, carry_quiet):
        """Open a chunk at `row`, optionally carrying recent quiet rows."""
        chunk = ([q for q in carry_quiet if row["t"] - q["t"] <= 10.0]
                 if carry_quiet else [])
        chunk.append(row)
        return chunk

    for row in rows:
        act = is_activity(row)
        if not session_open:
            if act:
                session_open = True
                seen_close = False
                cur = start_chunk(row, pending_quiet)
                pending_quiet = []
                last_activity_t = row["t"]
                if row["msg"] in ("SessionStopRes", "SessionStopReq"):
                    seen_close = True
                continue
            pending_quiet.append(row)
            if len(pending_quiet) > 200:
                pending_quiet = pending_quiet[-100:]
            continue

        # a session is open
        gap = row["t"] - last_activity_t
        if act:
            if gap > IDLE_GAP_S:
                if cur:
                    yield cur
                cur = [row]
                seen_close = False
            else:
                if (row["msg"] in ("supportedAppProtocolReq",
                                   "SessionSetupReq") and cur
                        and seen_close):
                    yield cur
                    cur = []
                    seen_close = False
                cur.append(row)
            last_activity_t = row["t"]
            if row["msg"] in ("SessionStopRes", "SessionStopReq"):
                seen_close = True
        else:
            if gap > IDLE_GAP_S:
                if cur:
                    yield cur
                cur = []
                session_open = False
                seen_close = False
                pending_quiet = [row]
            else:
                cur.append(row)
    if session_open and cur:
        yield cur


def process_station(args):
    """Worker: all connectors of one station -> (index entries, n_truncated).

    The output directory travels in the task tuple: on Windows the pool spawns
    fresh interpreters that re-import this module, so a global set in main()
    would not reach the workers.
    """
    station, conns, manifest, out_dir = args
    index = []
    n_truncated = 0
    for conn in conns:
        entries = manifest.get(f"{station}/{conn}", [])
        if not entries:
            continue
        cuts = connector_cuts(station, conn, entries)
        for i, sess in enumerate(iter_sessions(
                iter_rows(station, conn, entries))):
            skey = f"{station}__{conn}__{i:04d}"
            label = label_session(skey, station, conn, sess)
            if label is None:      # pure noise chunk, skip
                continue
            if is_truncation_artifact(label, cuts):
                n_truncated += 1
                continue
            path = os.path.join(out_dir, skey + ".csv")
            # always rewrite: a session file left over from an earlier run
            # can carry the same key with different content once the ring
            # gained files, so "already exists" is not "already correct"
            with open(path, "w", newline="", encoding="utf-8") as fh:
                wr = csv.DictWriter(fh, fieldnames=COLUMNS,
                                    extrasaction="ignore")
                wr.writeheader()
                wr.writerows(sess)
            d = label.__dict__.copy()
            d["group"] = paths.station_group(station)
            index.append(d)
    return station, index, n_truncated


def is_truncation_artifact(label, cuts):
    """True for an unjudgeable non-graceful end at a known data cut.

    Keep sessions with independent fault evidence, but drop clean strict-mode
    tails and legacy aborts anchored at capture loss / ring wraparound.
    """
    near_end_cut = any(abs(label.t_end - c) <= 5.0 for c in cuts)

    # Strict ground truth deliberately leaves an uncorroborated, non-graceful
    # end clean.  A session that ends at a *known data cut* is different: it is
    # unjudgeable, not a clean negative.  Legacy labels carried a synthetic
    # SESSION_ABORT at t_end and therefore reached the check below; strict
    # labels have no fault, so handle that case explicitly.
    if not label.faults:
        return not label.graceful_close and near_end_cut
    if any(f[1] not in ("SESSION_ABORT",) for f in label.faults):
        return False
    # anchor on the fault itself, not the session end: a session that merely
    # happens to finish near a cut may carry a genuine abort long before it
    return any(abs(f[0] - c) <= 5.0 for f in label.faults for c in cuts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", default="",
                    help="comma-separated substrings of station keys")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--out", default="", help="override sessions dir")
    ap.add_argument("--complete-only", action="store_true",
                    help="skip stations whose telemetry is not yet complete "
                         "(lets this run alongside an in-progress extraction)")
    args = ap.parse_args()
    only = [s for s in args.stations.split(",") if s.strip()] or None
    out_dir = args.out or OUT

    with open(os.path.join(TELEMETRY, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    os.makedirs(out_dir, exist_ok=True)

    complete = None
    if args.complete_only:
        complete = set()
        incomplete = 0
        for key, sdir, _g in paths.iter_stations():
            missing = 0
            for conn, cdir in paths.iter_connectors(sdir):
                od = os.path.join(TELEMETRY, key, conn)
                for f in os.listdir(cdir):
                    if f.endswith(".pcap") and not os.path.exists(
                            os.path.join(od, f[:-5] + ".csv")):
                        missing += 1
            if missing:
                incomplete += 1
            else:
                complete.add(key)
        print(f"--complete-only: {len(complete)} stations ready, "
              f"{incomplete} still extracting", flush=True)

    by_station = {}
    for key in sorted(manifest):
        station, conn = key.rsplit("/", 1)
        if only and not any(s in station for s in only):
            continue
        if complete is not None and station not in complete:
            continue
        by_station.setdefault(station, []).append(conn)
    tasks = [(st, conns, {f"{st}/{c}": manifest[f"{st}/{c}"] for c in conns},
              out_dir) for st, conns in by_station.items()]
    print(f"{len(tasks)} stations, {args.workers} workers -> {out_dir}",
          flush=True)

    index = []
    n_truncated = 0
    t0 = time.time()
    with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
        for k, (station, entries, ntr) in enumerate(
                ex.map(process_station, tasks, chunksize=1), 1):
            index.extend(entries)
            n_truncated += ntr
            if k % 10 == 0 or k == len(tasks):
                print(f"[{k}/{len(tasks)}] {station}: {len(entries)} sessions "
                      f"({(time.time()-t0)/60:.1f} min)", flush=True)

    index.sort(key=lambda e: e["session_key"])
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1, ensure_ascii=False)
    n_faulty = sum(1 for e in index if e["faults"])
    print(f"TOTAL sessions: {len(index)}  faulty: {n_faulty}  "
          f"dropped-truncated: {n_truncated}  "
          f"({(time.time()-t0)/60:.1f} min)", flush=True)


if __name__ == "__main__":
    main()
