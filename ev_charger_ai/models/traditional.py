"""Competitor 1 — Traditional AI.

Classic non-agentic stack: a fixed spec-derived rule engine plus two trained
classical ML models (Isolation Forest for unsupervised anomaly scoring,
XGBoost for supervised fault-within-horizon probability). Fixed thresholds
calibrated once on the training split; no memory, no planning, no adaptation.
"""
import os

import joblib
import numpy as np

from core.detector_base import Detector
from models.iso_rules import iso_alert
from models.slac_rules import slac_alert

from core.paths import ARTIFACTS as ART  # noqa: E402


class TraditionalAI(Detector):
    name = "TraditionalAI"

    XGB_EVERY = 4     # score cadence on v2g events (streaming cost control)
    IF_EVERY = 8

    def __init__(self):
        from core.feature_tracker import FeatureState
        from models.fast_infer import FastIForest, FastXGB
        bundle = joblib.load(os.path.join(ART, "traditional.joblib"))
        self.iforest = FastIForest(bundle["iforest"])
        self.xgb = FastXGB(bundle["xgb"], FeatureState.N_FEATURES)
        self.if_thresh = bundle["if_thresh"]
        self.xgb_thresh = bundle["xgb_thresh"]
        self._i_collapse_run = 0
        self._n_v2g = 0

    def reset(self, station, connector):
        self._i_collapse_run = 0
        self._n_v2g = 0

    def observe(self, ev, fs):
        # --- Layer 0: ISO 15118-2 conformance (only in the ISO arm) ----
        # fs.iso is None unless EV_AI_ISO=1, so the baseline arm runs the
        # exact code below and nothing else.
        if fs.iso is not None:
            hit = iso_alert(fs)
            if hit is not None:
                conf, reason, fam = hit
                return [self.alert(fs.t, conf, reason, fam)]

        # --- Layer 0b: SLAC matching (only in the SLAC arm) --------------
        if fs.slac is not None:
            hit = slac_alert(fs)
            if hit is not None:
                conf, reason, fam = hit
                return [self.alert(fs.t, conf, reason, fam)]

        # --- Layer 1: hard spec rules (DIN 70121) ----------------------
        if fs.resp_code.upper().startswith("FAILED"):
            return [self.alert(fs.t, 1.0, f"rule: ResponseCode {fs.resp_code}",
                               "PROTOCOL_FAILED")]
        if fs.evse_status in ("EVSE_Malfunction", "EVSE_EmergencyShutdown"):
            return [self.alert(fs.t, 1.0, f"rule: {fs.evse_status}",
                               "EVSE_FAULT")]
        if fs.isolation == "Fault":
            return [self.alert(fs.t, 1.0, "rule: isolation Fault",
                               "ISOLATION_FAULT")]
        if fs.ev_err not in ("", "NO_ERROR"):
            return [self.alert(fs.t, 1.0, f"rule: EVErrorCode {fs.ev_err}",
                               "EV_ERROR")]
        # spec timeouts / physical sanity
        if fs.cablecheck_elapsed and fs.cablecheck_elapsed > 40.0:
            return [self.alert(fs.t, 0.9, "rule: CableCheck > 40s (spec)",
                               "COMM_FREEZE")]
        if fs.dt_v2g is not None and fs.phase == "delivery" and fs.dt_v2g > 3.5:
            return [self.alert(fs.t, 0.85, f"rule: msg gap {fs.dt_v2g:.1f}s "
                               "in delivery", "COMM_FREEZE")]
        if fs.v_over:
            return [self.alert(fs.t, 0.9, "rule: V above EV max limit",
                               "EVSE_FAULT")]
        # NB: current-below-target is NORMAL on this fleet (dual-connector
        # power sharing) — no hard collapse rule; the ML layer sees the
        # i_collapse feature and learns when it matters.
        if fs.retx_60s > 60:
            # bursts of ~40/60s occur on healthy-but-lossy PLC links
            return [self.alert(fs.t, 0.7, f"rule: {fs.retx_60s} retx/60s",
                               "SESSION_ABORT")]
        if fs.link_gap is not None and fs.link_gap > 3.0 and fs.phase != "idle":
            return [self.alert(fs.t, 0.75, f"rule: PLC link silent "
                               f"{fs.link_gap:.1f}s", "SESSION_ABORT")]
        if fs.slac_attempts >= 3:
            return [self.alert(fs.t, 0.8, "rule: 3+ SLAC attempts",
                               "SLAC_FAILURE")]
        if fs.rst_seen and fs.phase in ("delivery", "cablecheck", "precharge"):
            return [self.alert(fs.t, 0.8, "rule: TCP RST mid-session",
                               "SESSION_ABORT")]

        # --- Layer 2: trained ML on feature vector (v2g events only) ---
        if fs.kind != "v2g":
            return []
        self._n_v2g += 1
        x = None
        if self._n_v2g % self.XGB_EVERY == 0:
            x = np.asarray(fs.as_vector(), dtype=np.float32)
            p = self.xgb.predict_proba1(x)
            if p > self.xgb_thresh:
                return [self.alert(fs.t, min(p, 0.99),
                                   f"xgb: fault risk {p:.2f}", "")]
        if self._n_v2g % self.IF_EVERY == 0:
            if x is None:
                x = np.asarray(fs.as_vector(), dtype=np.float32)
            s = self.iforest.score(x)
            if s > self.if_thresh:
                return [self.alert(fs.t, 0.6,
                                   f"iforest: anomaly {s:.2f}", "")]
        return []
