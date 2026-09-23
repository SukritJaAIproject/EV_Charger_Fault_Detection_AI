"""Normative constants and tables from ISO 15118-2:2014, clauses 8.7 and 8.8.

Why this file exists
--------------------
The fleet speaks DIN 70121 (`urn:din:70121:2012:MsgDef`), the German
predecessor of ISO 15118-2 — but ~19 % of the observed `supportedAppProtocolReq`
offers also carry `urn:iso:15118:2:2013:MsgDef`, and the DC message set,
state machine and timing model are the same shape in both. ISO 15118-2 is the
document that actually *publishes numbers*: how long each request may go
unanswered, how long a sequence may stall, how long CableCheck and PreCharge
may run, and which request may legally follow which response.

Everything here is transcribed from the standard, not invented, so that the
detector's thresholds are auditable against a clause number rather than being
hand-tuned. Where a value is a *Timeout* the standard says the party shall
terminate the session; where it is a *Performance Time* the party is merely
out of spec (clause 8.7.1) — the two are kept apart deliberately, because on
real hardware performance times are breached constantly and timeouts are not.

Message names are the DIN 70121 spellings seen on the wire. ISO renames three
of them (see ``ISO_NAME``); the timing values are keyed by the DIN spelling so
lookups work directly against the telemetry.

References (clause / table / requirement ids as printed in the standard):
  Table 109   per-message V2G_EVCC_Msg_Timeout and V2G_SECC_Msg_Performance_Time,
              V2G_EVCC_Sequence_Performance_Time, V2G_SECC_Sequence_Timeout,
              V2G_EVCC_Ongoing_Timeout, V2G_SECC_Ongoing_Performance_Time
  Table 111   communication-setup, CableCheck and PreCharge timers
  8.7.2.2/.3  [V2G2-436..445]  message and sequence timer handling
  8.7.3.2/.3  [V2G2-446..449] [V2G2-714..716]  communication setup
  8.7.3.4/.5  [V2G2-710..713]  EVSEProcessing == Ongoing
  8.7.3.6/.7  [V2G2-700..707]  CableCheck and PreCharge
  8.8.4.2.3   [V2G2-524..535] [V2G2-599] [V2G2-617..620] [V2G2-790..794]
              the DC EVCC state machine of Figure 102
  8.8.4.2.3   [V2G2-880]  DC_EVSEStatusCodes without explicit requirements are
              informational and shall not influence the charging process
"""

# --------------------------------------------------------------------------
# message naming: DIN 70121 (on the wire) <-> ISO 15118-2 (in the standard)
# --------------------------------------------------------------------------
ISO_NAME = {
    "ServicePaymentSelectionReq": "PaymentServiceSelectionReq",
    "ServicePaymentSelectionRes": "PaymentServiceSelectionRes",
    "ContractAuthenticationReq": "AuthorizationReq",
    "ContractAuthenticationRes": "AuthorizationRes",
}
DIN_NAME = {v: k for k, v in ISO_NAME.items()}

# --------------------------------------------------------------------------
# Table 109 — V2G_EVCC_Msg_Timeout(MessageType), seconds.
# Exceeding it is an ERROR: the EVCC stops the communication session
# ([V2G2-438], and per-message [V2G2-524] [V2G2-526] [V2G2-532] [V2G2-534]).
# --------------------------------------------------------------------------
MSG_TIMEOUT_S = {
    "supportedAppProtocolReq": 2.0,
    "SessionSetupReq": 2.0,
    "ServiceDiscoveryReq": 2.0,
    "ServiceDetailReq": 5.0,
    "ServicePaymentSelectionReq": 2.0,      # ISO: PaymentServiceSelectionReq
    "PaymentDetailsReq": 5.0,
    "ContractAuthenticationReq": 2.0,       # ISO: AuthorizationReq
    "ChargeParameterDiscoveryReq": 2.0,
    "ChargingStatusReq": 2.0,               # AC only
    "MeteringReceiptReq": 2.0,
    "PowerDeliveryReq": 5.0,
    "CableCheckReq": 2.0,
    "PreChargeReq": 2.0,
    "CurrentDemandReq": 0.25,
    "WeldingDetectionReq": 2.0,
    "SessionStopReq": 2.0,
    "CertificateInstallationReq": 5.0,
    "CertificateUpdateReq": 5.0,
}

