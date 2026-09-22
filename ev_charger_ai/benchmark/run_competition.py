"""THE COMPETITION — replay held-out sessions as a live stream.

All five detectors observe the exact same events and shared features, in
order, with no lookahead. First alert per session is scored: detection rate,
lead time before the fault, false alarms, head-to-head wins.

Sessions are replayed chronologically per connector; connectors run in
parallel worker processes. That preserves AgenticAI's cross-session station
memory exactly (its baselines are keyed per station/connector).

    python benchmark/run_competition.py test            # held-out stations
    python benchmark/run_competition.py train
    python benchmark/run_competition.py v2g2024         # one source group
    python benchmark/run_competition.py 003_,2024__1_   # station-key substrings
    python benchmark/run_competition.py test 0 18       # [split] [limit|0] [workers]

Set EV_AI_CLEAN_SAMPLE=N to keep every faulty session but only N clean ones,
drawn with a fixed seed. A full replay of the 1,909-session held-out split is
~9 h per arm on this machine (31.6 M events at ~3.3 ms/event across the five
detectors, capped at 4 worker processes by the Windows commit limit), which is
more than a three-arm comparison can afford. The sample keeps recall, lead time
and the per-family breakdown at full resolution and only coarsens the
false-alarm estimate. The draw is deterministic, so every arm scores exactly
the same sessions — the leaderboards stay comparable, which is the only
property that matters here. Sessions keep their chronological order inside each
connector, so AgenticAI's station memory still builds up the same way; it
simply sees fewer prior sessions, equally in every arm.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import sys
import time

# Inference is batch-1 numpy (models/fast_infer.py) and gains nothing from
# multi-threaded BLAS, but each worker's per-core OpenBLAS/OMP arenas cost
# well over a GB of Windows commit — the binding limit on this machine. Must
# run at module scope and before numpy/torch are imported, because 'spawn'
# re-imports this file as __mp_main__ in every worker.
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.stream import load_index, load_session_events  # noqa: E402
from core.feature_tracker import FeatureTracker  # noqa: E402
from core.metrics import score_detectors  # noqa: E402
from core.paths import (ARTIFACTS, RESULTS, SESSIONS, SPLIT_FILE,  # noqa: E402
                        station_group)

NAMES = ["TraditionalAI", "RL", "AIAgent", "AgenticAI", "MultiAgent"]


def build_detectors():
    from models.traditional import TraditionalAI
    from models.rl_detector import RLDetector
    from models.ai_agent import AIAgent
    from models.agentic_ai import AgenticAI
    from models.multi_agent import MultiAgent
    return [TraditionalAI(), RLDetector(), AIAgent(), AgenticAI(),
            MultiAgent()]


def run_connector(metas):
    """Replay one connector's sessions in chronological order."""
    detectors = build_detectors()
    names = [d.name for d in detectors]
    records = []
    wall = {d: 0.0 for d in names}
    n_err = 0
    for meta in metas:
        events = load_session_events(meta["session_key"])
        tracker = FeatureTracker()
        for d in detectors:
            d.reset(meta["station"], meta["connector"])
        first_alert = {}
        for ev in events:
            fs = tracker.update(ev)
            for d in detectors:
                tA = time.perf_counter()
                try:
                    alerts = d.observe(ev, fs)
                except Exception as e:  # noqa: BLE001
                    alerts = []
                    n_err += 1
                    print(f"!! {d.name} error in {meta['session_key']}: {e}",
                          flush=True)
                wall[d.name] += time.perf_counter() - tA
                if alerts and d.name not in first_alert:
                    a = alerts[0]
                    first_alert[d.name] = {
                        "t": a.t, "confidence": a.confidence,
                        "reason": a.reason, "fault_guess": a.fault_guess}
        for d in detectors:
            d.end_session(meta["station"], meta["connector"])
        records.append({"session_key": meta["session_key"], "label": meta,
                        "alerts": first_alert})
    # n_err lets the parent refuse to BANK a connector whose detectors threw:
    # swallowing the exception keeps the replay going, but freezing a degraded
    # connector into a checkpoint would make a transient failure permanent and
    # invisible in the published numbers
    return records, wall, n_err


