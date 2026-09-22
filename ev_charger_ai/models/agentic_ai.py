"""Competitor 3 — Agentic AI.

Everything the AI Agent has, plus genuine agency:

  goals          explicit per-phase subgoals with *expectations*
                 ("SLAC meets its selected rule-arm timer",
                  "precharge converges in <7 s",
                  "delivery stays stable", "session closes gracefully")
  planning       when an expectation is violated softly, it *plans an
                 investigation*: a short-lived focused probe that gathers
                 corroborating evidence (incl. NN tools) before deciding
  memory         persistent per-station baselines (phase durations, ripple,
                 latency) learned online across sessions -> expectations are
                 station-specific, not one-size-fits-all
  reflection     after each session it judges "was that normal?" from its own
                 observations (never ground truth) and updates the baselines

The result: earlier, more context-aware alerts with fewer false alarms on
stations that are habitually slow/noisy.
"""
from core.detector_base import Detector
from core.feature_tracker import Ewm
from models.nn_tools import AnomalyTool, ForecastTool
from models.slac_rules import slac_alert


class StationMemory:
    """Online baselines per station/connector, persisted across sessions."""

    def __init__(self):
        self.slac_s = Ewm(0.25)
        self.handshake_s = Ewm(0.25)
        self.cablecheck_s = Ewm(0.25)
        self.precharge_s = Ewm(0.25)
        self.ripple_v = Ewm(0.15)
        self.latency = Ewm(0.15)
        self.sessions_seen = 0

    def expect(self, ewm, default, k=3.0, floor=None):
        if ewm.mean is None or self.sessions_seen < 3:
            return default
        val = ewm.mean + k * ewm.std + 0.25 * abs(ewm.mean)
        return max(val, floor if floor is not None else default * 0.5)


class Investigation:
    def __init__(self, hypothesis, t0, ttl_s=15.0, need=2):
        self.hypothesis = hypothesis
        self.t0 = t0
        self.ttl = ttl_s
        self.need = need
        self.evidence = []
        self._last_add = {}   # note-kind -> t (rate limit repeating evidence)
        self._kind_sum = {}   # note-kind -> accumulated weight

    def add(self, note, weight, t=None, min_dt=0.0, kind_cap=None):
        kind = note.split(" ")[0]
        if t is not None and min_dt > 0.0:
            if t - self._last_add.get(kind, -1e18) < min_dt:
                return
            self._last_add[kind] = t
        if kind_cap is not None:
            if self._kind_sum.get(kind, 0.0) + weight > kind_cap:
                return
        self._kind_sum[kind] = self._kind_sum.get(kind, 0.0) + weight
        self.evidence.append((note, weight))

    def verdict(self, now):
        if sum(w for _, w in self.evidence) >= self.need:
            return "confirmed"
        if now - self.t0 > self.ttl:
            return "dismissed"
        return "open"


