"""Slice the ISO arm's 60-column matrices down to the base 33.

The two arms were built from the same sessions in the same order by the same
feature code, and the ISO block is appended after the base features — verified:
iso_X[:, :33] equals baseline_X exactly. So the baseline arm's matrix can be
produced from the ISO one by a column slice, on the NVMe, instead of read off
the USB volume the original lives on. The point is purely to keep a retrain off
that disk; the bytes are identical either way.

    python train/narrow_matrix.py <src_data_root> <dst_data_root> [n_cols]
"""
import json
import os
import shutil
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.npy_stream import NpyAppender   # noqa: E402

CHUNK = 2_000_000


def main(src, dst, ncols=33):
    os.makedirs(dst, exist_ok=True)
    for split in ("train", "test"):
        sx = os.path.join(src, f"{split}_X.npy")
        if not os.path.exists(sx):
            print(f"{split}: absent in {src}, skipped")
            continue
        X = np.load(sx, mmap_mode="r")
        if X.shape[1] < ncols:
            raise SystemExit(f"{sx} has {X.shape[1]} columns, need >= {ncols}")
        t0 = time.time()
        out = os.path.join(dst, f"{split}_X.npy")
        w = NpyAppender(out, np.float32, ncols=ncols)
        for lo in range(0, X.shape[0], CHUNK):
            w.append(np.asarray(X[lo:lo + CHUNK, :ncols], dtype=np.float32))
        shape = w.close()
        for name in ("t", "v2g", "sid"):
            shutil.copyfile(os.path.join(src, f"{split}_{name}.npy"),
                            os.path.join(dst, f"{split}_{name}.npy"))
        shutil.copyfile(os.path.join(src, f"{split}_sessions.json"),
                        os.path.join(dst, f"{split}_sessions.json"))
        legacy = os.path.join(src, f"{split}_sessions.legacy.json")
        if os.path.exists(legacy):
            shutil.copyfile(legacy, os.path.join(
                dst, f"{split}_sessions.legacy.json"))
        print(f"{split}: {shape} written in {(time.time()-t0)/60:.1f} min")

        # cheap proof the slice is faithful, on rows spread across the file
        a = np.load(out, mmap_mode="r")
        g = np.linspace(0, a.shape[0] - 1, 5000).astype(np.int64)
        ok = np.array_equal(np.asarray(a[g]), np.asarray(X[g][:, :ncols]))
        print(f"   slice verified on 5000 spread rows: {ok}")
        if not ok:
            raise SystemExit("slice does not match source — refusing to continue")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2],
         int(sys.argv[3]) if len(sys.argv) > 3 else 33)
