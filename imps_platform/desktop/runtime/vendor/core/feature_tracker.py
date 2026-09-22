"""Incremental per-session feature computation, shared by every detector.

All detectors receive the same FeatureState at each event, so the competition
compares decision architectures, not feature-engineering luck. Everything is
computed online (no lookahead) and cheap enough for production streaming.

Setting ``EV_AI_ISO=1`` additionally attaches the ISO 15118-2:2014 conformance
block (``core/iso_features.py``): 27 further features, each a ratio against a
normative timeout, performance time or sequence rule published in the standard
rather than a threshold tuned on this fleet.

``EV_AI_ISO_VEC=0`` computes that block but keeps it OUT of the numeric vector.
That splits the standard's contribution in two, which is the only way to say
which half did the work:

    EV_AI_ISO=0                 33 cols, no ISO anywhere        (arm "baseline")
    EV_AI_ISO=1 EV_AI_ISO_VEC=0 33 cols, ISO visible to rules   (arm "iso_rules")
    EV_AI_ISO=1                 60 cols, ISO everywhere         (arm "iso")

The middle arm reuses the baseline's trained weights unchanged — same models,
same thresholds, the only difference being that the rule layers can now see the
conformance state. Both flags are read once at import, so a process produces
one width for its whole life and two arms can never be mixed in one matrix.
"""
import math
import os
from collections import deque

ISO_ENABLED = os.environ.get("EV_AI_ISO", "0") == "1"
ISO_IN_VECTOR = ISO_ENABLED and os.environ.get("EV_AI_ISO_VEC", "1") == "1"
if ISO_ENABLED:
    from core.iso_features import IsoTracker, IsoState

# EV_AI_SLAC=1 attaches the HomePlug AV matching view (core/slac_features.py)
# as fs.slac. It adds NO columns to the vector — the matching sequence is a
# rule-layer signal, so trained weights of any width keep loading unchanged.
SLAC_ENABLED = os.environ.get("EV_AI_SLAC", "0") == "1"
if SLAC_ENABLED:
    from core.slac_features import SlacTracker


PHASES = ("idle", "slac", "handshake", "cablecheck", "precharge",
          "delivery", "closing")

PHASE_OF_MSG = {
    "supportedAppProtocolReq": "handshake", "supportedAppProtocolRes": "handshake",
    "SessionSetupReq": "handshake", "SessionSetupRes": "handshake",
    "ServiceDiscoveryReq": "handshake", "ServiceDiscoveryRes": "handshake",
    "ServicePaymentSelectionReq": "handshake",
    "ServicePaymentSelectionRes": "handshake",
    "ContractAuthenticationReq": "handshake",
    "ContractAuthenticationRes": "handshake",
    "ChargeParameterDiscoveryReq": "handshake",
    "ChargeParameterDiscoveryRes": "handshake",
    "CableCheckReq": "cablecheck", "CableCheckRes": "cablecheck",
    "PreChargeReq": "precharge", "PreChargeRes": "precharge",
    "PowerDeliveryReq": "delivery", "PowerDeliveryRes": "delivery",
    "CurrentDemandReq": "delivery", "CurrentDemandRes": "delivery",
    "WeldingDetectionReq": "closing", "WeldingDetectionRes": "closing",
    "SessionStopReq": "closing", "SessionStopRes": "closing",
}


class Ewm:
    """Exponentially weighted mean/std."""

    def __init__(self, alpha=0.1):
        self.alpha = alpha
        self.mean = None
        self.var = 0.0

    def update(self, x):
        if self.mean is None:
            self.mean = x
            self.var = 0.0
        else:
            d = x - self.mean
            self.mean += self.alpha * d
            self.var = (1 - self.alpha) * (self.var + self.alpha * d * d)
        return self

    @property
    def std(self):
        return math.sqrt(max(self.var, 0.0))

    def z(self, x):
        if self.mean is None:
            return 0.0
        # floor the deviation so a perfectly steady signal (var -> 0)
        # doesn't turn a tiny step into an astronomical z-score
        floor = 0.005 * abs(self.mean) + 1e-6
        s = max(self.std, floor)
        return (x - self.mean) / s