class AgenticAI(Detector):
    name = "AgenticAI"

    def __init__(self):
        self.anomaly = AnomalyTool()
        self.forecast = ForecastTool()
        self.memory = {}          # station/conn -> StationMemory
        self.mem = None
        self.invs = []
        self.session_obs = None
        self._phase_seen_t = None
        self._last_phase = None

    # ------------------------------------------------------ lifecycle
    def reset(self, station, connector):
        key = f"{station}/{connector}"
        self.mem = self.memory.setdefault(key, StationMemory())
        self.anomaly.reset()
        self.forecast.reset()
        self.invs = []
        self._last_phase = "idle"
        self._phase_seen_t = {}
        self._collapse_run = 0
        self.session_obs = {"alerted": False, "phase_dur": {}, "ripple": [],
                            "lat": [], "graceful": False, "reached_cd": False}

    def end_session(self, station, connector):
        # reflection: only learn from sessions the agent itself judged healthy
        obs = self.session_obs
        if obs is None or obs["alerted"] or not obs["graceful"]:
            self.mem.sessions_seen += 1
            return
        m = self.mem
        for phase, dur in obs["phase_dur"].items():
            ewm = {"slac": m.slac_s, "handshake": m.handshake_s,
                   "cablecheck": m.cablecheck_s,
                   "precharge": m.precharge_s}.get(phase)
            if ewm is not None and dur > 0:
                ewm.update(dur)
        if obs["ripple"]:
            m.ripple_v.update(sum(obs["ripple"]) / len(obs["ripple"]))
        if obs["lat"]:
            m.latency.update(sum(obs["lat"]) / len(obs["lat"]))
        m.sessions_seen += 1

    # ------------------------------------------------------ helpers
    def _track_phases(self, fs):
        if fs.phase != self._last_phase:
            t_in = self._phase_seen_t.get(self._last_phase)
            if t_in is not None:
                self.session_obs["phase_dur"][self._last_phase] = fs.t - t_in
            self._phase_seen_t[fs.phase] = fs.t
            self._last_phase = fs.phase
        if fs.phase == "delivery":
            self.session_obs["reached_cd"] = True
        if fs.msg == "SessionStopRes":
            self.session_obs["graceful"] = True

    def _reflex(self, fs):
        """Hard faults need no plan — immediate goal failure."""
        if fs.resp_code.upper().startswith("FAILED"):
            return f"goal 'dialog OK' failed: {fs.resp_code}", "PROTOCOL_FAILED"
        if fs.evse_status in ("EVSE_Malfunction", "EVSE_EmergencyShutdown"):
            return f"goal 'EVSE healthy' failed: {fs.evse_status}", "EVSE_FAULT"
        if fs.isolation == "Fault":
            return "goal 'insulation OK' failed", "ISOLATION_FAULT"
        if fs.ev_err not in ("", "NO_ERROR"):
            return f"goal 'EV healthy' failed: {fs.ev_err}", "EV_ERROR"
        # SLAC arm: a selected policy's hard timer is a goal failure outright.
        # Empirical and normative clocks are kept separate in slac_rules.py.
        if fs.slac is not None:
            hit = slac_alert(fs)
            if hit is not None:
                return f"goal 'PLC link established' failed: {hit[1]}", hit[2]
        # ISO arm only: a normative timeout reached is a goal failure by
        # definition — the standard says the session must end here, so there
        # is nothing left to investigate.
        i = fs.iso
        if i is not None:
            if i.ongoing_ratio >= 1.0:
                return ("goal 'EVSE finishes processing' failed: Ongoing "
                        f"{i.ongoing_ratio * 60:.0f}s > 60s [V2G2-711]",
                        "COMM_FREEZE")
            if i.seq_timeout_ratio >= 1.0:
                return ("goal 'dialog progresses' failed: idle "
                        f"{i.seq_timeout_ratio * 60:.0f}s > 60s [V2G2-443]",
                        "COMM_FREEZE")
            if i.comm_setup_ratio >= 1.0:
                return ("goal 'session established' failed: no SessionSetupRes "
                        "within 20s [V2G2-448]", "SESSION_ABORT")
        return None

    def _expectations(self, fs):
        """Soft expectation violations -> open investigations."""
        m = self.mem
        out = []
        if (fs.phase == "slac"
                and fs.phase_elapsed > m.expect(m.slac_s, 12.0)):
            out.append(("link_establishment_failing", 0.9))
        if fs.slac_attempts >= 2:
            out.append(("link_establishment_failing", 1.0))
        if (fs.phase == "handshake"
                and fs.phase_elapsed > m.expect(m.handshake_s, 25.0)):
            out.append(("handshake_stalling", 0.8))
        if (fs.cablecheck_elapsed
                and fs.cablecheck_elapsed > m.expect(m.cablecheck_s, 25.0)):
            out.append(("cablecheck_abnormal", 1.0))
        if (fs.precharge_elapsed
                and fs.precharge_elapsed > m.expect(m.precharge_s, 6.0)):
            out.append(("precharge_not_converging", 1.0))
        if fs.isolation_warning:
            out.append(("insulation_degrading", 1.6))
        # NB: EVSENotification=StopCharging is how NORMAL user stops look on
        # this fleet — not an expectation violation on its own.
        # Current-below-target is routine (dual-connector power sharing);
        # only a sustained non-recovering collapse merits investigation.
        if self._collapse_run >= 20:
            out.append(("power_collapse", 1.2))
        if fs.dt_v2g is not None and fs.phase == "delivery" and fs.dt_v2g > 2.5:
            out.append(("dialog_freezing", 0.8 + min(fs.dt_v2g / 2.5, 1.2)))
        if fs.link_gap is not None and fs.link_gap > 1.5 and fs.phase != "idle":
            out.append(("plc_link_degrading", 1.0))
        if fs.retx_60s > 20:
            out.append(("tcp_degrading", 0.7))
        # ISO arm: the station memory learns what this charger habitually
        # does, but the standard says what it is *allowed* to do. Both are
        # expectations; only one of them is negotiable.
        i = fs.iso
        if i is not None:
            if i.ongoing_ratio > 0.4:
                out.append(("iso_processing_stalled",
                            0.8 + 1.4 * min(i.ongoing_ratio, 1.0)))
            if i.seq_timeout_ratio > 0.4:
                out.append(("dialog_freezing",
                            0.8 + 1.2 * min(i.seq_timeout_ratio, 1.0)))
            if i.cablecheck_ratio > 0.75:
                out.append(("cablecheck_abnormal", 1.2))
            if i.precharge_ratio > 0.8 and i.precharge_v_gap_ratio > 1.0:
                out.append(("precharge_not_converging", 1.3))
            if i.comm_setup_ratio > 0.6:
                out.append(("handshake_stalling", 1.2))
            if i.n_redialog or i.seq_illegal:
                out.append(("iso_sequence_violated", 1.4))
        return out

    def _probe(self, inv, fs, vec_scores):
        """Investigation gathers corroborating evidence from all signals."""
        h = inv.hypothesis
        if h == "link_establishment_failing":
            if fs.slac_attempts >= 2:
                inv.add(f"SLAC attempts {fs.slac_attempts}", 1.2,
                        t=fs.t, min_dt=2.0)
            if fs.phase_elapsed > 20:
                inv.add("nomatch yet", 0.8, t=fs.t, min_dt=5.0)
        elif h == "insulation_degrading":
            if fs.isolation_warning:
                inv.add("warning persists", 0.45, t=fs.t, min_dt=2.0)
            if fs.isolation == "Fault":
                inv.add("became Fault", 3.0)
            if vec_scores.get("ae_fresh") and vec_scores.get("ae", 0) > 5:
                inv.add("AE anomaly", 0.5)
        elif h in ("dialog_freezing", "tcp_degrading", "plc_link_degrading"):
            if fs.retx_60s > 12:
                inv.add(f"retx {fs.retx_60s}", 0.4, t=fs.t, min_dt=5.0,
                        kind_cap=0.8)
            if fs.rst_seen:
                inv.add("RST seen", 1.2, t=fs.t, min_dt=1e17)
            if fs.link_gap is not None and fs.link_gap > 1.5:
                inv.add(f"linkgap {fs.link_gap:.1f}", 0.9, t=fs.t, min_dt=1.0)
            if fs.dt_v2g is not None and fs.dt_v2g > 2.0:
                inv.add(f"gap {fs.dt_v2g:.1f}s", 0.3 + min(0.2 * fs.dt_v2g,
                                                           0.7))
            if fs.latency_z and fs.latency_z > 4:
                inv.add(f"latency z={fs.latency_z:.1f}", 0.6,
                        t=fs.t, min_dt=2.0)
        elif h == "power_collapse":
            # forecast/ripple alone cannot confirm (load sharing looks the
            # same to them) — a true collapse signal must participate
            if fs.i_collapse:
                inv.add("collapse persists", 0.5, t=fs.t, min_dt=2.0)
            if vec_scores.get("fore", 0) > 8:
                inv.add("forecast surprise", 0.4, t=fs.t, min_dt=2.0,
                        kind_cap=1.2)
            if abs(fs.v_ripple_z or 0) > 6.5:
                inv.add("Vunstable", 0.4, t=fs.t, min_dt=2.0, kind_cap=0.8)
        elif h in ("iso_processing_stalled", "iso_sequence_violated"):
            i = fs.iso
            if i is None:
                inv.ttl = 0.0
            elif h == "iso_processing_stalled":
                # the evidence IS the clock: every further second of Ongoing
                # is another second of the standard's budget spent
                if i.ongoing_ratio > 0.4:
                    inv.add(f"ongoing {i.ongoing_ratio:.2f}",
                            0.5 + 1.5 * min(i.ongoing_ratio, 1.0),
                            t=fs.t, min_dt=2.0)
                else:
                    inv.ttl = 0.0          # EVSEProcessing went Finished
                if i.seq_timeout_ratio > 0.4:
                    inv.add("dialog idle too", 0.6, t=fs.t, min_dt=5.0)
            else:
                if i.n_redialog:
                    inv.add(f"redialog x{i.n_redialog}", 1.5, t=fs.t,
                            min_dt=1e17)
                if i.seq_illegal:
                    inv.add("illegal successor", 1.0, t=fs.t, min_dt=1.0)
                if i.rc_sev >= 1.0:
                    inv.add("FAILED response", 2.0)
        elif h in ("cablecheck_abnormal", "precharge_not_converging",
                   "handshake_stalling"):
            expected_phase = {"cablecheck_abnormal": "cablecheck",
                              "precharge_not_converging": "precharge",
                              "handshake_stalling": "handshake"}[h]
            if fs.phase == expected_phase:
                inv.add("stuck evidence", 0.45, t=fs.t, min_dt=2.0)
                if vec_scores.get("ae_fresh") and vec_scores.get("ae", 0) > 3:
                    inv.add("AE anomaly", 0.6)
                if fs.retx_60s > 4:
                    inv.add("comm degraded", 0.5, t=fs.t, min_dt=5.0)
            else:
                # phase moved on — hypothesis no longer applies
                inv.ttl = 0.0

    # ------------------------------------------------------ main loop
    def observe(self, ev, fs):
        self._track_phases(fs)
        if fs.req_res_latency is not None:
            self.session_obs["lat"].append(fs.req_res_latency)
        if fs.phase == "delivery" and abs(fs.v_ripple_z or 0) > 0:
            self.session_obs["ripple"].append(abs(fs.v_ripple_z))

        reflex = self._reflex(fs)
        if reflex:
            self.session_obs["alerted"] = True
            return [self.alert(fs.t, 1.0, reflex[0], reflex[1])]

        if ev.evse_i is not None:
            if fs.i_collapse:
                self._collapse_run += 1
            else:
                self._collapse_run = 0

        vec_scores = {}
        if ev.kind == "v2g":
            vec = fs.as_vector()
            evals_before = self.anomaly.evals
            vec_scores["ae"] = self.anomaly.score(vec)
            vec_scores["ae_fresh"] = self.anomaly.evals != evals_before
            if fs.phase == "delivery" and ev.evse_v is not None:
                vec_scores["fore"] = self.forecast.surprise(vec)
            # proactive: strong NN signal alone opens an investigation
            if vec_scores["ae"] > 12.0:
                self._open("pattern_anomaly", fs.t, need=2.5)
            if vec_scores.get("fore", 0) > 8.0:
                self._open("power_collapse", fs.t, need=2.2)

        for hypo, urgency in self._expectations(fs):
            self._open(hypo, fs.t, need=max(2.0 - 0.5 * (urgency - 1.0), 1.2))

        alerts = []
        still_open = []
        for inv in self.invs:
            self._probe(inv, fs, vec_scores)
            if (inv.hypothesis == "pattern_anomaly"
                    and vec_scores.get("ae_fresh")
                    and vec_scores.get("ae", 0) > 9):
                inv.add("AE persists", 0.5)
            v = inv.verdict(fs.t)
            if v == "confirmed":
                ev_str = ", ".join(n for n, _ in inv.evidence[:4])
                alerts.append(self.alert(
                    fs.t, 0.9,
                    f"investigation '{inv.hypothesis}' confirmed: {ev_str}"))
            elif v == "open":
                still_open.append(inv)
        self.invs = still_open
        if alerts:
            self.session_obs["alerted"] = True
            return alerts[:1]
        return []

    def _open(self, hypothesis, t, need=2.0):
        for inv in self.invs:
            if inv.hypothesis == hypothesis:
                return
        self.invs.append(Investigation(hypothesis, t, need=need))
