"""The ISO 15118-2:2014 rule layer, shared by every competitor in the ISO arm.

Each rule is a criterion the standard itself publishes, so its threshold is a
clause number rather than a number found by staring at this fleet's data. The
list is deliberately short: a rule only earns a place here if breaching it
means the standard *requires* a party to terminate the communication session,
and if it does not fire on healthy sessions of this fleet.

Rules that the fleet-tuned baseline already has in some ad-hoc form
(ResponseCode FAILED, EVSE_Malfunction / EVSE_EmergencyShutdown, isolation
Fault, EVErrorCode, CableCheck over 40 s) are kept here too so the ISO arm is
self-contained, but they are not what the experiment is about. The rules the
baseline has NO equivalent of are marked NEW — those are what attaching the
standard actually adds:

  NEW  EVSEProcessing stuck at 'Ongoing' past V2G_SECC_Ongoing_Performance_Time
       [V2G2-712/713], which obliges the SECC to answer FAILED and stop, on the
       way to V2G_EVCC_Ongoing_Timeout [V2G2-710/711].
  NEW  V2G_SECC_Sequence_Timeout exceeded between a response and the next
       request [V2G2-443] — the SECC must stop the session.
  NEW  V2G_EVCC_CommunicationSetup_Timeout exceeded before SessionSetupRes
       [V2G2-446/448].
  NEW  a second dialog opening inside one session: clause 8.8.1 says an EVCC
       establishes a new V2G Communication Session "after an error", and the
       standard offers no other route back to supportedAppProtocolReq.

Two further ISO criteria were tried and rejected as hard rules because this
fleet breaks them while perfectly healthy — see the constants block. They
survive as features, which is the honest place for "non-conformant but not
broken".
"""
from core import iso15118 as iso
from core.schema import (FAULT_PROTOCOL, FAULT_EVSE, FAULT_ISOLATION,
                         FAULT_EV_ERROR, FAULT_ABORT, FAULT_FREEZE)

# Where a hard rule trips, as a fraction of the standard's own limit. Speaking
# earlier than the standard does would mean inventing a threshold, which is the
# thing this arm exists not to do — so the only sub-1.0 value here is itself a
# published limit: V2G_SECC_Ongoing_Performance_Time (55 s) is the point where
# [V2G2-713] already obliges the SECC to answer FAILED and stop the session,
# i.e. 55/60 of the EVCC's V2G_EVCC_Ongoing_Timeout.
ONGOING_TRIP = 55.0 / 60.0
SEQ_TRIP = 1.0              # 60 s V2G_SECC_Sequence_Timeout [V2G2-443]

# --- rules the standard states but this fleet demonstrably breaks while
# --- healthy, so they are conformance findings and NOT fault detectors:
#
# Fig.102 / [V2G2-593]: the only legal successors of CurrentDemandRes are
#   CurrentDemandReq and PowerDeliveryReq — the EV must send
#   PowerDelivery(Stop) before SessionStopReq. Measured on this fleet: EVs go
#   straight from the CurrentDemand loop to SessionStopReq in sessions that
#   complete perfectly, and the EVSE answers OK instead of the
#   FAILED_SequenceError that [V2G2-459] requires. Kept as the feature
#   iso_seq_illegal so the learned layers can weigh it in context.
#
# [V2G2-704/706]: V2G_EVCC_PreCharge_Timeout is 7 s. Measured: clean sessions
#   on this fleet run PreCharge past 19 s with the output still far from the
#   EV target and then charge normally. Kept as iso_precharge_ratio and as
#   graded evidence in the agent architectures.


def iso_alert(fs):
    """-> (confidence, reason, fault_family) for the first ISO rule that trips.

    ``fs`` is the shared FeatureState; ``fs.iso`` carries the conformance view.
    Ordered most-certain first, so the reason string names the strongest piece
    of evidence available at this instant.
    """
    i = fs.iso
    if i is None:
        return None

    # --- the standard's own hard error criteria -------------------------
    if i.rc_sev >= 1.0:
        return (1.0, f"ISO 8.8.3: ResponseCode {fs.resp_code} -> terminate",
                FAULT_PROTOCOL)
    if i.evse_status_sev >= 1.0:
        return (1.0, f"ISO Table 98: {fs.evse_status}", FAULT_EVSE)
    if i.isolation_sev >= 1.0:
        return (1.0, "ISO 8.5: EVSEIsolationStatus Fault", FAULT_ISOLATION)
    if i.ev_err_sev >= 1.0:
        return (1.0, f"ISO 8.5: EVErrorCode {fs.ev_err}", FAULT_EV_ERROR)

    # --- NEW: timers the baseline has no concept of ----------------------
    if i.ongoing_ratio >= ONGOING_TRIP:
        s = i.ongoing_ratio * iso.ONGOING_TIMEOUT_S
        return (0.95, f"[V2G2-711] EVSEProcessing Ongoing {s:.0f}s "
                f"(timeout {iso.ONGOING_TIMEOUT_S:.0f}s)", FAULT_FREEZE)
    if i.seq_timeout_ratio >= SEQ_TRIP:
        s = i.seq_timeout_ratio * iso.SEQ_TIMEOUT_S
        return (0.95, f"[V2G2-443] no request for {s:.0f}s "
                f"(V2G_SECC_Sequence_Timeout {iso.SEQ_TIMEOUT_S:.0f}s)",
                FAULT_FREEZE)
    if i.comm_setup_ratio >= 1.0:
        return (0.9, f"[V2G2-448] no SessionSetupRes within "
                f"{iso.COMM_SETUP_TIMEOUT_S:.0f}s of link-up", FAULT_ABORT)
    if i.cablecheck_breach:
        s = i.cablecheck_ratio * iso.CABLECHECK_TIMEOUT_S
        return (0.9, f"[V2G2-702] CableCheck {s:.0f}s "
                f"(timeout {iso.CABLECHECK_TIMEOUT_S:.0f}s)", FAULT_FREEZE)
    # 8.8.1: "Within a Charging Session, an EVCC can establish a new V2G
    # Communication Session after an error" — the standard offers no other
    # route back to supportedAppProtocolReq, so a second dialog is a record
    # that the first one was terminated.
    if i.n_redialog >= 1:
        return (0.85, f"ISO 8.8.1: dialog reopened {i.n_redialog}x "
                "(previous session was terminated)", FAULT_ABORT)
    if i.msg_timeout_ratio >= 1.0:
        return (0.8, f"Table 109: {i.last_timeout_msg} unanswered for "
                f"{i.msg_timeout_ratio:.1f}x its timeout", FAULT_FREEZE)
    return None
