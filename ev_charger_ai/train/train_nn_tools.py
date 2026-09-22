"""Train the shared neural tools on the GPU (clean TRAIN sessions only).

  lstm_ae.pt   LSTM autoencoder over 32-step windows of v2g feature vectors
  gru_fore.pt  GRU forecaster of next (v_dev, i_dev) from 16-step windows
"""
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.nn_tools import LstmAE, GruForecaster, WIN, FORE_WIN  # noqa: E402
from core.feature_tracker import FeatureState  # noqa: E402
from core.npy_stream import load_steps  # noqa: E402

from core.paths import DATA_ROOT as DATA, ARTIFACTS as ART  # noqa: E402
DEV = "cuda" if torch.cuda.is_available() else "cpu"


def load_clean_v2g_sequences():
    z = load_steps(DATA, "train")
    X, sid, v2g = z["X"], z["sid"], z["v2g"]   # X is a memmap
    with open(os.path.join(DATA, "train_sessions.json")) as fh:
        sessions = json.load(fh)
    clean = {m["sid"] for m in sessions if not m["faulty"]}
    # Rows are stored in session order, so session spans are contiguous
    # blocks — one O(N) scan instead of a full mask per session.
    keep = v2g == 1
    bounds = np.flatnonzero(np.diff(sid) != 0) + 1
    los = np.r_[0, bounds]
    his = np.r_[bounds, len(sid)]
    # Visit sessions in a seeded shuffled order: windows() stops at its cap,
    # and in natural order that cap is reached inside the first station, so
    # the AE would learn one station's behaviour and call the rest anomalous.
    order = np.random.default_rng(0).permutation(len(los))
    seqs = []
    budget = 0
    for k in order:
        lo, hi = int(los[k]), int(his[k])
        if int(sid[lo]) not in clean:
            continue
        rows = np.asarray(X[lo:hi])[keep[lo:hi]]   # pull one session at a time
        if len(rows) < WIN:
            continue
        seqs.append(rows)
        budget += (len(rows) - WIN) // 8 + 1        # windows this seq yields
        if budget >= 3 * 200_000:                   # both consumers' caps
            break
    return seqs


def windows(seqs, win, stride, cap=200_000):
    out = []
    for seq in seqs:
        for i in range(0, len(seq) - win + 1, stride):
            out.append(seq[i:i + win])
            if len(out) >= cap:
                return np.asarray(out, dtype=np.float32)
    return np.asarray(out, dtype=np.float32)


def train_ae(seqs):
    W = windows(seqs, WIN, 8)
    print(f"AE windows: {W.shape}", flush=True)
    model = LstmAE(FeatureState.N_FEATURES).to(DEV)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    ds = torch.from_numpy(W)
    n = len(ds)
    t0 = time.time()
    for epoch in range(8):
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, 512):
            xb = ds[perm[i:i + 512]].to(DEV, non_blocking=True)
            rec = model(xb)
            loss = ((rec - xb) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss) * len(xb)
        print(f"AE epoch {epoch}: {tot/n:.5f} ({time.time()-t0:.0f}s)",
              flush=True)
    # error stats on clean windows
    model.eval()
    errs = []
    with torch.no_grad():
        for i in range(0, n, 1024):
            xb = ds[i:i + 1024].to(DEV)
            rec = model(xb)
            e = ((rec - xb) ** 2).mean(dim=(1, 2))
            errs.append(e.cpu().numpy())
    errs = np.concatenate(errs)
    torch.save({"state": model.state_dict(),
                "n_feat": FeatureState.N_FEATURES,
                "err_mean": float(errs.mean()),
                "err_std": float(errs.std() + 1e-9)},
               os.path.join(ART, "lstm_ae.pt"))
    print(f"AE err mean {errs.mean():.5f} std {errs.std():.5f}", flush=True)


def train_forecaster(seqs):
    from models.nn_tools import fore_slice
    ins, outs = [], []
    for seq in seqs:
        F = np.asarray([fore_slice(v) for v in seq], dtype=np.float32)
        tgt = seq[:, [6, 7]].astype(np.float32)  # v_dev, i_dev columns
        for i in range(0, len(seq) - FORE_WIN - 1, 4):
            ins.append(F[i:i + FORE_WIN])
            outs.append(tgt[i + FORE_WIN])
            if len(ins) >= 300_000:
                break
        if len(ins) >= 300_000:
            break
    Xw = torch.from_numpy(np.asarray(ins, dtype=np.float32))
    Yw = torch.from_numpy(np.asarray(outs, dtype=np.float32))
    print(f"forecaster windows: {Xw.shape}", flush=True)
    model = GruForecaster().to(DEV)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    n = len(Xw)
    for epoch in range(6):
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, 1024):
            b = perm[i:i + 1024]
            xb, yb = Xw[b].to(DEV), Yw[b].to(DEV)
            pred = model(xb)
            loss = ((pred - yb) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss) * len(b)
        print(f"FORE epoch {epoch}: {tot/n:.5f}", flush=True)
    model.eval()
    errs = []
    with torch.no_grad():
        for i in range(0, n, 2048):
            xb = Xw[i:i + 2048].to(DEV)
            pred = model(xb).cpu().numpy()
            errs.append(np.abs(pred - Yw[i:i + 2048].numpy()).mean(axis=1))
    errs = np.concatenate(errs)
    torch.save({"state": model.state_dict(),
                "err_mean": float(errs.mean()),
                "err_std": float(errs.std() + 1e-9)},
               os.path.join(ART, "gru_fore.pt"))
    print(f"FORE err mean {errs.mean():.4f} std {errs.std():.4f}", flush=True)


if __name__ == "__main__":
    os.makedirs(ART, exist_ok=True)
    print(f"device: {DEV}", flush=True)
    seqs = load_clean_v2g_sequences()
    print(f"clean sequences: {len(seqs)}", flush=True)
    train_ae(seqs)
    train_forecaster(seqs)