# --------------------------------------------------------------------------
# Table 109 — V2G_SECC_Msg_Performance_Time(MessageType), seconds.
# Exceeding it is NOT an error by itself (8.7.1 NOTE): the SECC is slow, and
# the probability of the EVCC timing out is high. Keyed by response name.
# --------------------------------------------------------------------------
RES_PERFORMANCE_S = {
    "supportedAppProtocolRes": 1.5,
    "SessionSetupRes": 1.5,
    "ServiceDiscoveryRes": 1.5,
    "ServiceDetailRes": 4.5,
    "ServicePaymentSelectionRes": 1.5,
    "PaymentDetailsRes": 4.5,
    "ContractAuthenticationRes": 1.5,
    "ChargeParameterDiscoveryRes": 1.5,
    "ChargingStatusRes": 1.5,
    "MeteringReceiptRes": 1.5,
    "PowerDeliveryRes": 4.5,
    "CableCheckRes": 1.5,
    "PreChargeRes": 1.5,
    "CurrentDemandRes": 0.025,
    "WeldingDetectionRes": 1.5,
    "SessionStopRes": 1.5,
    "CertificateInstallationRes": 4.5,
    "CertificateUpdateRes": 4.5,
}

# --- Table 109, sequence and ongoing timers -------------------------------
SEQ_PERFORMANCE_S = 40.0     # V2G_EVCC_Sequence_Performance_Time
SEQ_TIMEOUT_S = 60.0         # V2G_SECC_Sequence_Timeout   [V2G2-443] -> stop
ONGOING_TIMEOUT_S = 60.0     # V2G_EVCC_Ongoing_Timeout    [V2G2-711] -> stop
ONGOING_PERFORMANCE_S = 55.0  # V2G_SECC_Ongoing_Performance_Time [V2G2-713]

# --- Table 111, setup / cable check / pre charge --------------------------
COMM_SETUP_TIMEOUT_S = 20.0       # V2G_EVCC_CommunicationSetup_Timeout
COMM_SETUP_PERFORMANCE_S = 18.0   # V2G_SECC_CommunicationSetup_Performance_Time
CABLECHECK_TIMEOUT_S = 40.0       # V2G_EVCC_CableCheck_Timeout   [V2G2-700..702]
CABLECHECK_PERFORMANCE_S = 38.0   # V2G_SECC_CableCheck_Performance_Time
PRECHARGE_TIMEOUT_S = 7.0         # V2G_EVCC_PreCharge_Timeout    [V2G2-704..706]
PRECHARGE_PERFORMANCE_S = 5.0     # V2G_SECC_PreCharge_Performance_Time

# --------------------------------------------------------------------------
# Figure 102 / clause 8.8.4.2.3 — the DC EVCC state machine.
#
# Keyed by the response just received; the value is the set of requests the
# EVCC may legally send next. Anything else means the dialog left the
# normative sequence, which is exactly what FAILED_SequenceError is for.
# Self-loops are legal where the standard says so: CableCheck while
# EVSEProcessing is 'Ongoing' [V2G2-617], PreCharge until the voltage
# threshold is met [V2G2-618], CurrentDemand [V2G2-531], WeldingDetection
# [V2G2-620].
#
# ServiceDetail / PaymentDetails / CertificateInstallation / CertificateUpdate
# are kept as legal successors even though DIN 70121 never uses them: their
# absence is not an error, only their presence in the wrong place would be.
# --------------------------------------------------------------------------
DC_NEXT_REQ = {
    "": ("supportedAppProtocolReq", "SessionSetupReq"),
    "supportedAppProtocolRes": ("SessionSetupReq",),
    "SessionSetupRes": ("ServiceDiscoveryReq",),
    "ServiceDiscoveryRes": ("ServiceDetailReq", "ServicePaymentSelectionReq"),
    "ServiceDetailRes": ("ServiceDetailReq", "ServicePaymentSelectionReq"),
    "ServicePaymentSelectionRes": (
        "ContractAuthenticationReq", "PaymentDetailsReq",
        "CertificateInstallationReq", "CertificateUpdateReq"),
    "CertificateInstallationRes": ("PaymentDetailsReq",
                                   "ContractAuthenticationReq"),
    "CertificateUpdateRes": ("PaymentDetailsReq", "ContractAuthenticationReq"),
    "PaymentDetailsRes": ("ContractAuthenticationReq",),
    # [V2G2-504] re-poll authorisation while EVSEProcessing == Ongoing
    "ContractAuthenticationRes": ("ContractAuthenticationReq",
                                  "ChargeParameterDiscoveryReq"),
    # [V2G2-506] re-poll parameter discovery while Ongoing; [V2G2-599] -> cable check
    "ChargeParameterDiscoveryRes": ("ChargeParameterDiscoveryReq",
                                    "CableCheckReq"),
    "CableCheckRes": ("CableCheckReq", "PreChargeReq"),          # 617 / 525
    "PreChargeRes": ("PreChargeReq", "PowerDeliveryReq"),        # 618 / 528
    # after PowerDelivery(Start) -> CurrentDemand [V2G2-530];
    # after PowerDelivery(Stop)  -> WeldingDetection [V2G2-533] or
    #                               SessionStop [V2G2-619];
    # after PowerDelivery(Renegotiate) -> ChargeParameterDiscovery
    "PowerDeliveryRes": ("CurrentDemandReq", "WeldingDetectionReq",
                         "SessionStopReq", "ChargeParameterDiscoveryReq"),
    "CurrentDemandRes": ("CurrentDemandReq", "MeteringReceiptReq",
                         "PowerDeliveryReq"),                    # 531/790/527/686
    "MeteringReceiptRes": ("CurrentDemandReq", "PowerDeliveryReq"),  # 792/793/794
    "WeldingDetectionRes": ("WeldingDetectionReq", "SessionStopReq"),  # 620/535
    "SessionStopRes": (),                                        # terminal
}