class FeatureState:
    """Snapshot of live features; passed to detectors with each event."""
    __slots__ = (
        "t", "phase", "phase_elapsed", "session_elapsed", "dt_v2g",
        "req_res_latency", "latency_z", "v_dev", "i_dev", "v_ripple_z",
        "i_ripple_z", "soc", "soc_rate", "remaining_full_min",
        "remaining_trend", "retx_60s", "rst_seen", "link_gap",
        "slac_attempts", "cablecheck_n", "cablecheck_elapsed",
        "precharge_elapsed", "precharge_v_gap", "notification",
        "isolation", "isolation_warning", "limit_flags", "validation_bad",
        "evse_status", "resp_code", "ev_err", "msg", "kind",
        "i_collapse", "v_over", "gap_z", "ev_target_i", "evse_i",
        "iso", "slac",
    )

    def as_vector(self):
        """Numeric vector for learned models (fixed order, NaN-safe)."""
        def nz(x, d=0.0):
            return d if x is None else float(x)
        base = [
            PHASES.index(self.phase) / 6.0,
            min(nz(self.phase_elapsed) / 60.0, 5.0),
            min(nz(self.session_elapsed) / 600.0, 5.0),
            min(nz(self.dt_v2g) / 1.0, 10.0),
            min(nz(self.req_res_latency) / 0.25, 10.0),
            max(min(nz(self.latency_z), 8.0), -8.0),
            max(min(nz(self.v_dev) / 50.0, 8.0), -8.0),
            max(min(nz(self.i_dev) / 50.0, 8.0), -8.0),
            max(min(nz(self.v_ripple_z), 8.0), -8.0),
            max(min(nz(self.i_ripple_z), 8.0), -8.0),
            nz(self.soc, 50.0) / 100.0,
            max(min(nz(self.soc_rate) * 60.0, 5.0), -5.0),
            min(nz(self.remaining_full_min, 0.0) / 60.0, 5.0),
            max(min(nz(self.remaining_trend), 5.0), -5.0),
            min(self.retx_60s / 20.0, 3.0),
            1.0 if self.rst_seen else 0.0,
            min(nz(self.link_gap) / 5.0, 10.0),
            min(self.slac_attempts / 3.0, 3.0),
            min(self.cablecheck_n / 40.0, 3.0),
            min(nz(self.cablecheck_elapsed) / 40.0, 3.0),
            min(nz(self.precharge_elapsed) / 7.0, 3.0),
            max(min(nz(self.precharge_v_gap) / 50.0, 8.0), -8.0),
            1.0 if self.notification in ("Warning", "ReNegotiation") else
            (2.0 if self.notification in ("Stop", "StopCharging") else 0.0),
            1.0 if self.isolation_warning else 0.0,
            float(len(self.limit_flags or "")),
            1.0 if self.validation_bad else 0.0,
            1.0 if self.i_collapse else 0.0,
            1.0 if self.v_over else 0.0,
            max(min(nz(self.gap_z), 8.0), -8.0),
            1.0 if self.resp_code.upper().startswith("FAILED") else 0.0,
            1.0 if self.evse_status in ("EVSE_Malfunction",
                                        "EVSE_EmergencyShutdown") else 0.0,
            1.0 if self.ev_err not in ("", "NO_ERROR") else 0.0,
            1.0 if self.isolation == "Fault" else 0.0,
        ]
        if ISO_IN_VECTOR and self.iso is not None:
            base.extend(self.iso.as_vector())
        return base

    N_BASE_FEATURES = 33
    N_FEATURES = 33 + (IsoState.N_FEATURES if ISO_IN_VECTOR else 0)


