"""Train TraditionalAI's ML layer: IsolationForest + XGBoost.

Labels: y=1 for steps within 60 s before (or after) the session's first fault.
Thresholds calibrated so that session-level false-alarm rate on TRAIN clean
sessions is ~5 % (per model layer).
"""
import json
import os
import sys

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from xgboost import XGBClassifier

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.npy_stream import load_steps  # noqa: E402

from core.paths import DATA_ROOT as DATA, ARTIFACTS as ART  # noqa: E402
HORIZON = 60.0
FAR_TARGET = 0.05


def main():
    os.makedirs(ART, exist_ok=True)
    # X stays memory-mapped; only the rows actually used are materialised,
    # so private commit never approaches the ~6 GB the full matrix would need
    st = load_steps(DATA, "train")
    X, t_all, sid_all, v2g = st["X"], st["t"], st["sid"], st["v2g"]
    # the ML layer only ever scores v2g rows at inference — train and
    # calibrate on exactly that population. Work through indices into the
    # memmap rather than a filtered copy.
    v2g_idx = np.flatnonzero(v2g == 1)
    t = t_all[v2g_idx]
    sid = sid_all[v2g_idx]
    del t_all, sid_all, v2g
    with open(os.path.join(DATA, "train_sessions.json")) as fh:
        sessions = json.load(fh)
    t_fault = np.full(len(sessions), np.nan)
    faulty = np.zeros(len(sessions), dtype=bool)
    for m in sessions:
        faulty[m["sid"]] = m["faulty"]
        if m["t_fault"] is not None:
            t_fault[m["sid"]] = m["t_fault"]
    y = np.zeros(len(v2g_idx), dtype=np.int8)
    tf = t_fault[sid]
    with np.errstate(invalid="ignore"):
        y[(~np.isnan(tf)) & (tf - t <= HORIZON)] = 1
    clean_mask = ~faulty[sid]

    print(f"steps {len(v2g_idx)}, positives {int(y.sum())}", flush=True)

    def rows(local_idx):
        """Materialise the given v2g-local rows from the memmap, in order."""
        g = np.sort(v2g_idx[local_idx])
        return np.asarray(X[g], dtype=np.float32)

    # Isolation Forest on clean steps (subsampled)
    rng = np.random.default_rng(0)
    idx = np.flatnonzero(clean_mask)
    idx = rng.choice(idx, size=min(400_000, len(idx)), replace=False)
    iforest = IsolationForest(n_estimators=200, max_samples=1024,
                              n_jobs=-1, random_state=0)
    iforest.fit(rows(idx))

    # XGBoost supervised risk
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    neg = rng.choice(neg, size=min(len(neg), 8 * max(len(pos), 1000)),
                     replace=False)
    tr = np.sort(np.concatenate([pos, neg]))
    xgb = XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
        tree_method="hist", device="cuda", n_jobs=-1, random_state=0)
    xgb.fit(rows(tr), y[tr])

    # calibrate: session-level max score on clean train sessions, sampled at
    # the same cadence the detector uses at inference (every 4th / 8th v2g).
    # Scored per session so only one session's rows are resident at a time.
    clean_sids = np.array([m["sid"] for m in sessions if not m["faulty"]])
    order = np.argsort(sid, kind="stable")
    starts = np.searchsorted(sid[order], clean_sids, side="left")
    ends = np.searchsorted(sid[order], clean_sids, side="right")
    xgb_max, if_max = [], []
    for lo, hi in zip(starts, ends):
        m = order[lo:hi]
        if len(m) >= 4:
            xb = rows(m[3::4])
            xgb_max.append(float(xgb.predict_proba(xb)[:, 1].max()))
        if len(m) >= 8:
            ib = rows(m[7::8])
            if_max.append(float((-iforest.score_samples(ib)).max()))
    xgb_thresh = float(np.quantile(xgb_max, 1 - FAR_TARGET))
    if_thresh = float(np.quantile(if_max, 1 - FAR_TARGET))
    print(f"xgb_thresh {xgb_thresh:.3f}  if_thresh {if_thresh:.3f}",
          flush=True)

    joblib.dump({"iforest": iforest, "xgb": xgb,
                 "xgb_thresh": xgb_thresh, "if_thresh": if_thresh},
                os.path.join(ART, "traditional.joblib"))
    print("saved traditional.joblib", flush=True)


if __name__ == "__main__":
    main()
