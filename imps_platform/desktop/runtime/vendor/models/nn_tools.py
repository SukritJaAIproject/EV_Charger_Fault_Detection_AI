"""Pure-NumPy model wrappers for the packaged PCAP inference sidecar.

The training checkpoints are converted from PyTorch ``.pt`` files to safe,
non-pickled ``.npz`` files by :mod:`build_models`.  Keeping deserialization
and inference NumPy-only avoids shipping the multi-gigabyte CUDA/PyTorch
environment to desktop users.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .fast_infer import NumpyGRU, NumpyLSTMAE


WIN = 32
FORE_WIN = 16
FORE_DIMS = 8


def _model_dir() -> Path:
    configured = os.environ.get("IMPS_MODEL_DIR")
    if not configured:
        raise RuntimeError("IMPS_MODEL_DIR is not configured")
    path = Path(configured).resolve()
    if not path.is_dir():
        raise RuntimeError(f"Packaged model directory is missing: {path}")
    return path


def _load_checkpoint(name: str) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    path = _model_dir() / name
    if not path.is_file():
        raise RuntimeError(f"Packaged model artifact is missing: {path}")
    with np.load(path, allow_pickle=False) as archive:
        required = {"__err_mean", "__err_std"}
        missing = required.difference(archive.files)
        if missing:
            raise RuntimeError(
                f"Packaged model artifact is invalid ({', '.join(sorted(missing))}): {path}"
            )
        state = {
            key: np.asarray(archive[key], dtype=np.float32)
            for key in archive.files
            if not key.startswith("__")
        }
        metadata = {
            key: float(np.asarray(archive[key]).item())
            for key in archive.files
            if key.startswith("__")
        }
    return state, metadata


def fore_slice(vector):
    """Select the forecaster dimensions from ``FeatureState.as_vector``."""
    return [
        vector[6],
        vector[7],
        vector[8],
        vector[9],
        vector[10],
        vector[5],
        vector[28],
        vector[3],
    ]


class AnomalyTool:
    """Online LSTM autoencoder scorer using only the NumPy inference engine."""

    def __init__(self, device=None):
        state, metadata = _load_checkpoint("lstm_ae.npz")
        n_feat = int(metadata.get("__n_feat", 0))
        if n_feat <= 0:
            raise RuntimeError("lstm_ae.npz does not contain a valid feature count")
        self.engine = NumpyLSTMAE(state, n_feat)
        self.err_mean = metadata["__err_mean"]
        self.err_std = metadata["__err_std"]
        self.buf = []
        self.last_score = 0.0
        self._since_eval = 0
        self.evals = 0

    def reset(self):
        self.buf = []
        self.last_score = 0.0
        self._since_eval = 0
        self.evals = 0

    def score(self, vector):
        self.buf.append(vector)
        if len(self.buf) > WIN:
            self.buf.pop(0)
        self._since_eval += 1
        if len(self.buf) < WIN or self._since_eval < 10:
            return self.last_score
        self._since_eval = 0
        self.evals += 1
        error = self.engine.recon_error(self.buf)
        self.last_score = (error - self.err_mean) / (self.err_std + 1e-9)
        return self.last_score


class ForecastTool:
    """Online GRU forecaster using only the NumPy inference engine."""

    def __init__(self, device=None):
        state, metadata = _load_checkpoint("gru_fore.npz")
        self.engine = NumpyGRU(state)
        self.err_mean = metadata["__err_mean"]
        self.err_std = metadata["__err_std"]
        self.buf = []
        self.pred = None
        self.smooth = 0.0

    def reset(self):
        self.buf = []
        self.pred = None
        self.smooth = 0.0

    def surprise(self, vector):
        features = fore_slice(vector)
        actual = np.array([vector[6], vector[7]], dtype=np.float32)
        output = self.smooth
        if self.pred is not None:
            error = float(np.abs(self.pred - actual).mean())
            z_score = (error - self.err_mean) / (self.err_std + 1e-9)
            self.smooth = 0.7 * self.smooth + 0.3 * z_score
            output = self.smooth
        self.buf.append(features)
        if len(self.buf) > FORE_WIN:
            self.buf.pop(0)
        if len(self.buf) == FORE_WIN:
            self.pred = self.engine.predict(self.buf)
        return output


__all__ = ["AnomalyTool", "ForecastTool", "fore_slice"]