def commit_available():
    """Bytes of Windows commit still available (0 if unknown)."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExt", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.ullAvailPageFile)
    except Exception:  # noqa: BLE001
        return 0


# measured cost of one worker once BLAS threads are pinned to 1: numpy +
# torch + the joblib/torch artifacts each detector loads
WORKER_COMMIT_B = 1_400_000_000


def fit_workers(requested):
    """Never ask for more workers than the commit budget can start.

    A pool that cannot allocate dies partway through, taking a multi-hour
    replay with it; running fewer workers only costs wall time.
    """
    avail = commit_available()
    if not avail:
        return requested
    room = max(1, int(avail * 0.6 // WORKER_COMMIT_B))
    if room < requested:
        print(f"commit available {avail/1e9:.1f} GB -> capping workers "
              f"{requested} -> {room}", flush=True)
    return min(requested, room)


def _source_digest():
    """Content hash of every module that decides what a record says.

    Weights alone do not determine a record: the rule layers, the feature
    tracker and the detectors themselves are plain source, and editing any of
    them changes which sessions alert without touching a single .pt file. A
    fingerprint that ignored them would let a resume splice records made by two
    different versions of the code into one file, under a banner reading
    "resuming: N of 90 connectors already banked". Hash bytes rather than
    mtimes so that copying or re-checking-out the tree still resumes.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    h = hashlib.sha1()
    for sub in ("core", "models"):
        d = os.path.join(root, sub)
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".py"):
                with open(os.path.join(d, fn), "rb") as fh:
                    h.update(f"{sub}/{fn}|".encode())
                    h.update(hashlib.sha1(fh.read()).digest())
    with open(os.path.abspath(__file__), "rb") as fh:
        h.update(hashlib.sha1(fh.read()).digest())
    return h.hexdigest()


def _fingerprint(split, metas):
    """Identity of the run a checkpoint shard belongs to.

    A shard may only be reused by a run that would have produced exactly the
    same bytes, so this covers everything a record depends on: the replay code
    itself, which sessions and their full label metadata, the arm switches, the
    session index, and every weight file. Change any of them and the old shards
    simply stop matching — silently resuming onto stale records is the one
    failure this whole layer must not have.
    """
    h = hashlib.sha1()
    h.update(f"v2|{split}|{len(metas)}".encode())
    h.update(_source_digest().encode())
    for m in metas:
        # the whole meta, not a chosen field or two: main() stores it verbatim
        # as the record's "label" and core/metrics.py reads it back
        h.update(json.dumps(m, sort_keys=True, default=float).encode())
    for k in ("EV_AI_ISO", "EV_AI_ISO_VEC", "EV_AI_SLAC", "EV_AI_SLAC_WAIT",
              "EV_AI_SLAC_RULE_MODE", "EV_AI_SESSIONS", "EV_AI_INDEX",
              "EV_AI_CLEAN_SAMPLE"):
        h.update(f"{k}={os.environ.get(k, '')}".encode())
    # the session CSVs are the actual input; sessionize.py rewrites index.json
    # whenever it regenerates them, so the index's stamp stands in for 40k files
    idx = os.path.join(SESSIONS, os.environ.get("EV_AI_INDEX", "index.json"))
    try:
        h.update(f"idx|{os.path.getmtime(idx):.0f}|"
                 f"{os.path.getsize(idx)}".encode())
    except OSError:
        pass
    try:
        for fn in sorted(os.listdir(ARTIFACTS)):
            p = os.path.join(ARTIFACTS, fn)
            h.update(f"{fn}|{os.path.getmtime(p):.0f}|"
                     f"{os.path.getsize(p)}".encode())
    except OSError:
        pass
    return h.hexdigest()[:16]


