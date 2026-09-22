"""GPU-trained neural tools shared by the agent-style competitors.

  LstmAE        sequence autoencoder over feature windows; reconstruction
                error = "this pattern never happens in healthy sessions"
  GruForecaster predicts next (V, I); persistent surprise = physical precursor

Both are trained on CLEAN training-split sessions only (no fault labels
needed) — see train/train_nn_tools.py. Online wrappers keep a rolling window
per session and return calibrated z-like scores.
"""
import os

import numpy as np
import torch
import torch.nn as nn

from core.paths import ARTIFACTS as ART  # noqa: E402
WIN = 32
FORE_WIN = 16
FORE_DIMS = 8  # subset: v_dev,i_dev,v_ripple,i_ripple,soc,latency,gap,dt


class LstmAE(nn.Module):
    def __init__(self, n_feat, hidden=64, latent=16):
        super().__init__()
        self.enc = nn.LSTM(n_feat, hidden, batch_first=True)
        self.to_latent = nn.Linear(hidden, latent)
        self.from_latent = nn.Linear(latent, hidden)
        self.dec = nn.LSTM(hidden, hidden, batch_first=True)
        self.out = nn.Linear(hidden, n_feat)

    def forward(self, x):
        _, (h, _) = self.enc(x)
        z = self.to_latent(h[-1])
        h0 = self.from_latent(z).unsqueeze(1).repeat(1, x.shape[1], 1)
        y, _ = self.dec(h0)
        return self.out(y)


class GruForecaster(nn.Module):
    def __init__(self, n_in=FORE_DIMS, hidden=48):
        super().__init__()
        self.gru = nn.GRU(n_in, hidden, batch_first=True)
        self.head = nn.Linear(hidden, 2)  # next (v_norm, i_norm)

    def forward(self, x):
        y, _ = self.gru(x)
        return self.head(y[:, -1])


def fore_slice(vec):
    """Pick the forecaster's input dims out of the full feature vector."""
    # indices in FeatureState.as_vector order
    return [vec[6], vec[7], vec[8], vec[9], vec[10], vec[5], vec[28], vec[3]]


class AnomalyTool:
    """Online LSTM-AE scorer. score() ~ how many sigmas above clean-normal.

    Inference runs through the pure-numpy engine (models/fast_infer.py),
    verified numerically equivalent to the torch model — no torch needed in
    production and ~5x faster per evaluation.
    """

    def __init__(self, device=None):
        from models.fast_infer import NumpyLSTMAE
        ckpt = torch.load(os.path.join(ART, "lstm_ae.pt"),
                          map_location="cpu", weights_only=False)
        self.engine = NumpyLSTMAE(ckpt["state"], ckpt["n_feat"])
        self.err_mean = ckpt["err_mean"]
        self.err_std = ckpt["err_std"]
        self.buf = []
        self.last_score = 0.0
        self._since_eval = 0
        self.evals = 0        # bumps on every real evaluation (not cache hits)

    def reset(self):
        self.buf = []
        self.last_score = 0.0
        self._since_eval = 0
        self.evals = 0

    def score(self, vec):
        self.buf.append(vec)
        if len(self.buf) > WIN:
            self.buf.pop(0)
        self._since_eval += 1
        if len(self.buf) < WIN or self._since_eval < 10:
            return self.last_score
        self._since_eval = 0
        self.evals += 1
        err = self.engine.recon_error(self.buf)
        self.last_score = (err - self.err_mean) / (self.err_std + 1e-9)
        return self.last_score


class ForecastTool:
    """Online GRU forecaster. surprise() = |predicted - actual| z-score EWMA.
    Pure-numpy inference engine, verified equivalent to the torch model."""

    def __init__(self, device=None):
        from models.fast_infer import NumpyGRU
        ckpt = torch.load(os.path.join(ART, "gru_fore.pt"),
                          map_location="cpu", weights_only=False)
        self.engine = NumpyGRU(ckpt["state"])
        self.err_mean = ckpt["err_mean"]
        self.err_std = ckpt["err_std"]
        self.buf = []
        self.pred = None
        self.smooth = 0.0

    def reset(self):
        self.buf = []
        self.pred = None
        self.smooth = 0.0

    def surprise(self, vec):
        feats = fore_slice(vec)
        actual = np.array([vec[6], vec[7]], dtype=np.float32)  # v_dev, i_dev
        out = self.smooth
        if self.pred is not None:
            err = float(np.abs(self.pred - actual).mean())
            z = (err - self.err_mean) / (self.err_std + 1e-9)
            self.smooth = 0.7 * self.smooth + 0.3 * z
            out = self.smooth
        self.buf.append(feats)
        if len(self.buf) > FORE_WIN:
            self.buf.pop(0)
        if len(self.buf) == FORE_WIN:
            self.pred = self.engine.predict(self.buf)
        return out
