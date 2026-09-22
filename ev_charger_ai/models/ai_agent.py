"""Competitor 2 — AI Agent.

A single autonomous agent with the classic perceive -> reason -> act loop:

  perceive  ingest event + shared features
  reason    triage, then *choose which tools to invoke* (attention budget),
            post findings to an evidence board with time-decay
  act       noisy-OR belief fusion over distinct evidence types; alert when
            belief crosses threshold with >=2 evidence families (or 1 critical)

Tools: spec_checker, trend_analyzer, comm_health, anomaly (LSTM-AE),
forecast (GRU). Differs from TraditionalAI by dynamic tool selection,
evidence accumulation/decay and fused belief, rather than one-shot rules.
"""
import math

from core.detector_base import Detector
from models.nn_tools import AnomalyTool, ForecastTool
from models.slac_rules import slac_alert

CRITICAL = 0.95


class EvidenceBoard:
    def __init__(self, half_life_s=20.0):
        self.items = {}  # family -> (weight, t, note)
        self.hl = half_life_s

    def post(self, family, weight, t, note):
        cur = self.items.get(family)
        if cur is None:
            self.items[family] = (weight, t, note)
            return
        cur_eff = cur[0] * (0.5 ** ((t - cur[1]) / self.hl))
        if weight >= cur_eff:          # fresh evidence beats decayed memory
            self.items[family] = (weight, t, note)

    def belief(self, now):
        p_keep = 1.0
        n_active = 0
        critical = False
        notes = []
        for fam, (w, t, note) in self.items.items():
            decay = 0.5 ** ((now - t) / self.hl)
            w_eff = w * decay
            if w_eff < 0.05:
                continue
            n_active += 1
            p_keep *= (1.0 - min(w_eff, 0.99))
            if w >= CRITICAL:
                critical = True
            notes.append(f"{fam}={w_eff:.2f}({note})")
        return 1.0 - p_keep, n_active, critical, notes


