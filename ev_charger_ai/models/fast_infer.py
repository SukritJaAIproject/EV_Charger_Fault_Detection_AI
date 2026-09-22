"""Pure-numpy streaming inference engines.

Batch-1 calls through sklearn/torch cost 2-65 ms in per-call overhead; these
reimplementations produce numerically equivalent outputs in tens of
microseconds, and shrink the production footprint (no torch/sklearn needed
at inference).

  FastIForest   sklearn IsolationForest.score_samples clone (tree traversal)
  NumpyMLP      QNet (Linear-ReLU-Linear-ReLU-Linear)
  NumpyLSTMAE   LstmAE reconstruction error
  NumpyGRU      GruForecaster next-step prediction
"""
import numpy as np


# --------------------------------------------------------------- iforest
def _avg_path_length(n):
    n = np.asarray(n, dtype=np.float64)
    out = np.zeros_like(n)
    m2 = n == 2
    big = n > 2
    out[m2] = 1.0
    nb = n[big]
    out[big] = 2.0 * (np.log(nb - 1.0) + np.euler_gamma) - 2.0 * (nb - 1.0) / nb
    return out


def _tree_depth(left, right):
    """Longest root-to-leaf path, in edges, of one child-array-encoded tree."""
    best = 0
    stack = [(0, 0)]
    while stack:
        node, d = stack.pop()
        if left[node] == -1:
            best = max(best, d)
            continue
        stack.append((left[node], d + 1))
        stack.append((right[node], d + 1))
    return best


def _pad_forest(per_tree, fill):
    """Stack ragged per-tree arrays into one [n_trees, max_nodes] block.

    A tree's cursor never leaves its own node range, so the padding is only
    there to make the rows the same length — its contents are never read.
    """
    n = max(len(a) for a in per_tree)
    out = np.full((len(per_tree), n), fill, dtype=per_tree[0].dtype)
    for i, a in enumerate(per_tree):
        out[i, :len(a)] = a
    return out


class FastIForest:
    """Precompiled traversal tables from a fitted sklearn IsolationForest.

    Traversal walks every tree at once: the cursor is a [n_trees] vector and the
    loop runs over DEPTH, not over trees, so 200 Python iterations per scored
    sample become ~11 numpy ops. The per-tree loop is kept below as
    ``score_ref`` — it is the definition this must agree with, and
    ``tests/test_fast_infer_equivalence.py`` asserts they do.
    """

    def __init__(self, iforest):
        self.trees = []
        for est, feats in zip(iforest.estimators_,
                              iforest.estimators_features_):
            t = est.tree_
            depth = np.zeros(t.node_count, dtype=np.float64)
            stack = [(0, 0.0)]
            while stack:
                node, d = stack.pop()
                depth[node] = d
                if t.children_left[node] != -1:
                    stack.append((t.children_left[node], d + 1.0))
                    stack.append((t.children_right[node], d + 1.0))
            leaf_adjust = _avg_path_length(
                np.maximum(t.n_node_samples, 2)) * (t.n_node_samples > 1)
            self.trees.append((
                t.children_left.copy(), t.children_right.copy(),
                t.feature.copy(), t.threshold.copy(),
                depth + leaf_adjust, np.asarray(feats)))
        self.c = _avg_path_length(
            np.array([iforest.max_samples_], dtype=np.float64))[0]

        # --- vectorised tables ------------------------------------------
        # sklearn marks a leaf with children_left == -1 and feature == -2
        # (TREE_UNDEFINED), so "is this a leaf" must be asked of the CHILD
        # array, never of the feature array. estimators_features_ is composed
        # into the feature index here so the hot loop has one gather, not two;
        # leaves get index 0, which the leaf mask discards.
        self._L = _pad_forest([t[0].astype(np.int64) for t in self.trees], -1)
        self._R = _pad_forest([t[1].astype(np.int64) for t in self.trees], -1)
        self._F = _pad_forest(
            [t[5][np.maximum(t[2], 0)].astype(np.int64) for t in self.trees], 0)
        self._T = _pad_forest([t[3].astype(np.float64) for t in self.trees], 0.0)
        self._P = _pad_forest([t[4].astype(np.float64) for t in self.trees], 0.0)
        self._ix = np.arange(len(self.trees), dtype=np.int64)
        # loop bound: the deepest root-to-leaf path in the forest. Derived, not
        # assumed from ceil(log2(max_samples)) — an early break makes an
        # over-estimate harmless but an under-estimate would silently stop a
        # traversal at an internal node.
        self._maxdepth = max(_tree_depth(t[0], t[1]) for t in self.trees)

    def score_ref(self, x):
        """Reference: the original per-tree Python loop."""
        total = 0.0
        for left, right, feat, thr, pathlen, feats in self.trees:
            node = 0
            while left[node] != -1:
                node = (left[node] if x[feats[feat[node]]] <= thr[node]
                        else right[node])
            total += pathlen[node]
        mean_path = total / len(self.trees)
        return float(2.0 ** (-mean_path / self.c))

    def score(self, x):
        """= -sklearn.score_samples(x)[0] (higher = more anomalous)."""
        ix, node = self._ix, np.zeros(len(self.trees), dtype=np.int64)
        for _ in range(self._maxdepth):
            left = self._L[ix, node]
            active = left != -1
            if not active.any():
                break
            # sklearn splits on "<=" and promotes the float32 sample against a
            # float64 threshold, exactly as the reference does
            go_left = x[self._F[ix, node]] <= self._T[ix, node]
            nxt = np.where(go_left, left, self._R[ix, node])
            node = np.where(active, nxt, node)
        # cumsum accumulates in tree order, matching the reference's sequential
        # "total += ..." bit for bit; np.sum would reassociate pairwise
        total = float(np.cumsum(self._P[ix, node])[-1])
        mean_path = total / len(self.trees)
        return float(2.0 ** (-mean_path / self.c))