# Ordered DC progress states, used as a monotonic "how far did we get" signal.
DC_STAGE_ORDER = (
    "supportedAppProtocol", "SessionSetup", "ServiceDiscovery",
    "ServicePaymentSelection", "ContractAuthentication",
    "ChargeParameterDiscovery", "CableCheck", "PreCharge",
    "PowerDelivery", "CurrentDemand", "WeldingDetection", "SessionStop",
)
DC_STAGE_INDEX = {name: i for i, name in enumerate(DC_STAGE_ORDER)}

# The terminal sequence the standard prescribes for a clean DC stop:
# PowerDelivery(Stop) -> [WeldingDetection]* -> SessionStop  [V2G2-533/535/619]
CLEAN_CLOSE_TAIL = ("PowerDeliveryReq", "SessionStopReq")


def base_name(msg):
    """'CurrentDemandRes' -> 'CurrentDemand'; non-V2G names pass through."""
    if msg.endswith("Req") or msg.endswith("Res"):
        return msg[:-3]
    return msg


def stage_index(msg):
    """-> position in DC_STAGE_ORDER, or None for a message outside the flow."""
    return DC_STAGE_INDEX.get(base_name(msg))


# --------------------------------------------------------------------------
# ResponseCode semantics (clause 8.8.3, Table 112).
#
# 1.0 = the standard requires the session to be terminated with an error.
# 0.5 = negotiated-but-degraded (an OK_ variant that reports a limitation).
# 0.0 = success.
# The DIN dialect also emits the bare 'FAILED' and the SAP-specific
# CamelCase 'Failed_NoNegotiation', so matching is case-insensitive on the
# FAILED prefix rather than against a closed set.
# --------------------------------------------------------------------------
RC_OK_DEGRADED = {
    "OK_NEWSESSIONESTABLISHED": 0.0,
    "OK_OLDSESSIONJOINED": 0.0,
    "OK_SUCCESSFULNEGOTIATION": 0.0,
    "OK_CERTIFICATEEXPIRESSOON": 0.5,
}


def rc_severity(resp_code):
    """ResponseCode text -> 0.0 (ok) .. 1.0 (session must be terminated)."""
    if not resp_code:
        return 0.0
    u = resp_code.upper()
    if u.startswith("FAILED"):
        return 1.0
    return RC_OK_DEGRADED.get(u, 0.0)


# --------------------------------------------------------------------------
# DC_EVSEStatusCode severity.
#
# [V2G2-880]: status codes without explicit requirements are informational and
# shall not influence the charging process; the expected values during a
# healthy session are EVSE_Ready and EVSE_IsolationMonitoringActive.
# EVSE_Shutdown is how a normal, EVSE-initiated stop is announced, so it is a
# context signal (0.3), not a fault — matching what the fleet actually does.
# --------------------------------------------------------------------------
EVSE_STATUS_SEVERITY = {
    "EVSE_NotReady": 0.1,
    "EVSE_Ready": 0.0,
    "EVSE_IsolationMonitoringActive": 0.0,
    "EVSE_Shutdown": 0.3,
    "EVSE_UtilityInterruptEvent": 0.6,
    "EVSE_EmergencyShutdown": 1.0,
    "EVSE_Malfunction": 1.0,
}

# isolationLevelType (clause 8.5). 'Invalid' is the normal pre-measurement
# state and 'Warning' occurs transiently in healthy sessions on this fleet;
# only 'Fault' is hard.
ISOLATION_SEVERITY = {
    "Invalid": 0.0, "No_IMD": 0.0, "Valid": 0.0,
    "Warning": 0.4, "Fault": 1.0,
}

# EVSENotificationType (clause 8.5). Both non-None values are *requests to act*
# and legal in a healthy session; they mark a change of intent, not a fault.
NOTIFICATION_SEVERITY = {"None": 0.0, "StopCharging": 0.4, "ReNegotiation": 0.3}


def ev_error_severity(ev_err):
    """DC_EVErrorCode -> 0.0 (no error / no data) .. 1.0 (EV reports a fault)."""
    if not ev_err or ev_err in ("NO_ERROR", "NoData"):
        return 0.0
    return 1.0


PROTOCOL_ISO = "urn:iso:15118:2:2013:MsgDef"
PROTOCOL_DIN = "urn:din:70121:2012:MsgDef"
