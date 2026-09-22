"""Train the RL competitor with fitted Q-iteration (Double DQN style) on GPU.

The environment is policy-independent given logged sessions: WAIT moves to
the next logged state; ALERT terminates with a reward computable from the
label. So the full transition set is enumerable — no exploration needed.

  r(ALERT | faulty, t<=t_f+10) = +1 + min(max(t_f - t, 0), 120)/120
  r(ALERT | faulty, t> t_f+10) = +0.2
  r(ALERT | clean)             = -1.5
  r(end   | faulty, no alert)  = -1
  r(end   | clean,  no alert)  = +0.3

Memory: at full-fleet scale there are ~350 M steps, so nothing per-row is
materialised. X/t/sid stay memory-mapped and every per-row quantity (session
start, next row, rewards, done) is derived per batch from ~45 k per-session
values. Stacked states are gathered per batch.

After training, an alert margin is calibrated on TRAIN clean sessions to
bound the false-alarm rate (~6 %).
"""
import json
import os
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.rl_detector import QNet, STACK, N_STATE  # noqa: E402
from core.npy_stream import load_steps, session_spans  # noqa: E402
from core.paths import DATA_ROOT as DATA, ARTIFACTS as ART  # noqa: E402

DEV = "cuda" if torch.cuda.is_available() else "cpu"
GAMMA = 0.997
LEAD_CAP = 120.0
LATE_GRACE = 10.0
FAR_TARGET = 0.06
ITERS = 6000
BATCH = 4096
# X is a ~50 GB memmap on a USB hard disk. Drawing BATCH independent random
# rows would be BATCH random page-ins per step (~25 M seeks over training);
# sampling contiguous runs keeps the same coverage at ~BATCH/RUN seeks.
RUN = 32