def _shard_path(d, key):
    return os.path.join(d, hashlib.sha1("|".join(key).encode())
                        .hexdigest()[:16] + ".json")


def _ckpt_load(tag, split, metas):
    """Per-connector checkpointing, enabled with EV_AI_CKPT=<dir>.

    A full-fleet replay is ~6 h and a single worker dying takes the whole pool
    with it (BrokenProcessPool), so without this one lost worker costs the
    entire run — which is exactly what happened on 2026-09-16. Connectors are
    independent by construction (AgenticAI's memory is keyed per
    station/connector), so each one's records can be banked the moment it
    lands and replayed from disk on the next attempt.

    Returns ((dir, fingerprint) | None, {key: shard}).
    """
    root = os.environ.get("EV_AI_CKPT")
    if not root:
        return None, {}
    fp = _fingerprint(split, metas)
    # the fingerprint is part of the PATH, not just the contents: arms share a
    # split, so without it every arm writes the same 90 filenames and each run
    # destroys the previous one's bank while refusing (correctly) to read it
    d = os.path.join(root, tag, fp)
    os.makedirs(d, exist_ok=True)
    done = {}
    for fn in os.listdir(d):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as fh:
                sh = json.load(fh)
        except (OSError, ValueError):
            continue                      # half-written when the pool died
        if sh.get("fp") == fp:
            done[tuple(sh["key"])] = sh
    return (d, fp), done


def _ckpt_save(ck, key, recs, wall):
    d, fp = ck
    p = _shard_path(d, key)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"fp": fp, "key": list(key), "records": recs, "wall": wall},
                  fh, default=float, ensure_ascii=False)
    os.replace(tmp, p)                    # atomic: never leave a torn shard


def select(index, split):
    """'test' | 'train' | 'all' | a source group ('main','v2g2024','v2g2025')
    | a comma-separated list of station-key substrings."""
    if split == "all":
        return list(index)
    if split in ("test", "train"):
        with open(SPLIT_FILE, encoding="utf-8") as fh:
            test = set(json.load(fh)["test"])
        return [m for m in index if (m["station"] in test) == (split == "test")]
    if split in ("main", "v2g2024", "v2g2025"):
        return [m for m in index if station_group(m["station"]) == split]
    subs = [p.strip() for p in split.split(",") if p.strip()]
    return [m for m in index if any(s in m["station"] for s in subs)]


def clean_sample(metas, n_clean, seed=20260909):
    """Every faulty session, plus a fixed random n_clean of the clean ones."""
    import random
    faulty = [m for m in metas if m["faults"]]
    clean = [m for m in metas if not m["faults"]]
    if n_clean >= len(clean):
        return metas
    keep = {m["session_key"]
            for m in random.Random(seed).sample(clean, n_clean)}
    kept = [m for m in metas if m["faults"] or m["session_key"] in keep]
    print(f"clean sample: {len(faulty)} faulty + {n_clean} of {len(clean)} "
          f"clean = {len(kept)} sessions (seed {seed})", flush=True)
    return kept


