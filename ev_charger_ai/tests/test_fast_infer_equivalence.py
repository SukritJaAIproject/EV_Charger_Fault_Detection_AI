"""The vectorised traversals must agree with the per-tree loops they replaced.

Three arms of a published experiment are compared to each other through these
outputs, so "close enough" is not the bar: the assertion is bit-identity on real
feature vectors, not on synthetic noise. Sequential accumulation (cumsum, not
sum) is what makes that achievable — see the comments in models/fast_infer.py.

    python tests/test_fast_infer_equivalence.py            # baseline artifacts
    python tests/test_fast_infer_equivalence.py iso        # 60-feature arm
"""
import os
import sys
import time

import joblib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ARMS = {
    "baseline": (r"F:\pcap_downloads\ev_charger_ai\artifacts_baseline",
                 r"F:\pcap_downloads\ev_charger_ai\data", 33),
    "iso": (r"C:\ev_iso\artifacts", r"C:\ev_iso\data", 60),
}


def real_vectors(data_dir, n):
    """Rows the models actually see, not synthetic noise: the distribution is
    what decides whether a sample can land on a knife-edge threshold."""
    X = np.load(os.path.join(data_dir, "test_X.npy"), mmap_mode="r")
    v2g = np.load(os.path.join(data_dir, "test_v2g.npy"), mmap_mode="r")
    idx = np.flatnonzero(np.asarray(v2g[:4_000_000]) == 1)
    rng = np.random.default_rng(7)
    take = np.sort(rng.choice(idx, size=min(n, len(idx)), replace=False))
    return np.asarray(X[take], dtype=np.float32)


