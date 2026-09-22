"""Build training arrays from sessionized data.

Replays every session of a split through the shared FeatureTracker (exactly
what detectors see at inference) and stores per-decision-step vectors:

  <split>_X.npy    [N,33] float32      <split>_t.npy    [N] float64
  <split>_v2g.npy  [N]    int8         <split>_sid.npy  [N] int32
  <split>_sessions.json                per-session metadata (sid order)

Decision steps = every event except hpav LINK_STATUS polling.

Rows are written in session (sid) order and the sid array is contiguous, which
train_rl.py and train_nn_tools.py rely on to find session blocks. The replay
is pure Python and dominates wall time (~1 M steps/min), so sessions are
split into contiguous sid ranges, each range is replayed by a worker into
part files, and the parts are streamed into the final .npy in order. Nothing
larger than one session is ever held in RAM.

Split membership comes from DATA_ROOT/split.json (train/make_split.py).
"""
import argparse
import concurrent.futures as cf
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.stream import load_index, load_session_events  # noqa: E402
from core.feature_tracker import FeatureTracker, FeatureState  # noqa: E402
from core.npy_stream import NpyAppender, steps_path  # noqa: E402
from core.paths import DATA_ROOT, SPLIT_FILE  # noqa: E402

DATA = DATA_ROOT
WORKERS = 12
ARRAYS = (("X", np.float32, FeatureState.N_FEATURES), ("t", np.float64, None),
          ("v2g", np.int8, None), ("sid", np.int32, None))


def is_decision(ev):
    return not (ev.kind == "hpav" and "LINK_STATUS" in ev.msg)


def load_split():
    with open(SPLIT_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def part_path(split, name, k):
    return steps_path(DATA, split, f"{name}.part{k:03d}")


def replay_chunk(args):
    """Worker: replay sessions [metas] (with their global sids) into part k."""
    split, k, metas = args
    wr = {n: NpyAppender(part_path(split, n, k), dt, nc)
          for n, dt, nc in ARRAYS}
    total = 0
    sess_meta = []
    for sid, meta in metas:
        events = load_session_events(meta["session_key"])
        tracker = FeatureTracker()
        rows, ts, v2g = [], [], []
        for ev in events:
            fs = tracker.update(ev)
            if not is_decision(ev):
                continue
            rows.append(fs.as_vector())
            ts.append(fs.t)
            v2g.append(1 if ev.kind == "v2g" else 0)
        n = len(rows)
        wr["X"].append(np.asarray(rows, dtype=np.float32).reshape(
            n, FeatureState.N_FEATURES))
        wr["t"].append(np.asarray(ts, dtype=np.float64))
        wr["v2g"].append(np.asarray(v2g, dtype=np.int8))
        wr["sid"].append(np.full(n, sid, dtype=np.int32))
        total += n
        del rows, ts, v2g, events
        faults = meta["faults"]
        sess_meta.append({
            "sid": sid, "session_key": meta["session_key"],
            "station": meta["station"], "group": meta.get("group", ""),
            "faulty": bool(faults),
            "t_fault": min(f[0] for f in faults) if faults else None,
            "t_start": meta["t_start"], "t_end": meta["t_end"],
            "n_steps": n,
        })
    for w in wr.values():
        w.close()
    return k, total, sess_meta


def merge_parts(split, n_parts):
    """Stream part files into the final arrays, in part order."""
    for name, dt, nc in ARRAYS:
        out = NpyAppender(steps_path(DATA, split, name), dt, nc)
        for k in range(n_parts):
            p = part_path(split, name, k)
            arr = np.load(p, mmap_mode="r")
            step = max(1, 2_000_000 // max(1, (nc or 1)))
            for i in range(0, len(arr), step):
                out.append(np.asarray(arr[i:i + step]))
            del arr
            os.remove(p)
        shape = out.close()
        print(f"  {split}_{name}.npy {shape}", flush=True)


def build(split, workers):
    index = load_index()
    sp = load_split()
    test = set(sp["test"])
    metas = [m for m in index if (m["station"] in test) == (split == "test")]
    metas.sort(key=lambda m: m["session_key"])
    numbered = list(enumerate(metas))            # global sid = position
    n_parts = min(workers * 3, max(1, len(numbered)))
    chunks = [(split, k, numbered[k::n_parts]) for k in range(n_parts)]
    # keep sid contiguous inside the final file: parts must hold contiguous
    # sid ranges, so slice by range rather than round-robin
    size = -(-len(numbered) // n_parts)
    chunks = [(split, k, numbered[k * size:(k + 1) * size])
              for k in range(n_parts)]
    chunks = [c for c in chunks if c[2]]

    print(f"{split}: {len(metas)} sessions -> {len(chunks)} parts, "
          f"{workers} workers", flush=True)
    t0 = time.time()
    all_meta = []
    total = 0
    with cf.ProcessPoolExecutor(max_workers=workers) as ex:
        for k, n, sm in ex.map(replay_chunk, chunks):
            all_meta.extend(sm)
            total += n
            print(f"  part {k+1}/{len(chunks)} done: {n} steps "
                  f"({(time.time()-t0)/60:.1f} min)", flush=True)
    all_meta.sort(key=lambda m: m["sid"])
    print(f"  merging {len(chunks)} parts ...", flush=True)
    merge_parts(split, len(chunks))
    with open(os.path.join(DATA, f"{split}_sessions.json"), "w",
              encoding="utf-8") as fh:
        json.dump(all_meta, fh, ensure_ascii=False)
    n_f = sum(1 for m in all_meta if m["faulty"])
    print(f"{split}: {len(all_meta)} sessions ({n_f} faulty), {total} steps "
          f"in {(time.time()-t0)/60:.1f} min", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--splits", default="train,test")
    a = ap.parse_args()
    for s in a.splits.split(","):
        build(s.strip(), a.workers)
