"""Run extract_worker over every pcap under PCAP_ROOT with a process pool.

Resumable: skips outputs that already exist, and leaves alone any pcap still
being written by the downloader (settle guard). Writes manifest.json ordering
each connector's ring-buffer files by first packet time; that comes from the
per-file .meta.json sidecars, so it costs nothing even at 100+ GB of CSV.

    python pipeline/extract_all.py                 # everything
    python pipeline/extract_all.py --stations A,B  # only station keys containing A or B
    python pipeline/extract_all.py --workers 8
"""
import argparse
import concurrent.futures as cf
import csv
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from extract_worker import extract  # noqa: E402
from core.paths import (TELEMETRY, PCAP_ROOT, iter_stations,  # noqa: E402
                        iter_connectors, ensure_dirs)

DST = TELEMETRY
WORKERS = 14
# A pcap still being written by the downloader would extract short and then be
# skipped forever (outputs are resumable). Only touch files quiet this long.
SETTLE_S = 180


def jobs(only=None):
    now = time.time()
    skipped_hot = 0
    for key, sdir, _group in iter_stations(PCAP_ROOT):
        if only and not any(s in key for s in only):
            continue
        for conn, cdir in iter_connectors(sdir):
            outdir = os.path.join(DST, key, conn)
            os.makedirs(outdir, exist_ok=True)
            for f in sorted(os.listdir(cdir)):
                if not f.endswith(".pcap"):
                    continue
                src = os.path.join(cdir, f)
                dst = os.path.join(outdir, f[:-5] + ".csv")
                if os.path.exists(dst):
                    continue
                try:
                    if now - os.path.getmtime(src) < SETTLE_S:
                        skipped_hot += 1
                        continue
                except OSError:
                    continue
                yield (src, dst)
    if skipped_hot:
        print(f"(skipped {skipped_hot} pcaps still being written)", flush=True)


def run_one(job):
    src, dst = job
    try:
        n = extract(src, dst)
        return (src, dst, n, None)
    except Exception as e:  # noqa: BLE001
        return (src, dst, 0, str(e))


def file_span(csv_path):
    """(first, last, rows) from the sidecar, else by scanning the CSV.

    A sidecar missing its span (older extraction, or one rewritten by a
    consumer that only cared about another field) must fall through to the
    scan — never silently drop the file from the manifest.
    """
    meta = csv_path[:-4] + ".meta.json"
    try:
        with open(meta) as fh:
            m = json.load(fh)
        if m.get("first") is not None:
            return m["first"], m["last"], m["rows"]
    except (OSError, ValueError, KeyError):
        pass
    first = last = None
    nrows = 0
    try:
        with open(csv_path, encoding="utf-8") as fh:
            rd = csv.reader(fh)
            next(rd, None)
            for row in rd:
                if not row or not row[0]:
                    continue
                ts = float(row[0])
                if first is None:
                    first = ts
                last = ts
                nrows += 1
    except Exception:  # noqa: BLE001
        return None
    return (first, last, nrows) if first is not None else None


def build_manifest():
    """Index every extracted connector, restricted to canonical stations.

    Telemetry for clone stations may already exist from an earlier run;
    leaving them out here keeps every downstream stage clean without having
    to delete anything.
    """
    canonical = {k for k, _d, _g in iter_stations(PCAP_ROOT)}
    manifest = {}
    skipped_clones = 0
    n_dupe_files = 0
    for station in sorted(os.listdir(DST)):
        sdir = os.path.join(DST, station)
        if not os.path.isdir(sdir):
            continue
        if station not in canonical:
            skipped_clones += 1
            continue
        for conn in sorted(os.listdir(sdir)):
            cdir = os.path.join(sdir, conn)
            if not os.path.isdir(cdir):
                continue
            entries = []
            for f in os.listdir(cdir):
                if not f.endswith(".csv"):
                    continue
                span = file_span(os.path.join(cdir, f))
                if span:
                    entries.append({"file": f, "first": span[0],
                                    "last": span[1], "rows": span[2]})
            # The downloader retries a ring slot as ethlog0.r2, .r3, even
            # .r2.r2. Those re-downloads carry the SAME packets (measured:
            # 152 pairs with identical start time and identical row counts),
            # so replaying them would duplicate every dialog and rewind the
            # clock inside the streaming splitter. Keep, per capture start,
            # only the file that reaches furthest; drop anything its span
            # already covers.
            entries.sort(key=lambda e: (e["first"], -e["last"], -e["rows"]))
            uniq = []
            for e in entries:
                if uniq and e["last"] <= uniq[-1]["last"]:
                    n_dupe_files += 1
                    continue
                uniq.append(e)
            manifest[f"{station}/{conn}"] = uniq
    if skipped_clones or n_dupe_files:
        print(f"manifest: skipped {skipped_clones} clone station(s), "
              f"{n_dupe_files} duplicate ring file(s)", flush=True)
    with open(os.path.join(DST, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", default="",
                    help="comma-separated substrings of station keys to include")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--manifest-only", action="store_true")
    args = ap.parse_args()
    ensure_dirs()
    only = [s for s in args.stations.split(",") if s.strip()] or None

    t0 = time.time()
    errors = []
    if not args.manifest_only:
        all_jobs = list(jobs(only))
        total = len(all_jobs)
        print(f"{total} files to extract, {args.workers} workers, "
              f"src={PCAP_ROOT} dst={DST}", flush=True)
        done = 0
        # The machine is shared: under memory pressure Windows can kill a
        # pool worker, and ProcessPoolExecutor then fails every pending
        # future with BrokenProcessPool. Losing an hours-long stage to one
        # dead worker is not acceptable, so rebuild the pool and carry on --
        # completed files are skipped on the retry because their CSV exists.
        attempt = 0
        pending = all_jobs
        while pending:
            attempt += 1
            if attempt > 1:
                pending = [(s, d) for s, d in pending
                           if not os.path.exists(d)]
                if not pending:
                    break
                workers = max(2, args.workers // 2 ** (attempt - 1))
                print(f"-- pool restart #{attempt-1}: {len(pending)} files "
                      f"left, {workers} workers", flush=True)
            else:
                workers = args.workers
            try:
                with cf.ProcessPoolExecutor(max_workers=workers) as ex:
                    for src, dst, n, err in ex.map(run_one, pending,
                                                   chunksize=1):
                        done += 1
                        if err:
                            errors.append({"src": src, "err": err})
                            print(f"[{done}/{total}] ERROR {src}: {err}",
                                  flush=True)
                        elif done % 100 == 0 or done == total:
                            rate = done / (time.time() - t0)
                            eta = (total - done) / rate / 60 if rate else 0
                            print(f"[{done}/{total}] {rate:.2f} f/s "
                                  f"ETA {eta:.0f} min", flush=True)
                pending = []
            except cf.process.BrokenProcessPool as e:
                if attempt >= 6:
                    raise
                print(f"!! pool broken ({e}); rebuilding", flush=True)
                time.sleep(20)
        with open(os.path.join(DST, "extract_errors.json"), "w") as fh:
            json.dump(errors, fh, indent=1)

    manifest = build_manifest()
    n_files = sum(len(v) for v in manifest.values())
    print(f"DONE in {(time.time()-t0)/60:.1f} min, {len(errors)} errors, "
          f"manifest: {len(manifest)} connectors / {n_files} files", flush=True)


if __name__ == "__main__":
    main()