# --------------------------------------------------------------- xgboost
class FastXGB:
    """Numpy traversal of a fitted xgboost binary:logistic booster.

    The probability-space offset is calibrated empirically against
    predict_proba on a handful of samples, so it is robust to how the
    installed xgboost version encodes base_score.
    """

    def __init__(self, sk_model, n_features):
        booster = sk_model.get_booster()
        df = booster.trees_to_dataframe()
        self.trees = []
        for tid, tdf in df.groupby("Tree"):
            tdf = tdf.set_index("Node").sort_index()
            n = len(tdf)
            feat = np.full(n, -1, dtype=np.int32)
            thr = np.zeros(n, dtype=np.float32)
            yes = np.zeros(n, dtype=np.int32)
            no = np.zeros(n, dtype=np.int32)
            leaf = np.zeros(n, dtype=np.float32)
            for node, row in tdf.iterrows():
                if row["Feature"] == "Leaf":
                    leaf[node] = row["Gain"]
                else:
                    feat[node] = int(row["Feature"][1:])
                    thr[node] = row["Split"]
                    yes[node] = int(row["Yes"].split("-")[1])
                    no[node] = int(row["No"].split("-")[1])
            self.trees.append((feat, thr, yes, no, leaf))
        # --- vectorised tables: walk all 300 trees at once, looping over
        # depth instead of over trees. Leaves keep feature -1, and a leaf's
        # cursor simply stops moving, so no tree can run past its own nodes.
        # Built BEFORE the offset calibration below, which scores through the
        # production path so the offset belongs to the code that will use it.
        self._F = _pad_forest([t[0].astype(np.int64) for t in self.trees], -1)
        self._T = _pad_forest([t[1] for t in self.trees], 0.0)
        self._Y = _pad_forest([t[2].astype(np.int64) for t in self.trees], 0)
        self._N = _pad_forest([t[3].astype(np.int64) for t in self.trees], 0)
        self._V = _pad_forest([t[4] for t in self.trees], 0.0)
        self._ix = np.arange(len(self.trees), dtype=np.int64)
        self._maxdepth = max(
            _tree_depth(np.where(f == -1, -1, y), np.where(f == -1, -1, n))
            for f, _t, y, n, _l in self.trees)

        # empirical margin offset (margin space — probability space loses
        # precision to float32 saturation on confident samples)
        import xgboost as _xgb
        rng = np.random.default_rng(0)
        xs = rng.standard_normal((8, n_features)).astype(np.float32)
        ref = booster.predict(_xgb.DMatrix(xs), output_margin=True)
        margins = np.array([self._margin(x) for x in xs])
        offs = ref - margins
        assert offs.std() < 1e-3, "non-constant offset — check encoding"
        self.offset = float(offs.mean())

    def margin_ref(self, x):
        """Reference: the original per-tree Python loop."""
        total = 0.0
        for feat, thr, yes, no, leaf in self.trees:
            node = 0
            while feat[node] != -1:
                node = yes[node] if x[feat[node]] < thr[node] else no[node]
            total += leaf[node]
        return total

    def _margin(self, x):
        ix, node = self._ix, np.zeros(len(self.trees), dtype=np.int64)
        for _ in range(self._maxdepth):
            feat = self._F[ix, node]
            active = feat != -1
            if not active.any():
                break
            # xgboost's split rule is "< threshold goes to Yes"; both sides are
            # float32 here, as in the reference
            go_yes = x[feat] < self._T[ix, node]
            nxt = np.where(go_yes, self._Y[ix, node], self._N[ix, node])
            node = np.where(active, nxt, node)
        # Sequential accumulation in tree order, bit-identical to the
        # reference's "total = 0.0; total += leaf[node]". Two things have to
        # match, not one: the ORDER (cumsum, never sum — sum reassociates
        # pairwise) and the DTYPE. Under NEP 50 a Python float is weak, so
        # `0.0 + np.float32` yields float32 and the reference accumulates the
        # whole forest in float32; promoting to float64 here is *more* accurate
        # and therefore wrong, drifting ~5e-6 off the published numbers.
        return float(np.cumsum(self._V[ix, node])[-1])

    def predict_proba1(self, x):
        m = float(self._margin(x)) + self.offset
        return float(1.0 / (1.0 + np.exp(-m)))


