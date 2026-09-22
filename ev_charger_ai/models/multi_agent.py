"""Competitor 4 — Multi-Agent system.

Four specialist agents watch the same stream through different professional
lenses; a Coordinator fuses their suspicion on a shared blackboard:

  PowerAgent     electrical delivery: deviation, ripple, collapse, limits
  BatteryAgent   EV side: SOC dynamics, remaining-time trajectory, EV errors
  ProtocolAgent  DIN 70121 dialog: sequence, response codes, latency, stalls
  CommsAgent     PLC link, SLAC, TCP health

Coordination policy:
  - any single agent at critical (>=0.95) -> immediate alert
  - cross-confirmation: two agents above 0.5 within 5 s -> alert
  - one agent above the fused threshold alone -> alert
  - a mid-level suspicion (0.35..0.6) makes the coordinator raise everyone
    else's sensitivity for 10 s ("focus request") so corroborating weak
    signals surface faster than any single-lens system would find them.
"""
from core.detector_base import Detector
from models.slac_rules import slac_alert

CRIT = 0.95


class SpecialistAgent:
    name = "specialist"

    def __init__(self):
        self.suspicion = 0.0
        self.note = ""
        self.t_last = None
        self.sensitivity = 1.0

    def reset(self):
        self.suspicion = 0.0
        self.note = ""
        self.t_last = None
        self.sensitivity = 1.0

    def decay(self, dt):
        self.suspicion *= 0.5 ** (dt / 15.0)

    def bump(self, s, note, t, cap=None):
        # sensitivity sharpens the EVIDENCE; it must never lift a rule above
        # the confidence ceiling its author chose (several ceilings sit
        # deliberately just under the coordinator's decision bars)
        s = min(s * self.sensitivity, s if cap is None else cap, 1.0)
        if s >= self.suspicion:
            self.suspicion = s
            self.note = note
        self.t_last = t

    def observe(self, ev, fs):
        raise NotImplementedError


class PowerAgent(SpecialistAgent):
    name = "power"

    def reset(self):
        super().reset()
        self.collapse_run = 0

    def observe(self, ev, fs):
        if fs.v_over:
            self.bump(0.95, "V over EV max", fs.t)
        # current-below-target is routine (dual-connector power sharing);
        # only a long, non-recovering collapse is suspicious
        if ev.evse_i is not None:      # judge only on measurable (Res) rows
            if fs.i_collapse:
                self.collapse_run += 1
                if self.collapse_run >= 60:            # ~30 s sustained
                    self.bump(0.6, f"I collapse x{self.collapse_run}", fs.t)
            else:
                self.collapse_run = 0
        if abs(fs.v_ripple_z or 0) > 8.0:
            self.bump(0.15 + 0.03 * abs(fs.v_ripple_z),
                      f"V ripple z={fs.v_ripple_z:.1f}", fs.t, cap=0.45)
        if abs(fs.i_ripple_z or 0) > 8.0:
            self.bump(0.15 + 0.03 * abs(fs.i_ripple_z),
                      f"I ripple z={fs.i_ripple_z:.1f}", fs.t, cap=0.45)
        if fs.precharge_elapsed and fs.precharge_elapsed > 7.0:
            self.bump(0.4 + 0.05 * fs.precharge_elapsed,
                      f"precharge {fs.precharge_elapsed:.0f}s", fs.t, cap=0.85)
        if (fs.precharge_v_gap is not None and fs.precharge_elapsed
                and fs.precharge_elapsed > 4.0
                and abs(fs.precharge_v_gap) > 60):
            self.bump(0.55, f"precharge gap {fs.precharge_v_gap:.0f}V", fs.t)


class BatteryAgent(SpecialistAgent):
    name = "battery"

    def observe(self, ev, fs):
        if fs.ev_err not in ("", "NO_ERROR"):
            self.bump(1.0, f"EVError {fs.ev_err}", fs.t)
        if (fs.soc_rate is not None and fs.phase == "delivery"
                and fs.soc_rate <= 0.0 and (fs.evse_i or 0) > 30
                and fs.session_elapsed > 120):
            self.bump(0.5, "SOC stalled under current", fs.t)
        if fs.remaining_trend is not None and fs.remaining_trend > 5.0:
            self.bump(0.3, "remaining-time diverging", fs.t)