class FeatureTracker:
    """Feeds on Events, emits FeatureState. One instance per session."""

    def __init__(self):
        self.t0 = None
        self.phase = "idle"
        self.phase_t0 = None
        self.last_v2g_t = None
        self.last_req = {}          # msg base -> t of Req awaiting Res
        self.lat_ewm = Ewm(0.05)
        self.v_ewm = Ewm(0.05)
        self.i_ewm = Ewm(0.05)
        self.gap_ewm = Ewm(0.05)
        self.soc_hist = deque(maxlen=50)
        self.rem_hist = deque(maxlen=50)
        self.retx = deque()
        self.rst_seen = False
        self.last_link_t = None
        self.slac_attempts = 0
        self.cablecheck_n = 0
        self.cablecheck_t0 = None
        self.precharge_t0 = None
        self.last_soc = None
        self.last_evse_v = None
        # EV requests (targets/limits) arrive on Req rows; measured values on
        # Res rows — carry the latest request forward so deviations computable
        self.cur_target_v = None
        self.cur_target_i = None
        self.cur_ev_max_v = None
        self.delivery_reached = False  # present current once reached target
        self.iso_tracker = IsoTracker() if ISO_ENABLED else None
        self.slac_tracker = SlacTracker() if SLAC_ENABLED else None

    def _set_phase(self, phase, t):
        if phase != self.phase:
            self.phase = phase
            self.phase_t0 = t

    def update(self, ev):
        t = ev.t
        if self.t0 is None:
            self.t0 = t
            self.phase_t0 = t
        fs = FeatureState()
        fs.iso = self.iso_tracker.update(ev) if self.iso_tracker else None
        fs.slac = self.slac_tracker.update(ev) if self.slac_tracker else None
        fs.t = t
        fs.msg = ev.msg
        fs.kind = ev.kind
        fs.notification = ev.notification
        fs.evse_status = ev.evse_status
        fs.resp_code = ev.resp_code
        fs.ev_err = ev.ev_err
        v = ev.validation
        fs.validation_bad = bool(v) and "OK" not in v and "Success" not in v
        fs.limit_flags = ev.limit_achieved
        fs.isolation = ev.isolation
        fs.isolation_warning = ev.isolation == "Warning"
        fs.rst_seen = self.rst_seen
        fs.ev_target_i = ev.ev_target_i
        fs.evse_i = ev.evse_i

        # --- comm health ------------------------------------------------
        if ev.kind == "tcp":
            if ev.msg == "RST":
                self.rst_seen = True
                fs.rst_seen = True
            else:
                self.retx.append(t)
        while self.retx and t - self.retx[0] > 60.0:
            self.retx.popleft()
        fs.retx_60s = len(self.retx)

        if ev.kind == "hpav":
            if "LINK_STATUS" in ev.msg and ev.msg.endswith("CNF"):
                self.last_link_t = t
            if "SLAC_PARM.REQ" in ev.msg:
                self.slac_attempts += 1
                self._set_phase("slac", t)
        fs.link_gap = (t - self.last_link_t) if self.last_link_t else None
        fs.slac_attempts = self.slac_attempts

        # --- V2G dialog -------------------------------------------------
        fs.dt_v2g = None
        fs.req_res_latency = None
        fs.latency_z = 0.0
        gap_z_now = 0.0
        if ev.kind == "v2g":
            if self.last_v2g_t is not None:
                gap = t - self.last_v2g_t
                fs.dt_v2g = gap
                if self.phase == "delivery":
                    gap_z_now = self.gap_ewm.z(gap)   # z BEFORE absorbing
                    self.gap_ewm.update(gap)
            self.last_v2g_t = t
            base = ev.msg[:-3] if ev.msg.endswith("Req") else (
                ev.msg[:-3] if ev.msg.endswith("Res") else ev.msg)
            if ev.msg.endswith("Req"):
                self.last_req[base] = t
            elif ev.msg.endswith("Res") and base in self.last_req:
                lat = t - self.last_req.pop(base)
                fs.req_res_latency = lat
                fs.latency_z = self.lat_ewm.z(lat)
                self.lat_ewm.update(lat)
            new_phase = PHASE_OF_MSG.get(ev.msg)
            if new_phase:
                self._set_phase(new_phase, t)
            if ev.msg == "CableCheckReq":
                self.cablecheck_n += 1
                if self.cablecheck_t0 is None:
                    self.cablecheck_t0 = t
            if ev.msg == "PreChargeReq" and self.precharge_t0 is None:
                self.precharge_t0 = t
            if ev.ev_target_v is not None:
                self.cur_target_v = ev.ev_target_v
            if ev.ev_target_i is not None:
                self.cur_target_i = ev.ev_target_i
            if ev.ev_max_v is not None:
                self.cur_ev_max_v = ev.ev_max_v
        fs.gap_z = gap_z_now

        fs.cablecheck_n = self.cablecheck_n
        fs.cablecheck_elapsed = (
            (t - self.cablecheck_t0)
            if self.cablecheck_t0 and self.phase == "cablecheck" else 0.0)
        fs.precharge_elapsed = (
            (t - self.precharge_t0)
            if self.precharge_t0 and self.phase == "precharge" else 0.0)

        # --- electrical -------------------------------------------------
        fs.v_dev = fs.i_dev = None
        fs.v_ripple_z = fs.i_ripple_z = 0.0
        fs.i_collapse = False
        fs.v_over = False
        fs.precharge_v_gap = None
        tgt_v = ev.ev_target_v if ev.ev_target_v is not None else \
            self.cur_target_v
        tgt_i = ev.ev_target_i if ev.ev_target_i is not None else \
            self.cur_target_i
        max_v = ev.ev_max_v if ev.ev_max_v is not None else self.cur_ev_max_v
        if ev.evse_v is not None:
            if tgt_v:
                fs.v_dev = ev.evse_v - tgt_v
            if self.phase == "delivery":
                fs.v_ripple_z = self.v_ewm.z(ev.evse_v)
                self.v_ewm.update(ev.evse_v)
            if self.phase == "precharge" and tgt_v:
                fs.precharge_v_gap = tgt_v - ev.evse_v
            if max_v and ev.evse_v > max_v * 1.02:
                fs.v_over = True
            self.last_evse_v = ev.evse_v
        if ev.evse_i is not None:
            if tgt_i:
                fs.i_dev = ev.evse_i - tgt_i
                if ev.evse_i >= 0.8 * tgt_i and tgt_i > 20:
                    self.delivery_reached = True
                # "collapse" = current essentially GONE while the EV asks for
                # substantial power. Partial reductions (down to ~30-50 % of
                # target) are routine dual-connector load sharing on this
                # fleet and must not count.
                if (self.phase == "delivery" and tgt_i > 50
                        and ev.evse_i < max(0.15 * tgt_i, 5.0)
                        and self.delivery_reached
                        and "c" not in (ev.limit_achieved or "")):
                    fs.i_collapse = True
            if self.phase == "delivery":
                fs.i_ripple_z = self.i_ewm.z(ev.evse_i)
                self.i_ewm.update(ev.evse_i)

        # --- battery ----------------------------------------------------
        fs.soc = ev.soc
        fs.soc_rate = None
        if ev.soc is not None:
            self.soc_hist.append((t, ev.soc))
            if len(self.soc_hist) >= 2:
                (t_a, s_a), (t_b, s_b) = self.soc_hist[0], self.soc_hist[-1]
                if t_b > t_a:
                    fs.soc_rate = (s_b - s_a) / (t_b - t_a)
        fs.remaining_full_min = ev.remaining_full_min
        fs.remaining_trend = None
        if ev.remaining_full_min is not None:
            self.rem_hist.append((t, ev.remaining_full_min))
            if len(self.rem_hist) >= 2:
                (t_a, r_a), (t_b, r_b) = self.rem_hist[0], self.rem_hist[-1]
                dt_min = (t_b - t_a) / 60.0
                if dt_min > 0.05:
                    # >0: estimate diverging (remaining not shrinking with time)
                    fs.remaining_trend = (r_b - r_a) / dt_min + 1.0

        fs.phase = self.phase
        fs.session_elapsed = t - self.t0
        fs.phase_elapsed = t - (self.phase_t0 or t)
        return fs