def main(split="test", limit=None, workers=10):
    os.makedirs(RESULTS, exist_ok=True)
    index = load_index()
    metas = select(index, split)
    n_clean = int(os.environ.get("EV_AI_CLEAN_SAMPLE", "0") or 0)
    if n_clean:
        metas = clean_sample(metas, n_clean)
    if not metas:
        # a typo'd split, or an index.json still being written by sessionize,
        # would otherwise yield a complete but entirely fictitious leaderboard
        stations = sorted({m["station"] for m in index})
        raise SystemExit(
            f"split {split!r} matched 0 of {len(index)} sessions; index.json "
            f"holds {len(stations)} stations. Refusing to write an empty "
            "leaderboard — has sessionize.py / make_split.py run?")
    metas.sort(key=lambda m: (m["station"], m["connector"], m["t_start"]))
    if limit:
        metas = metas[:limit]
    groups = {}
    for m in metas:
        groups.setdefault((m["station"], m["connector"]), []).append(m)
    workers = fit_workers(workers)
    print(f"{len(metas)} sessions across {len(groups)} connectors, "
          f"{workers} workers", flush=True)

    tag = split.replace(",", "+")
    if n_clean:
        # a sampled run must not overwrite a full one — the two are not
        # interchangeable and comparing across them would be wrong
        tag = f"{tag}_s{n_clean}"
    if limit:
        tag = f"{tag}_smoke{limit}"

    ck, banked = _ckpt_load(tag, split, metas)
    records = []
    wall = {d: 0.0 for d in NAMES}
    for sh in banked.values():
        records.extend(sh["records"])
        for k, v in sh["wall"].items():
            wall[k] = wall.get(k, 0.0) + v
    t0 = time.time()
    # biggest connectors first so the pool tail is short
    order = [(key, g) for key, g in sorted(groups.items(),
                                           key=lambda kv: -len(kv[1]))
             if key not in banked]
    if banked:
        print(f"resuming: {len(banked)} of {len(groups)} connectors already "
              f"banked ({len(records)} sessions), {len(order)} to go",
              flush=True)
    failed, degraded = [], []
    with cf.ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_connector, g): key for key, g in order}
        done = len(banked)
        for fut in cf.as_completed(futs):
            key = futs[fut]
            try:
                recs, w, n_err = fut.result()
            except Exception as e:  # noqa: BLE001
                # keep draining: one deterministically broken connector must
                # not cost the other 89, and a BrokenProcessPool here would
                # otherwise discard every future still in flight
                failed.append((key, repr(e)))
                print(f"!! connector {key} failed: {e!r}", flush=True)
                continue
            records.extend(recs)
            for k, v in w.items():
                wall[k] += v
            if n_err:
                degraded.append((key, n_err))
            if ck and not n_err:
                try:
                    _ckpt_save(ck, key, recs, w)
                except OSError as e:
                    # a failed bank costs one connector's replay next time; it
                    # must never take down the run the bank exists to protect
                    print(f"!! checkpoint write failed for {key}: {e}",
                          flush=True)
            done += 1
            if done % 10 == 0 or done == len(groups):
                print(f"[{done}/{len(groups)}] {len(records)} sessions "
                      f"({(time.time()-t0)/60:.1f} min)", flush=True)
    if degraded:
        print(f"!! {len(degraded)} connectors had detector errors and were "
              f"NOT banked: {degraded[:5]}", flush=True)
    if failed:
        # scoring a partial replay would produce a complete-looking leaderboard
        # built on missing sessions
        raise SystemExit(f"{len(failed)} of {len(groups)} connectors failed "
                         f"— refusing to score a partial replay: {failed[:5]}")
    records.sort(key=lambda r: r["session_key"])

    result = score_detectors(records, NAMES)
    result["wall_seconds"] = {k: round(v, 1) for k, v in wall.items()}
    result["split"] = split
    with open(os.path.join(RESULTS, f"records_{tag}.json"), "w",
              encoding="utf-8") as fh:
        json.dump(records, fh, default=float, ensure_ascii=False)
    with open(os.path.join(RESULTS, f"leaderboard_{tag}.json"), "w",
              encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, default=float, ensure_ascii=False)

    print(json.dumps({k: {kk: (round(vv, 3) if isinstance(vv, float) else vv)
                          for kk, vv in v.items() if kk != "by_family"}
                      for k, v in result["detectors"].items()}, indent=1))
    print(f"n_faulty={result['n_faulty']} n_clean={result['n_clean']}  "
          f"({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    # usage: run_competition.py [split] [limit|0] [workers]
    main(sys.argv[1] if len(sys.argv) > 1 else "test",
         int(sys.argv[2]) if len(sys.argv) > 2 else None,
         int(sys.argv[3]) if len(sys.argv) > 3 else 10)