class AIAgent(Detector):
    name = "AIAgent"

    def __init__(self, alert_belief=0.85):
        self.anomaly = AnomalyTool()
        self.forecast = ForecastTool()
        self.alert_belief = alert_belief
        self.board = None
        self._collapse_run = 0

    def reset(self, station, connector):
        self.board = EvidenceBoard()
        self.anomaly.reset()
        self.forecast.reset()
        self._collapse_run = 0

    # ------------------------------------------------------ tools
    def tool_spec_checker(self, fs):
        out = []
        if fs.resp_code.upper().startswith("FAILED"):
            out.append(("protocol", 1.0, f"resp {fs.resp_code}"))
        if fs.evse_status in ("EVSE_Malfunction", "EVSE_EmergencyShutdown"):
            out.append(("evse", 1.0, fs.evse_status))
        if fs.isolation == "Fault":
            out.append(("isolation", 1.0, "isolation Fault"))
        if fs.isolation_warning:
            out.append(("isolation", 0.55, "isolation Warning"))
        if fs.ev_err not in ("", "NO_ERROR"):
            out.append(("ev", 1.0, f"EVError {fs.ev_err}"))
        if fs.validation_bad:
            out.append(("protocol", 0.3, "msg validation"))
        if (fs.notification in ("Stop", "StopCharging")
                and fs.phase == "delivery"):
            out.append(("protocol", 0.35, "EVSENotification StopCharging"))
        if fs.cablecheck_elapsed and fs.cablecheck_elapsed > 30.0:
            w = 0.5 if fs.cablecheck_elapsed < 40 else 0.9
            out.append(("timeout", w,
                        f"cablecheck {fs.cablecheck_elapsed:.0f}s"))
        if fs.precharge_elapsed and fs.precharge_elapsed > 7.0:
            out.append(("timeout", 0.6,
                        f"precharge {fs.precharge_elapsed:.0f}s"))
        return out

    def tool_iso_conformance(self, fs):
        """Sixth tool, present only in the ISO arm: read the live conformance
        ratios and post graded evidence. Unlike the other tools this one has no
        tuned constants — the weight is the fraction of the standard's own
        limit that has already elapsed, so evidence strengthens exactly as the
        session approaches the point where ISO 15118-2 requires it to end.
        """
        i = fs.iso
        if i is None:
            return []
        out = []
        if i.ongoing_ratio > 0.25:      # [V2G2-711] 60 s
            out.append(("timeout", min(0.3 + 0.7 * i.ongoing_ratio, 0.97),
                        f"EVSEProcessing Ongoing {i.ongoing_ratio:.0%} of ISO timeout"))
        if i.seq_timeout_ratio > 0.25:  # [V2G2-443] 60 s
            out.append(("timeout", min(0.2 + 0.8 * i.seq_timeout_ratio, 0.95),
                        f"sequence idle {i.seq_timeout_ratio:.0%} of ISO timeout"))
        if i.cablecheck_ratio > 0.6:    # [V2G2-702] 40 s
            out.append(("timeout", min(0.3 + 0.6 * i.cablecheck_ratio, 0.92),
                        f"CableCheck {i.cablecheck_ratio:.0%} of ISO timeout"))
        if i.precharge_ratio > 0.7 and i.precharge_v_gap_ratio > 1.0:
            out.append(("power", min(0.3 + 0.4 * i.precharge_ratio, 0.85),
                        f"PreCharge {i.precharge_ratio:.0%} of ISO timeout, "
                        f"still {i.precharge_v_gap_ratio:.1f} bands off"))
        if i.comm_setup_ratio > 0.5:    # [V2G2-448] 20 s
            out.append(("protocol", min(0.2 + 0.7 * i.comm_setup_ratio, 0.9),
                        f"session setup {i.comm_setup_ratio:.0%} of ISO timeout"))
        if i.seq_illegal:
            out.append(("protocol", 0.7, f"illegal successor {fs.msg}"))
        if i.n_redialog:
            out.append(("protocol", min(0.6 + 0.2 * i.n_redialog, 0.9),
                        f"dialog reopened x{i.n_redialog}"))
        if i.msg_timeout_ratio >= 1.0:
            out.append(("timeout", 0.8,
                        f"{i.last_timeout_msg} past its ISO msg timeout"))
        if i.evse_status_sev >= 1.0:
            out.append(("evse", 1.0, f"{fs.evse_status}"))
        return out

    def tool_slac_matching(self, fs):
        """Seventh tool, present only in the SLAC arm. The matching sequence is
        the one thing this fleet's biggest blind family leaves on the wire, and
        nothing else in the evidence board describes it.
        """
        s = fs.slac
        if s is None or s.v2g_seen:
            return []
        out = []
        hard = slac_alert(fs)
        if hard is not None:
            # Critical, not merely strong. A SLAC failure produces no V2G at
            # all, so no other tool on this board can ever corroborate it —
            # posted below CRITICAL it would sit at one active family forever
            # and the agent would never speak (measured: 0 of 10 such sessions
            # before this line). In empirical mode the certainty comes from
            # the fleet's 10 s operating point; normative mode instead comes
            # from the ISO 15118-3 timer/retry budget in slac_rules.py.
            out.append(("comm", max(0.96, hard[0]), hard[1]))
        elif s.match_pending_s >= 1.0:
            # a healthy match answers in 7 ms, so even a second is evidence -
            # graded, because the board should not commit on it alone
            out.append(("comm", 0.45, f"SLAC match unanswered "
                                      f"{s.match_pending_s:.1f}s"))
        if s.n_restart >= 1:
            out.append(("comm", 0.5 + 0.15 * min(s.n_restart, 3),
                        f"SLAC sequence restarted x{s.n_restart}"))
        return out

    def tool_trend_analyzer(self, fs, ev):
        out = []
        if fs.v_over:
            out.append(("power", 0.9, "V over EV limit"))
        # current-below-target is routine here (dual-connector power sharing);
        # only a long non-recovering collapse is evidence
        if ev.evse_i is not None:
            if fs.i_collapse:
                self._collapse_run += 1
                if self._collapse_run >= 60:        # ~30 s sustained
                    out.append(("power", 0.6,
                                f"I collapse x{self._collapse_run}"))
            else:
                self._collapse_run = 0
        if abs(fs.v_ripple_z or 0) > 8.0:
            out.append(("power", 0.25, f"V ripple z={fs.v_ripple_z:.1f}"))
        if abs(fs.i_ripple_z or 0) > 8.0:
            out.append(("power", 0.25, f"I ripple z={fs.i_ripple_z:.1f}"))
        if fs.remaining_trend is not None and fs.remaining_trend > 5.0:
            out.append(("battery", 0.3, "remaining-time diverging"))
        if (fs.soc_rate is not None and fs.phase == "delivery"
                and fs.soc_rate <= 0.0 and (fs.evse_i or 0) > 30
                and fs.session_elapsed > 120):
            out.append(("battery", 0.45, "SOC stalled under current"))
        return out

    def tool_comm_health(self, fs):
        out = []
        if fs.retx_60s > 12:
            out.append(("comm", min(0.1 + fs.retx_60s * 0.015, 0.6),
                        f"{fs.retx_60s} retx/60s"))
        if fs.link_gap is not None and fs.link_gap > 2.0 and fs.phase != "idle":
            out.append(("comm", min(0.4 + fs.link_gap * 0.1, 0.9),
                        f"PLC silent {fs.link_gap:.1f}s"))
        if fs.slac_attempts >= 2:
            out.append(("comm", 0.5 + 0.2 * min(fs.slac_attempts - 2, 2),
                        f"SLAC attempt #{fs.slac_attempts}"))
        if fs.rst_seen and fs.phase in ("cablecheck", "precharge", "delivery"):
            out.append(("comm", 0.8, "TCP RST"))
        if fs.dt_v2g is not None and fs.phase == "delivery":
            if fs.dt_v2g > 1.5:
                out.append(("comm", min(0.2 + fs.dt_v2g * 0.15, 0.8),
                            f"dialog gap {fs.dt_v2g:.1f}s"))
            # NB: gap_z is useless as evidence here — the loop rhythm is so
            # steady that any legit pause yields astronomical z; absolute
            # dt thresholds above carry the real signal.
        if fs.latency_z and fs.latency_z > 6 and fs.req_res_latency > 0.1:
            out.append(("comm", 0.35, f"latency z={fs.latency_z:.1f}"))
        return out

    # ------------------------------------------------------ agent loop
    def observe(self, ev, fs):
        # perceive + triage: which tools deserve attention this tick?
        findings = self.tool_spec_checker(fs)          # always cheap
        findings += self.tool_iso_conformance(fs)      # no-op in the base arm
        findings += self.tool_slac_matching(fs)        # no-op outside the SLAC arm
        if ev.kind == "v2g" and (ev.evse_v is not None
                                 or ev.evse_i is not None):
            findings += self.tool_trend_analyzer(fs, ev)
        if ev.kind in ("tcp", "hpav") or fs.phase == "delivery":
            findings += self.tool_comm_health(fs)
        if ev.kind == "v2g":
            vec = fs.as_vector()
            a = self.anomaly.score(vec)                # heavy tool, throttled
            if a > 10.0:
                findings.append(("anomaly", min(0.1 + 0.03 * a, 0.5),
                                 f"AE z={a:.1f}"))
            if fs.phase == "delivery" and ev.evse_v is not None:
                # forecast on measurement-carrying (Res) rows only
                s = self.forecast.surprise(vec)
                if s > 10.0:
                    findings.append(("forecast", min(0.1 + 0.02 * s, 0.45),
                                     f"forecast z={s:.1f}"))
        # reason: post to board
        for fam, w, note in findings:
            self.board.post(fam, w, fs.t, note)
        # act
        belief, n_active, critical, notes = self.board.belief(fs.t)
        if critical or (belief >= self.alert_belief and n_active >= 2):
            reason = "; ".join(notes[:4])
            return [self.alert(fs.t, min(belief, 0.99),
                               f"belief {belief:.2f}: {reason}")]
        return []