class Transitions:
    """Per-batch transition construction from memmapped arrays."""

    def __init__(self):
        z = load_steps(DATA, "train")
        self.X, self.t, self.sid = z["X"], z["t"], z["sid"]
        with open(os.path.join(DATA, "train_sessions.json"),
                  encoding="utf-8") as fh:
            sessions = json.load(fh)
        n_sess = max(m["sid"] for m in sessions) + 1
        self.faulty = np.zeros(n_sess, dtype=bool)
        self.t_fault = np.full(n_sess, np.nan)
        for m in sessions:
            self.faulty[m["sid"]] = m["faulty"]
            if m["t_fault"] is not None:
                self.t_fault[m["sid"]] = m["t_fault"]
        sids, los, his = session_spans(self.sid)
        # per-session row range, indexed by sid
        self.lo = np.zeros(n_sess, dtype=np.int64)
        self.hi = np.zeros(n_sess, dtype=np.int64)
        self.lo[sids] = los
        self.hi[sids] = his
        # sample only from sessions with >= 2 rows
        ok = (his - los) >= 2
        self.valid_sids = sids[ok]
        self.valid_lo = los[ok]
        self.valid_len = (his - los)[ok]
        self.n_rows = int(self.valid_len.sum())
        self.cum = np.concatenate([[0], np.cumsum(self.valid_len)])
        self.sessions = sessions

    def sample_rows(self, rng, batch):
        """Contiguous runs of rows, uniform over all rows of valid sessions.

        Each run starts at a uniformly drawn row and walks forward, clipped
        to that row's own session so every index stays inside [lo, hi) — the
        reward/next-state logic in batch() is unaffected.
        """
        n_starts = max(1, batch // RUN)
        u = rng.integers(0, self.n_rows, n_starts)
        k = np.searchsorted(self.cum, u, side="right") - 1
        lo = self.valid_lo[k]
        end = lo + self.valid_len[k] - 1                    # last row of it
        anchor = lo + (u - self.cum[k])
        # Let the run begin anywhere in the RUN rows *before* its uniformly
        # drawn anchor, then clip to the session. Every row is then covered
        # by the same number of starts — sliding overrunning runs backwards
        # instead would starve the first RUN rows of each session, exactly
        # where SLAC and handshake faults live.
        start = anchor - rng.integers(0, RUN, n_starts)
        off = np.arange(RUN, dtype=np.int64)
        idx = start[:, None] + off[None, :]
        idx = np.clip(idx, lo[:, None], end[:, None])
        return idx.reshape(-1)[:batch]

    def stack(self, idx):
        """[len(idx), STACK*F] states, frames clamped to session start."""
        s = np.asarray(self.sid[idx])
        start = self.lo[s]
        cols = []
        for k in range(STACK):
            shift = STACK - 1 - k
            cols.append(np.asarray(self.X[np.maximum(idx - shift, start)],
                                   dtype=np.float32))
        return np.concatenate(cols, axis=1)

    def batch(self, idx):
        s = np.asarray(self.sid[idx])
        last = idx == (self.hi[s] - 1)
        nidx = np.where(last, idx, idx + 1)
        ts = np.asarray(self.t[idx])
        tf = self.t_fault[s]
        f = self.faulty[s]
        with np.errstate(invalid="ignore"):
            early = 1.0 + np.minimum(np.maximum(tf - ts, 0.0), LEAD_CAP) / LEAD_CAP
            r_alert = np.where(f, np.where(ts <= tf + LATE_GRACE, early, 0.2),
                               -1.5).astype(np.float32)
        r_wait = np.where(last, np.where(f, -1.0, 0.3), 0.0).astype(np.float32)
        done = last.astype(np.float32)
        return self.stack(idx), self.stack(nidx), r_alert, r_wait, done


def main():
    os.makedirs(ART, exist_ok=True)
    tr = Transitions()
    print(f"transitions: {tr.n_rows} rows over {len(tr.valid_sids)} sessions  "
          f"device {DEV}", flush=True)

    q = QNet().to(DEV)
    tgt = QNet().to(DEV)
    tgt.load_state_dict(q.state_dict())
    opt = torch.optim.Adam(q.parameters(), lr=3e-4)
    rng = np.random.default_rng(0)
    t0 = time.time()
    for it in range(ITERS):
        idx = tr.sample_rows(rng, BATCH)
        s, ns, r_a, r_w, d = tr.batch(idx)
        s = torch.from_numpy(s).to(DEV)
        ns = torch.from_numpy(ns).to(DEV)
        r_a = torch.from_numpy(r_a).to(DEV)
        r_w = torch.from_numpy(r_w).to(DEV)
        d = torch.from_numpy(d).to(DEV)
        with torch.no_grad():
            na = q(ns).argmax(dim=1, keepdim=True)          # double DQN
            nq = tgt(ns).gather(1, na).squeeze(1)
            y_wait = r_w + GAMMA * nq * (1 - d)
            y_alert = r_a
        qs = q(s)
        loss = ((qs[:, 0] - y_wait) ** 2 + (qs[:, 1] - y_alert) ** 2).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        if it % 200 == 0:
            tgt.load_state_dict(q.state_dict())
        if it % 1000 == 0:
            print(f"iter {it} loss {loss.item():.4f} "
                  f"({time.time()-t0:.0f}s)", flush=True)

    # margin calibration on clean train sessions (one session at a time)
    q.eval()
    margins = []
    with torch.no_grad():
        for s_id, lo, ln in zip(tr.valid_sids, tr.valid_lo, tr.valid_len):
            if tr.faulty[s_id]:
                continue
            idx = np.arange(lo, lo + ln)
            qv = q(torch.from_numpy(tr.stack(idx)).to(DEV))
            margins.append(float((qv[:, 1] - qv[:, 0]).max()))
    margin = float(np.quantile(margins, 1 - FAR_TARGET)) if margins else 0.0
    margin = max(margin, 0.0)
    print(f"calibrated margin: {margin:.3f} over {len(margins)} clean sessions",
          flush=True)
    torch.save({"state": q.state_dict(), "margin": margin},
               os.path.join(ART, "dqn.pt"))
    print("saved dqn.pt", flush=True)


if __name__ == "__main__":
    main()
