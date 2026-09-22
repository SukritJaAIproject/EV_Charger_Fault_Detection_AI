"""Stage only a split's sessions onto a fast disk.

The fleet's sessions total 92 GB on a USB HDD; a replay of the held-out split
reads roughly a fifth of that, and reads it once. Copying just those files to
the NVMe turns a disk-bound replay into a CPU-bound one (measured 28x on the
37-station set). Refuses to start if the subset would not leave 5 GB free.

    python train/stage_heldout.py <src_sessions> <dst_sessions> <split.json> [test|train]
"""
import json
import os
import shutil
import sys
import time


def main(src, dst, split_file, which="test"):
    with open(split_file, encoding="utf-8") as fh:
        stations = set(json.load(fh)[which])
    with open(os.path.join(src, "index.json"), encoding="utf-8") as fh:
        index = json.load(fh)
    keep = [m for m in index if m["station"] in stations]
    paths = [(os.path.join(src, m["session_key"] + ".csv"),
              os.path.join(dst, m["session_key"] + ".csv")) for m in keep]

    t0 = time.time()
    total = sum(os.path.getsize(s) for s, _ in paths if os.path.exists(s))
    free = shutil.disk_usage(os.path.splitdrive(dst)[0] + os.sep).free
    print(f"{which}: {len(keep)} of {len(index)} sessions, "
          f"{total/1e9:.1f} GB; destination has {free/1e9:.1f} GB free "
          f"(sized in {time.time()-t0:.0f}s)", flush=True)
    if total > free - 5e9:
        raise SystemExit("would not leave 5 GB free — not staging")

    os.makedirs(dst, exist_ok=True)
    # the replay needs the index too (it selects sessions from it)
    shutil.copyfile(os.path.join(src, "index.json"), os.path.join(dst, "index.json"))
    done = skipped = 0
    t0 = time.time()
    for i, (s, d) in enumerate(paths, 1):
        if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s):
            skipped += 1
            continue
        shutil.copyfile(s, d)
        done += 1
        if i % 1000 == 0:
            print(f"  {i}/{len(paths)} ({(time.time()-t0)/60:.1f} min)", flush=True)
    print(f"staged {done} files ({skipped} already present) into {dst} "
          f"in {(time.time()-t0)/60:.1f} min", flush=True)

    # prove the staged index is byte-identical to the source
    with open(os.path.join(dst, "index.json"), encoding="utf-8") as fh:
        same = json.load(fh) == index
    missing = [d for _, d in paths if not os.path.exists(d)]
    print(f"index identical: {same}; missing after copy: {len(missing)}")
    if not same or missing:
        raise SystemExit("staging incomplete")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3],
         sys.argv[4] if len(sys.argv) > 4 else "test")