class ProtocolAgent(SpecialistAgent):
    name = "protocol"

    def observe(self, ev, fs):
        if fs.resp_code.upper().startswith("FAILED"):
            self.bump(1.0, f"resp {fs.resp_code}", fs.t)
        if fs.evse_status in ("EVSE_Malfunction", "EVSE_EmergencyShutdown"):
            self.bump(1.0, fs.evse_status, fs.t)
        if fs.isolation == "Fault":
            self.bump(1.0, "isolation Fault", fs.t)
        if fs.isolation_warning:
            # transient warnings occur in healthy sessions — below the
            # consensus bar on its own
            self.bump(0.45, "isolation Warning", fs.t)
        if fs.validation_bad:
            self.bump(0.3, "validation error", fs.t)
        if (fs.notification in ("Stop", "StopCharging")
                and fs.phase == "delivery"):
            self.bump(0.45, "notification StopCharging", fs.t)
        if fs.cablecheck_elapsed and fs.cablecheck_elapsed > 25.0:
            self.bump(0.4 + 0.02 * fs.cablecheck_elapsed,
                      f"cablecheck {fs.cablecheck_elapsed:.0f}s", fs.t, cap=0.9)
        if fs.dt_v2g is not None and fs.phase == "delivery" and fs.dt_v2g > 1.5:
            # 2-3 s dialog pauses recur in healthy sessions on this fleet
            self.bump(0.2 + 0.15 * fs.dt_v2g,
                      f"dialog gap {fs.dt_v2g:.1f}s", fs.t, cap=0.8)
        if fs.latency_z and fs.latency_z > 5 and (fs.req_res_latency or 0) > 0.1:
            self.bump(0.4, f"latency z={fs.latency_z:.1f}", fs.t)


class CommsAgent(SpecialistAgent):
    name = "comms"

    def reset(self):
        super().reset()
        self.v2g_seen = False
        self.slac_seen = 0

    def observe(self, ev, fs):
        if ev.kind == "v2g":
            self.v2g_seen = True
        # slac_attempts is a monotonic session counter, so judge it on the
        # EDGE (a newly arrived SLAC_PARM.REQ). A level test re-bumps on every
        # later event and pins the agent at its ceiling for the whole session.
        if fs.slac_attempts > self.slac_seen:
            self.slac_seen = fs.slac_attempts
            if fs.slac_attempts >= 2:
                if self.v2g_seen:
                    # re-SLAC after the dialog started = genuine link drop
                    self.bump(0.95, f"re-SLAC #{fs.slac_attempts}", fs.t)
                else:
                    # retry during initial PLC matching is routine; keep it
                    # under the consensus (0.5) and fused (0.85) bars
                    self.bump(0.3 + 0.1 * fs.slac_attempts,
                              f"SLAC attempt #{fs.slac_attempts}", fs.t,
                              cap=0.6)
        if fs.link_gap is not None and fs.link_gap > 1.5 and fs.phase != "idle":
            self.bump(0.35 + 0.15 * fs.link_gap,
                      f"PLC silent {fs.link_gap:.1f}s", fs.t, cap=0.9)
        if fs.retx_60s > 12:
            self.bump(0.1 + 0.015 * fs.retx_60s,
                      f"{fs.retx_60s} retx/60s", fs.t, cap=0.6)
        if fs.rst_seen and fs.phase in ("cablecheck", "precharge", "delivery"):
            self.bump(0.75, "TCP RST", fs.t)
        # SLAC arm only: the matching sequence. This agent already owns the PLC
        # lens, so the signal belongs here rather than in a sixth specialist.
        if fs.slac is not None:
            hit = slac_alert(fs)
            if hit is not None:
                self.bump(max(0.95, hit[0]), hit[1], fs.t)


