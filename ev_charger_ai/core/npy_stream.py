"""Append-as-you-go .npy writing, and memmap loading of step arrays.

The full training matrix is ~6 GB. Holding it in RAM needs that much Windows
*commit* (pagefile-backed private memory), which this shared machine does not
always have spare even with tens of GB of physical RAM free. Writing straight
to a .npy and reading it back memory-mapped keeps private commit near zero:
the pages are file-backed.

A .npy file is just a fixed-size header followed by raw C-contiguous data, so
the row count can be patched in after the fact — no temp copy, no second pass.
"""
import os

import numpy as np

HEADER_TOTAL = 128        # magic(6) + ver(2) + len(2) + 118-byte header string
_MAGIC = b"\x93NUMPY\x01\x00"


def _header_bytes(dtype, shape):
    d = (f"{{'descr': '{np.lib.format.dtype_to_descr(dtype)}', "
         f"'fortran_order': False, 'shape': {shape}, }}")
    pad = HEADER_TOTAL - 10 - len(d) - 1
    if pad < 0:
        raise ValueError("header does not fit in the reserved block")
    body = (d + " " * pad + "\n").encode("latin1")
    return _MAGIC + len(body).to_bytes(2, "little") + body


class NpyAppender:
    """Write rows to a .npy incrementally; the shape is patched on close()."""

    def __init__(self, path, dtype, ncols=None):
        self.path = path
        self.dtype = np.dtype(dtype)
        self.ncols = ncols
        self.n = 0
        self.fh = open(path, "wb")
        self.fh.write(b"\0" * HEADER_TOTAL)      # reserve; rewritten on close

    def append(self, arr):
        arr = np.ascontiguousarray(arr, dtype=self.dtype)
        if self.ncols is not None:
            arr = arr.reshape(-1, self.ncols)
            self.n += arr.shape[0]
        else:
            arr = arr.reshape(-1)
            self.n += arr.shape[0]
        if arr.size:
            self.fh.write(arr.tobytes())

    def close(self):
        shape = (self.n, self.ncols) if self.ncols is not None else (self.n,)
        self.fh.flush()
        self.fh.seek(0)
        self.fh.write(_header_bytes(self.dtype, shape))
        self.fh.close()
        return shape


def steps_path(data_dir, split, name):
    return os.path.join(data_dir, f"{split}_{name}.npy")


def load_steps(data_dir, split, mmap=True):
    """-> dict with X, t, v2g, sid — all memory-mapped by default.

    At full-fleet scale even the 1-D arrays are GBs (t alone is 8 B/row), so
    nothing is materialised here; callers slice what they need.
    """
    mode = "r" if mmap else None
    return {name: np.load(steps_path(data_dir, split, name), mmap_mode=mode)
            for name in ("X", "t", "v2g", "sid")}


def session_spans(sid):
    """Contiguous [lo, hi) row ranges per session, in file order.

    Rows are written in sid order, so a session is one block. Works on a
    memmap; only the sid array is read.
    """
    sid = np.asarray(sid)
    if len(sid) == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64)
    bounds = np.flatnonzero(np.diff(sid) != 0) + 1
    los = np.concatenate([[0], bounds])
    his = np.concatenate([bounds, [len(sid)]])
    return sid[los].astype(np.int64), los, his
