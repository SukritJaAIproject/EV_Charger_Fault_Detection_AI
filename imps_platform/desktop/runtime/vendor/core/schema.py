"""Shared data structures for the EV charger fault-detection competition."""
from dataclasses import dataclass, field
from typing import Optional


# Fault families (ground truth taxonomy, DIN 70121 semantics)
FAULT_PROTOCOL = "PROTOCOL_FAILED"        # ResponseCode FAILED_*
FAULT_EVSE = "EVSE_FAULT"                 # EVSE_Malfunction / EVSE_EmergencyShutdown
FAULT_ISOLATION = "ISOLATION_FAULT"       # EVSEIsolationStatus == Fault
FAULT_EV_ERROR = "EV_ERROR"               # EVErrorCode != NO_ERROR
FAULT_ABORT = "SESSION_ABORT"             # no graceful close / TCP RST / re-SLAC
FAULT_SLAC = "SLAC_FAILURE"               # PLC matching never led to V2G session
FAULT_FREEZE = "COMM_FREEZE"              # multi-second stall mid power delivery
FAULT_NO_POWER = "NO_POWER_DELIVERED"     # committed to charging, closed cleanly,
                                          # never reached CurrentDemand
FAULT_PROCESSING = "EVSE_PROCESSING_STALL" # Ongoing never reached Finished
FAULT_PRECHARGE = "PRECHARGE_FAULT"        # ramp failed to converge in time

QUALITY_DECODE_ERROR = "DECODE_ERROR"       # invalidates electrical evidence;
                                             # deliberately not a fault family

ALL_FAULTS = [FAULT_PROTOCOL, FAULT_EVSE, FAULT_ISOLATION, FAULT_EV_ERROR,
              FAULT_ABORT, FAULT_SLAC, FAULT_FREEZE, FAULT_NO_POWER,
              FAULT_PROCESSING, FAULT_PRECHARGE]


@dataclass
class Event:
    """One telemetry event from the charger stream (parsed CSV row)."""
    t: float
    kind: str                      # v2g | sdp | hpav | tcp
    msg: str
    session: str = ""
    resp_code: str = ""
    evse_status: str = ""
    isolation: str = ""
    notification: str = ""
    ev_err: str = ""
    soc: Optional[float] = None
    evse_v: Optional[float] = None
    evse_i: Optional[float] = None
    ev_target_v: Optional[float] = None
    ev_target_i: Optional[float] = None
    ev_max_v: Optional[float] = None
    ev_max_i: Optional[float] = None
    evse_max_v: Optional[float] = None
    evse_max_i: Optional[float] = None
    remaining_full_min: Optional[float] = None
    remaining_bulk_min: Optional[float] = None
    ev_ready: str = ""
    charge_complete: str = ""
    bulk_complete: str = ""
    evse_processing: str = ""
    limit_achieved: str = ""
    validation: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Alert:
    """A detector raising its hand: `I see a problem`."""
    t: float                       # stream time when raised
    detector: str
    confidence: float              # 0..1
    reason: str                    # human-readable evidence
    fault_guess: str = ""          # optional fault family guess


@dataclass
class SessionLabel:
    """Ground truth for one charging session."""
    session_key: str               # station/connector/idx
    station: str
    connector: str
    t_start: float
    t_end: float
    n_events: int
    reached_current_demand: bool
    graceful_close: bool
    faults: list = field(default_factory=list)   # [(t, fault_family, detail)]
    # A censored session is neither positive nor negative: the capture ended
    # before the normative envelope could establish what happened.  New label
    # profiles can exclude it without rewriting the immutable published labels.
    censored: bool = False
    censor_reason: str = ""
    quality_flags: list = field(default_factory=list)
    label_profile: str = "strict"

    @property
    def is_faulty(self) -> bool:
        return len(self.faults) > 0

    @property
    def first_fault_t(self) -> Optional[float]:
        return min(f[0] for f in self.faults) if self.faults else None

    @property
    def first_fault_family(self) -> Optional[str]:
        return min(self.faults, key=lambda f: f[0])[1] if self.faults else None