class StandardsAgent(SpecialistAgent):
    """Fifth specialist, active only in the ISO arm: reads the dialog against
    ISO 15118-2:2014 instead of against this fleet's habits.

    Its suspicion is the fraction of a normative limit already consumed, so it
    is the one member of the team whose opinion is not calibrated on the data
    it is judging — which is exactly what makes it useful for
    cross-confirmation: when it and a data-tuned agent agree, the agreement is
    not two views of the same fitted threshold.
    """
    name = "standards"

    def observe(self, ev, fs):
        i = fs.iso
        if i is None:
            return
        if i.rc_sev >= 1.0:
            self.bump(1.0, f"ISO 8.8.3 terminate: {fs.resp_code}", fs.t)
        if i.evse_status_sev >= 1.0:
            self.bump(1.0, f"ISO Table 98 {fs.evse_status}", fs.t)
        if i.ongoing_ratio > 0.25:
            self.bump(0.3 + 0.7 * min(i.ongoing_ratio, 1.0),
                      f"Ongoing {i.ongoing_ratio * 60:.0f}s/60s [V2G2-711]",
                      fs.t, cap=0.97)
        if i.seq_timeout_ratio > 0.25:
            self.bump(0.2 + 0.8 * min(i.seq_timeout_ratio, 1.0),
                      f"sequence idle {i.seq_timeout_ratio * 60:.0f}s/60s "
                      "[V2G2-443]", fs.t, cap=0.95)
        if i.cablecheck_ratio > 0.6:
            self.bump(0.3 + 0.6 * min(i.cablecheck_ratio, 1.0),
                      f"CableCheck {i.cablecheck_ratio * 40:.0f}s/40s "
                      "[V2G2-702]", fs.t, cap=0.92)
        if i.comm_setup_ratio > 0.5:
            self.bump(0.2 + 0.7 * min(i.comm_setup_ratio, 1.0),
                      f"setup {i.comm_setup_ratio * 20:.0f}s/20s [V2G2-448]",
                      fs.t, cap=0.9)
        # [V2G2-706] PreCharge is deliberately NOT voted on here. It was kept
        # as graded evidence after being demoted from a hard rule, and on the
        # full-fleet held-out split (2026-09-15) that vote produced 348 false
        # alarms against 12 catches. The feature remains in the vector for the
        # learned layers; this agent just no longer speaks on it.
        if i.n_redialog:
            self.bump(0.6 + 0.2 * i.n_redialog,
                      f"dialog reopened x{i.n_redialog}", fs.t, cap=0.9)
        if i.seq_illegal:
            self.bump(0.7, f"Fig.102 illegal successor {fs.msg}", fs.t)
        if i.msg_timeout_ratio >= 1.0:
            self.bump(0.8, f"{i.last_timeout_msg} past Table 109 timeout",
                      fs.t)


class MultiAgent(Detector):
    name = "MultiAgent"

    def __init__(self, fused_threshold=0.85):
        self.agents = [PowerAgent(), BatteryAgent(), ProtocolAgent(),
                       CommsAgent(), StandardsAgent()]
        self.fused_threshold = fused_threshold
        self.focus_until = 0.0
        self.focus_requester = None
        self.last_t = None

    def reset(self, station, connector):
        for a in self.agents:
            a.reset()
        self.focus_until = 0.0
        self.focus_requester = None
        self.last_t = None

    def observe(self, ev, fs):
        if self.last_t is not None:
            dt = max(fs.t - self.last_t, 0.0)
            for a in self.agents:
                a.decay(dt)
        self.last_t = fs.t

        for a in self.agents:
            a.observe(ev, fs)

        # coordinator
        sus = sorted(((a.suspicion, a) for a in self.agents), reverse=True,
                     key=lambda x: x[0])
        top_s, top_a = sus[0]
        second_s, second_a = sus[1]

        # focus request: one agent's mid-level suspicion sharpens the OTHERS
        # for 10 s, so corroborating weak signals surface faster. The
        # requester keeps sensitivity 1.0 — sharpening itself would just be
        # self-amplification.
        if 0.35 <= top_s < 0.6 and fs.t > self.focus_until:
            self.focus_until = fs.t + 10.0
            self.focus_requester = top_a
        boosted = fs.t <= self.focus_until
        for a in self.agents:
            a.sensitivity = (1.25 if boosted and a is not self.focus_requester
                             else 1.0)

        if top_s >= CRIT:
            return [self.alert(fs.t, top_s,
                               f"[{top_a.name}] critical: {top_a.note}")]
        if top_s >= 0.5 and second_s >= 0.5:
            fused = 1 - (1 - top_s) * (1 - second_s)
            return [self.alert(
                fs.t, min(fused, 0.99),
                f"consensus [{top_a.name}]{top_a.note} + "
                f"[{second_a.name}]{second_a.note}")]
        if top_s >= self.fused_threshold:
            return [self.alert(fs.t, top_s,
                               f"[{top_a.name}] {top_a.note}")]
        return []