# --------------------------------------------------------------- MLP (QNet)
class NumpyMLP:
    def __init__(self, state_dict):
        self.layers = []
        i = 0
        while f"net.{i}.weight" in state_dict:
            W = state_dict[f"net.{i}.weight"].numpy().astype(np.float32)
            b = state_dict[f"net.{i}.bias"].numpy().astype(np.float32)
            self.layers.append((W, b))
            i += 2

    def forward(self, x):
        for k, (W, b) in enumerate(self.layers):
            x = W @ x + b
            if k < len(self.layers) - 1:
                x = np.maximum(x, 0.0)
        return x


# --------------------------------------------------------------- LSTM cell
def _lstm_seq(x, w_ih, w_hh, b, H):
    """Run an LSTM over x [T, in]; returns h_last and all h [T, H]."""
    T = x.shape[0]
    hs = np.empty((T, H), dtype=np.float32)
    h = np.zeros(H, dtype=np.float32)
    c = np.zeros(H, dtype=np.float32)
    xg = x @ w_ih.T + b            # [T, 4H] precomputed input contributions
    for t in range(T):
        g = xg[t] + w_hh @ h
        i = 1.0 / (1.0 + np.exp(-g[:H]))
        f = 1.0 / (1.0 + np.exp(-g[H:2 * H]))
        gg = np.tanh(g[2 * H:3 * H])
        o = 1.0 / (1.0 + np.exp(-g[3 * H:]))
        c = f * c + i * gg
        h = o * np.tanh(c)
        hs[t] = h
    return h, hs


class NumpyLSTMAE:
    def __init__(self, state_dict, n_feat, hidden=64, latent=16):
        sd = {k: v.numpy().astype(np.float32) for k, v in state_dict.items()}
        self.H = hidden
        self.enc_ih = sd["enc.weight_ih_l0"]
        self.enc_hh = sd["enc.weight_hh_l0"]
        self.enc_b = sd["enc.bias_ih_l0"] + sd["enc.bias_hh_l0"]
        self.tl_W, self.tl_b = sd["to_latent.weight"], sd["to_latent.bias"]
        self.fl_W, self.fl_b = sd["from_latent.weight"], sd["from_latent.bias"]
        self.dec_ih = sd["dec.weight_ih_l0"]
        self.dec_hh = sd["dec.weight_hh_l0"]
        self.dec_b = sd["dec.bias_ih_l0"] + sd["dec.bias_hh_l0"]
        self.out_W, self.out_b = sd["out.weight"], sd["out.bias"]

    def recon_error(self, x):
        """x [T, n_feat] -> mean squared reconstruction error (scalar)."""
        x = np.asarray(x, dtype=np.float32)
        h_last, _ = _lstm_seq(x, self.enc_ih, self.enc_hh, self.enc_b, self.H)
        z = self.tl_W @ h_last + self.tl_b
        h0 = self.fl_W @ z + self.fl_b
        h0_seq = np.repeat(h0[None, :], x.shape[0], axis=0)
        _, hs = _lstm_seq(h0_seq, self.dec_ih, self.dec_hh, self.dec_b, self.H)
        rec = hs @ self.out_W.T + self.out_b
        return float(((rec - x) ** 2).mean())


class NumpyGRU:
    def __init__(self, state_dict, hidden=48):
        sd = {k: v.numpy().astype(np.float32) for k, v in state_dict.items()}
        self.H = hidden
        self.w_ih = sd["gru.weight_ih_l0"]
        self.w_hh = sd["gru.weight_hh_l0"]
        self.b_ih = sd["gru.bias_ih_l0"]
        self.b_hh = sd["gru.bias_hh_l0"]
        self.head_W, self.head_b = sd["head.weight"], sd["head.bias"]

    def predict(self, x):
        """x [T, in] -> next-step head output [2]."""
        x = np.asarray(x, dtype=np.float32)
        H = self.H
        h = np.zeros(H, dtype=np.float32)
        xg = x @ self.w_ih.T + self.b_ih
        for t in range(x.shape[0]):
            hg = self.w_hh @ h + self.b_hh
            r = 1.0 / (1.0 + np.exp(-(xg[t][:H] + hg[:H])))
            z = 1.0 / (1.0 + np.exp(-(xg[t][H:2 * H] + hg[H:2 * H])))
            n = np.tanh(xg[t][2 * H:] + r * hg[2 * H:])
            h = (1.0 - z) * n + z * h
        return self.head_W @ h + self.head_b