def main(arm="baseline", n=4000):
    art, data, n_feat = ARMS[arm]
    bundle = joblib.load(os.path.join(art, "traditional.joblib"))
    from core.feature_tracker import FeatureState  # noqa: E402
    from models.fast_infer import FastIForest, FastXGB  # noqa: E402

    xs = real_vectors(data, n)
    print(f"arm={arm}  {xs.shape[0]} real v2g feature vectors, "
          f"{xs.shape[1]} wide (expected {n_feat})")
    assert xs.shape[1] == n_feat, (
        f"{data} holds {xs.shape[1]}-wide vectors but arm {arm} expects "
        f"{n_feat} — is EV_AI_ISO set correctly?")

    iso_f = FastIForest(bundle["iforest"])
    xgb = FastXGB(bundle["xgb"], xs.shape[1])
    print(f"  iforest {len(iso_f.trees)} trees, depth<={iso_f._maxdepth}; "
          f"xgb {len(xgb.trees)} trees, depth<={xgb._maxdepth}")

    # --- bit-identity -------------------------------------------------
    bad_x = bad_i = 0
    worst_x = worst_i = 0.0
    for x in xs:
        a, b = xgb.margin_ref(x), xgb._margin(x)
        if a != b:
            bad_x += 1
            worst_x = max(worst_x, abs(a - b))
        c, d = iso_f.score_ref(x), iso_f.score(x)
        if c != d:
            bad_i += 1
            worst_i = max(worst_i, abs(c - d))
    print(f"  xgb margin   : {bad_x}/{len(xs)} differ (worst {worst_x:.3g})")
    print(f"  iforest score: {bad_i}/{len(xs)} differ (worst {worst_i:.3g})")

    # --- would any DECISION have changed? -----------------------------
    xt, it = bundle["xgb_thresh"], bundle["if_thresh"]
    pr_ref = np.array([1.0 / (1.0 + np.exp(-(xgb.margin_ref(x) + xgb.offset)))
                       for x in xs])
    pr_new = np.array([xgb.predict_proba1(x) for x in xs])
    sc_ref = np.array([iso_f.score_ref(x) for x in xs])
    sc_new = np.array([iso_f.score(x) for x in xs])
    flips_x = int(((pr_ref > xt) != (pr_new > xt)).sum())
    flips_i = int(((sc_ref > it) != (sc_new > it)).sum())
    print(f"  alert flips  : xgb {flips_x}, iforest {flips_i} "
          f"(thresholds {xt:.3f} / {it:.3f})")

    # --- the depth bound must be TIGHT, not merely large enough -------
    # One iteration short is silent: the cursor parks on an internal node and
    # the code reads that node's padded slot. For xgb that slot is 0.0 (split
    # nodes never get a leaf value), for iforest it is a larger path length, so
    # neither raises — the scores just quietly move. Assert both that every
    # cursor lands on a leaf, and that one fewer iteration would change the
    # answer, since a bound nobody can exercise is a bound nobody is testing.
    import numpy as _np

    def _lands_on_leaves(engine, table, x):
        ix = engine._ix
        node = _np.zeros(len(engine.trees), dtype=_np.int64)
        for _ in range(engine._maxdepth):
            col = table[ix, node]
            active = col != -1
            if not active.any():
                break
            if engine is xgb:
                go = x[col] < engine._T[ix, node]
                nxt = _np.where(go, engine._Y[ix, node], engine._N[ix, node])
            else:
                go = x[engine._F[ix, node]] <= engine._T[ix, node]
                nxt = _np.where(go, col, engine._R[ix, node])
            node = _np.where(active, nxt, node)
        return bool((table[ix, node] == -1).all())

    probe = xs[:300]
    leaf_x = all(_lands_on_leaves(xgb, xgb._F, x) for x in probe)
    leaf_i = all(_lands_on_leaves(iso_f, iso_f._L, x) for x in probe)
    saved = xgb._maxdepth, iso_f._maxdepth
    xgb._maxdepth -= 1
    iso_f._maxdepth -= 1
    short_x = sum(1 for x in probe[:120] if xgb.margin_ref(x) != xgb._margin(x))
    short_i = sum(1 for x in probe[:120] if iso_f.score_ref(x) != iso_f.score(x))
    xgb._maxdepth, iso_f._maxdepth = saved
    print(f"  depth bound   : xgb={saved[0]} iforest={saved[1]}; "
          f"all cursors on leaves {leaf_x}/{leaf_i}; "
          f"one short breaks {short_x}/120 and {short_i}/120")

    # --- does this sample actually exercise the split operator? -------
    # xgboost splits on "<" and sklearn on "<=", and the difference only shows
    # at an exact tie. The iforest side has no ties at all (its thresholds are
    # midpoints between observed values), so an iforest-only test can never
    # catch a flipped operator. Prove the xgb sample does contain ties.
    ties = 0
    for x in probe[:120]:
        ties += int((x[xgb._F.ravel()[xgb._F.ravel() != -1]]
                     == xgb._T.ravel()[xgb._F.ravel() != -1]).sum())
    print(f"  operator cover: {ties} exact x==threshold ties across 120 vectors "
          f"({'protects <' if ties else 'NO TIES — test cannot see a flipped operator'})")

    # --- speed --------------------------------------------------------
    sub = xs[:400]
    t0 = time.perf_counter()
    for x in sub:
        xgb.margin_ref(x)
    ref_x = (time.perf_counter() - t0) / len(sub)
    t0 = time.perf_counter()
    for x in sub:
        xgb._margin(x)
    new_x = (time.perf_counter() - t0) / len(sub)
    t0 = time.perf_counter()
    for x in sub:
        iso_f.score_ref(x)
    ref_i = (time.perf_counter() - t0) / len(sub)
    t0 = time.perf_counter()
    for x in sub:
        iso_f.score(x)
    new_i = (time.perf_counter() - t0) / len(sub)
    print(f"  xgb margin   : {ref_x*1e6:8.1f} us -> {new_x*1e6:8.1f} us "
          f"({ref_x/new_x:5.1f}x)")
    print(f"  iforest score: {ref_i*1e6:8.1f} us -> {new_i*1e6:8.1f} us "
          f"({ref_i/new_i:5.1f}x)")

    ok = (bad_x == 0 and bad_i == 0 and flips_x == 0 and flips_i == 0
          and leaf_x and leaf_i and short_x > 0 and short_i > 0 and ties > 0)
    print("  RESULT:", "bit-identical" if ok else "!! DIVERGENCE !!")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "baseline",
                  int(sys.argv[2]) if len(sys.argv) > 2 else 4000))
