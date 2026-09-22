"""Online ISO 15118-2:2014 conformance features.

One instance per session, fed the same event stream as ``FeatureTracker``.
Every quantity is a *ratio against a published normative limit* rather than a
hand-tuned threshold, so a value of 1.0 always means "the standard's own
criterion has just been reached". That is the whole point of the experiment:
the baseline arm learns where to put its thresholds from data, this arm is
handed them by the standard.

Two families are kept apart, exactly as clause 8.7.1 does:

  * **Timeout** ratios — reaching 1.0 means the standard requires the party to
    terminate the communication session. These are genuine fault evidence.
  * **Performance-time** ratios — reaching 1.0 only means a party is slower
    than the standard's performance criterion. Real hardware breaches these
    constantly, so they are informative features, never hard rules.

No lookahead: every value is computable from events already seen. Long stalls
become visible *while they are still happening* because the PLC link-status
poll keeps ticking (~20 Hz) even when the V2G dialog is stuck, so the sequence
timers grow on those events instead of only when the dialog resumes.
"""
from core import iso15118 as iso


def _clip(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


class IsoState:
    """Snapshot of the ISO conformance view at one event."""

    __slots__ = (
        "msg_timeout_ratio", "msg_timeout_ratio_max", "msg_perf_ratio",
        "n_msg_timeout_breach", "seq_gap_ratio", "seq_timeout_ratio",
        "n_seq_breach", "ongoing_ratio", "ongoing_perf_breach",
        "comm_setup_ratio", "cablecheck_ratio", "cablecheck_breach",
        "precharge_ratio", "precharge_breach", "seq_illegal", "n_seq_illegal",
        "stage_frac", "stage_regress", "rc_sev", "evse_status_sev",
        "isolation_sev", "notification_sev", "ev_err_sev", "v_over_evse_max",
        "i_over_evse_max", "precharge_v_gap_ratio", "n_redialog",
        # non-vector context used by the rule layers
        "last_timeout_msg", "in_ongoing", "stage_name",
    )

    # Names of the appended block, in as_vector() order. Offsets into the full
    # feature vector are FeatureState.N_BASE_FEATURES + index here.
    FEATURE_NAMES = (
        "iso_msg_timeout_ratio", "iso_msg_timeout_ratio_max",
        "iso_msg_perf_ratio", "iso_n_msg_timeout_breach",
        "iso_seq_gap_ratio", "iso_seq_timeout_ratio", "iso_n_seq_breach",
        "iso_ongoing_ratio", "iso_ongoing_perf_breach",
        "iso_comm_setup_ratio", "iso_cablecheck_ratio",
        "iso_cablecheck_breach", "iso_precharge_ratio",
        "iso_precharge_breach", "iso_seq_illegal", "iso_n_seq_illegal",
        "iso_stage_frac", "iso_stage_regress", "iso_rc_sev",
        "iso_evse_status_sev", "iso_isolation_sev", "iso_notification_sev",
        "iso_ev_err_sev", "iso_v_over_evse_max", "iso_i_over_evse_max",
        "iso_precharge_v_gap_ratio", "iso_n_redialog",
    )

    N_FEATURES = 27

    def as_vector(self):
        """Fixed-order numeric block appended to the base feature vector."""
        return [
            _clip(self.msg_timeout_ratio, 0.0, 8.0),
            _clip(self.msg_timeout_ratio_max, 0.0, 8.0),
            _clip(self.msg_perf_ratio, 0.0, 8.0),
            _clip(self.n_msg_timeout_breach / 5.0, 0.0, 8.0),
            _clip(self.seq_gap_ratio, 0.0, 8.0),
            _clip(self.seq_timeout_ratio, 0.0, 8.0),
            _clip(self.n_seq_breach / 3.0, 0.0, 8.0),
            _clip(self.ongoing_ratio, 0.0, 8.0),
            1.0 if self.ongoing_perf_breach else 0.0,
            _clip(self.comm_setup_ratio, 0.0, 8.0),
            _clip(self.cablecheck_ratio, 0.0, 8.0),
            1.0 if self.cablecheck_breach else 0.0,
            _clip(self.precharge_ratio, 0.0, 8.0),
            1.0 if self.precharge_breach else 0.0,
            1.0 if self.seq_illegal else 0.0,
            _clip(self.n_seq_illegal / 3.0, 0.0, 8.0),
            self.stage_frac,
            1.0 if self.stage_regress else 0.0,
            self.rc_sev,
            self.evse_status_sev,
            self.isolation_sev,
            self.notification_sev,
            self.ev_err_sev,
            _clip(self.v_over_evse_max, -1.0, 4.0),
            _clip(self.i_over_evse_max, -1.0, 4.0),
            _clip(self.precharge_v_gap_ratio, 0.0, 8.0),
            _clip(self.n_redialog, 0.0, 4.0),
        ]


class IsoTracker:
    """Feeds on Events, emits IsoState. One instance per session."""

    def __init__(self):
        self.t0 = None
        self.link_ready_t = None      # proxy for D-LINK_READY.indication
        self.session_setup_res_t = None
        self.last_res_msg = ""        # drives the Figure 102 successor check
        self.last_res_t = None        # start of V2G_*_Sequence_Timer
        self.pending_req = {}         # base name -> t, start of V2G_EVCC_Msg_Timer
        self.pending_breached = set()  # pending requests already counted once
        self.max_msg_ratio = 0.0
        self.n_msg_breach = 0
        self.n_seq_breach = 0
        self._seq_breach_armed = True
        self.n_seq_illegal = 0
        self.ongoing_t0 = None
        self.cablecheck_t0 = None
        self.cablecheck_end_t = None
        self.precharge_t0 = None
        self.precharge_done = False
        self.max_stage = -1
        self.evse_max_v = None
        self.evse_max_i = None
        self.cur_target_v = None
        self.n_dialog = 0

    def _new_v2g_session(self, t):
        """A fresh V2G communication session starts: every timer resets.

        A sessionize chunk is cut on a 60 s idle gap, so it can still hold two
        back-to-back V2G dialogs (a retry after a failure, typically). The
        standard's timers are per communication session, and leaving CableCheck
        or Ongoing running across a re-dialog would report a fake multi-minute
        stall on the second one.
        """
        self.n_dialog += 1
        self.link_ready_t = t
        self.session_setup_res_t = None
        self.pending_req.clear()
        self.pending_breached.clear()
        self.last_res_msg = ""
        self.last_res_t = None
        self._seq_breach_armed = True
        self.ongoing_t0 = None
        self.cablecheck_t0 = None
        self.cablecheck_end_t = None
        self.precharge_t0 = None
        self.precharge_done = False

    # -- helpers -----------------------------------------------------------
    def _sequence_ratios(self, t):
        if self.last_res_t is None:
            return 0.0, 0.0
        gap = t - self.last_res_t
        return gap / iso.SEQ_PERFORMANCE_S, gap / iso.SEQ_TIMEOUT_S

    def update(self, ev):
        t = ev.t
        if self.t0 is None:
            self.t0 = t
        st = IsoState()
        st.last_timeout_msg = ""
        st.seq_illegal = False
        st.msg_timeout_ratio = 0.0
        st.msg_perf_ratio = 0.0

        # --- data-link establishment proxy: SLAC matched, or first V2G ----
        if ev.kind == "hpav" and "SLAC_MATCH.CNF" in ev.msg:
            self.link_ready_t = t
        if ev.kind == "v2g" and self.link_ready_t is None:
            self.link_ready_t = t

        if ev.kind == "v2g":
            msg = ev.msg
            base = iso.base_name(msg)

            # --- V2G_EVCC_Msg_Timer: request sent, response awaited -------
            if msg.endswith("Req"):
                # A dialog opens at supportedAppProtocolReq, or at
                # SessionSetupReq when the app-protocol handshake was not the
                # thing that just happened (some EVs skip it on a retry).
                if (msg == "supportedAppProtocolReq"
                        or (msg == "SessionSetupReq"
                            and self.last_res_msg != "supportedAppProtocolRes")):
                    self._new_v2g_session(t)
                self.pending_req[base] = t
                self.pending_breached.discard(base)
                # V2G_*_Sequence_Timer stops here [V2G2-444]
                if self.last_res_t is not None:
                    gap = t - self.last_res_t
                    if gap >= iso.SEQ_PERFORMANCE_S and self._seq_breach_armed:
                        self.n_seq_breach += 1
                        self._seq_breach_armed = False
                # Figure 102: is this a legal successor of the last response?
                # Only meaningful once we have seen the dialog open — a ring
                # file that resumes mid-CurrentDemand loop is a capture seam,
                # not a sequence error.
                allowed = (iso.DC_NEXT_REQ.get(self.last_res_msg)
                           if self.n_dialog else None)
                if allowed is not None and msg not in allowed:
                    st.seq_illegal = True
                    self.n_seq_illegal += 1
                self.last_res_t = None
                if msg == "CableCheckReq" and self.cablecheck_t0 is None:
                    self.cablecheck_t0 = t          # [V2G2-700]
                if msg == "PreChargeReq":
                    if self.precharge_t0 is None:
                        self.precharge_t0 = t       # [V2G2-704]
                    # [V2G2-525]: PreCharge only follows a CableCheckRes that
                    # said Finished, so the request itself is proof the cable
                    # check completed — needed because this firmware does not
                    # always populate EVSEProcessing on CableCheckRes.
                    if self.cablecheck_end_t is None and self.cablecheck_t0:
                        self.cablecheck_end_t = t
                if msg == "PowerDeliveryReq":
                    self.precharge_done = True      # [V2G2-707] threshold met
            elif msg.endswith("Res"):
                t_req = self.pending_req.pop(base, None)
                already = base in self.pending_breached
                self.pending_breached.discard(base)
                if t_req is not None:
                    lat = t - t_req
                    lim = iso.MSG_TIMEOUT_S.get(base + "Req")
                    if lim:
                        r = lat / lim
                        st.msg_timeout_ratio = r
                        if r > self.max_msg_ratio:
                            self.max_msg_ratio = r
                        if r >= 1.0 and not already:
                            self.n_msg_breach += 1
                            st.last_timeout_msg = base + "Req"
                    perf = iso.RES_PERFORMANCE_S.get(msg)
                    if perf:
                        st.msg_perf_ratio = lat / perf
                self.last_res_msg = msg
                self.last_res_t = t                 # [V2G2-441] timer starts
                self._seq_breach_armed = True
                # ...but only while a next request is still expected. After
                # SessionStopRes the EVCC terminates the connection
                # ([V2G2-508] -> [V2G2-025]) and after a FAILED response it
                # stops the session ([V2G2-438]) — in both cases no further
                # request is owed, so the sequence timer must stop. Leaving it
                # running made every cleanly-closed session whose PLC link
                # kept polling for another minute look like a 60 s stall
                # (measured: 2 of 120 clean sessions, both post-SessionStopRes).
                if msg == "SessionStopRes" or iso.rc_severity(ev.resp_code) >= 1.0:
                    self.last_res_t = None
                    self.ongoing_t0 = None
                # CableCheck finishes on OK + EVSEProcessing Finished [V2G2-703]
                if (msg == "CableCheckRes" and self.cablecheck_end_t is None
                        and iso.rc_severity(ev.resp_code) == 0.0
                        and ev.evse_processing == "Finished"):
                    self.cablecheck_end_t = t
                if msg == "SessionSetupRes" and self.session_setup_res_t is None:
                    self.session_setup_res_t = t

            # --- EVSEProcessing == Ongoing [V2G2-710..713] ----------------
            if ev.evse_processing == "Ongoing":
                if self.ongoing_t0 is None:
                    self.ongoing_t0 = t
            elif ev.evse_processing == "Finished":
                self.ongoing_t0 = None

            idx = iso.stage_index(msg)
            if idx is not None and idx > self.max_stage:
                self.max_stage = idx

            if ev.evse_max_v is not None:
                self.evse_max_v = ev.evse_max_v
            if ev.evse_max_i is not None:
                self.evse_max_i = ev.evse_max_i
            if ev.ev_target_v is not None:
                self.cur_target_v = ev.ev_target_v

        # --- timers evaluated at the current instant ----------------------
        # V2G_EVCC_Msg_Timer is running RIGHT NOW for every request still
        # unanswered, so report the worst outstanding one rather than only
        # scoring pairs that completed. Without this the standard's central
        # error case — [V2G2-438], the SECC simply stops answering — produces
        # no signal at all, because the response that would have closed the
        # timer never arrives. The PLC link-status poll keeps ticking at ~20 Hz
        # through a dead V2G stream, so this grows while the stall is happening.
        for pend, t_req in self.pending_req.items():
            lim = iso.MSG_TIMEOUT_S.get(pend + "Req")
            if not lim:
                continue
            r = (t - t_req) / lim
            if r > st.msg_timeout_ratio:
                st.msg_timeout_ratio = r
                if r >= 1.0:
                    st.last_timeout_msg = pend + "Req"
            if r >= 1.0 and pend not in self.pending_breached:
                self.pending_breached.add(pend)
                self.n_msg_breach += 1
        if st.msg_timeout_ratio > self.max_msg_ratio:
            self.max_msg_ratio = st.msg_timeout_ratio
        st.msg_timeout_ratio_max = self.max_msg_ratio
        st.n_msg_timeout_breach = self.n_msg_breach
        st.seq_gap_ratio, st.seq_timeout_ratio = self._sequence_ratios(t)
        st.n_seq_breach = self.n_seq_breach
        st.n_seq_illegal = self.n_seq_illegal

        if self.ongoing_t0 is not None:
            span = t - self.ongoing_t0
            st.ongoing_ratio = span / iso.ONGOING_TIMEOUT_S
            st.ongoing_perf_breach = span >= iso.ONGOING_PERFORMANCE_S
            st.in_ongoing = True
        else:
            st.ongoing_ratio = 0.0
            st.ongoing_perf_breach = False
            st.in_ongoing = False

        # [V2G2-446..449] runs from D-LINK_READY to SessionSetupRes. Only
        # meaningful when this capture actually contains the opening of the
        # dialog; a ring file that resumes mid-charge has no setup to time.
        if not self.n_dialog or self.link_ready_t is None:
            span = 0.0
        elif self.session_setup_res_t is not None:
            span = self.session_setup_res_t - self.link_ready_t
        else:
            span = t - self.link_ready_t          # still waiting, grows live
        st.comm_setup_ratio = span / iso.COMM_SETUP_TIMEOUT_S

        if self.cablecheck_t0 is None:
            st.cablecheck_ratio = 0.0
        else:
            # [V2G2-700..702]: one timer per communication session, started at
            # the first CableCheckReq and stopped when the cable check
            # finishes. Once stopped the ratio freezes — it is a record of how
            # close that cable check came to the 40 s limit, not a clock that
            # keeps running for the rest of the charge.
            end = self.cablecheck_end_t if self.cablecheck_end_t else t
            st.cablecheck_ratio = (end - self.cablecheck_t0) / iso.CABLECHECK_TIMEOUT_S
        st.cablecheck_breach = (self.cablecheck_end_t is None
                                and st.cablecheck_ratio >= 1.0)

        if self.precharge_t0 is None or self.precharge_done:
            st.precharge_ratio = 0.0
            st.precharge_breach = False
        else:
            st.precharge_ratio = (t - self.precharge_t0) / iso.PRECHARGE_TIMEOUT_S
            st.precharge_breach = st.precharge_ratio >= 1.0

        st.stage_frac = (max(self.max_stage, 0)
                         / (len(iso.DC_STAGE_ORDER) - 1.0))
        st.stage_name = (iso.DC_STAGE_ORDER[self.max_stage]
                         if self.max_stage >= 0 else "")
        cur = iso.stage_index(ev.msg) if ev.kind == "v2g" else None
        # A drop back to an earlier stage is legal only as renegotiation
        # ([V2G2-686]/[V2G2-794]: PowerDelivery(Renegotiate) ->
        # ChargeParameterDiscovery), which the successor table already allows.
        st.stage_regress = bool(cur is not None and cur < self.max_stage
                                and st.seq_illegal)

        st.rc_sev = iso.rc_severity(ev.resp_code)
        st.evse_status_sev = iso.EVSE_STATUS_SEVERITY.get(ev.evse_status, 0.0)
        st.isolation_sev = iso.ISOLATION_SEVERITY.get(ev.isolation, 0.0)
        st.notification_sev = iso.NOTIFICATION_SEVERITY.get(ev.notification, 0.0)
        st.ev_err_sev = iso.ev_error_severity(ev.ev_err)

        st.v_over_evse_max = 0.0
        st.i_over_evse_max = 0.0
        if ev.evse_v is not None and self.evse_max_v:
            st.v_over_evse_max = ev.evse_v / self.evse_max_v - 1.0
        if ev.evse_i is not None and self.evse_max_i:
            st.i_over_evse_max = ev.evse_i / self.evse_max_i - 1.0

        # PreCharge ends when the EVSE output has been adjusted to the RESS
        # voltage [V2G2-705]. Every pre-charge starts with a huge gap (output
        # ramps from 0 V to ~400 V), so the gap alone says nothing — what
        # matters is still being far out with the 7 s timer half gone. Below
        # the halfway mark this feature stays at 0.
        st.precharge_v_gap_ratio = 0.0
        if (self.precharge_t0 is not None and not self.precharge_done
                and ev.evse_v is not None and self.cur_target_v
                and st.precharge_ratio >= 0.5):
            band = max(20.0, 0.05 * self.cur_target_v)
            st.precharge_v_gap_ratio = abs(self.cur_target_v - ev.evse_v) / band

        # A second dialog inside one session means the first one died: the
        # standard has no "restart" transition, the only way back to
        # supportedAppProtocolReq/SessionSetupReq is a terminated session.
        st.n_redialog = max(0, self.n_dialog - 1)
        return st
