"""Ground-truth labeling of charging sessions (DIN 70121 semantics).

A session is FAULTY if it contains at least one hard fault marker:

  PROTOCOL_FAILED   ResponseCode FAILED_*
  EVSE_FAULT        EVSEStatusCode EVSE_Malfunction / EVSE_EmergencyShutdown
  ISOLATION_FAULT   EVSEIsolationStatus == Fault
  EV_ERROR          EVErrorCode not in {NO_ERROR}
  SESSION_ABORT     V2G dialog began but never closed with SessionStop
                    (stream death, TCP RST, or re-SLAC mid-session)
  SLAC_FAILURE      PLC matching attempted, no V2G dialog ever established,
                    or pairing took over 60 s before one was
  COMM_FREEZE       strict: >5 s delivery gap / CableCheck >60 s;
                    iso_reviewed: request/sequence timers / CableCheck >40 s
  NO_POWER_DELIVERED  the EV asked for charge parameters and the session then
                    closed properly without ever reaching CurrentDemand - a
                    charge that was attempted in earnest and delivered nothing
  EVSE_PROCESSING_STALL  machine phase remained Ongoing for 60 s
  PRECHARGE_FAULT   10 s pre-charge with no voltage convergence

Deliberately NOT faults (they are normal or mere precursors):
  EVSE_Shutdown + EVSENotification=Stop (user/charger initiated stop),
  isolation Warning, ChargingComplete, graceful SessionStop.

Fault time = the moment the problem is manifest in the stream, so detector
lead time is measured against an objective anchor.

``EV_AI_LABEL_PROFILE=strict`` (default) preserves the pre-continuation code
path. It is not identical to the older published ``index.json`` snapshot,
which predates the existing ``NO_POWER_DELIVERED`` rule and 13 SLAC
reclassifications. ``iso_reviewed`` applies the adjudicated rulebook proposals
and marks unobservable outcomes ``censored`` instead of silently treating them
as clean.
"""
from core.schema import (SessionLabel, FAULT_PROTOCOL, FAULT_EVSE,
                         FAULT_ISOLATION, FAULT_EV_ERROR, FAULT_ABORT,
                         FAULT_SLAC, FAULT_FREEZE, FAULT_NO_POWER,
                         FAULT_PROCESSING, FAULT_PRECHARGE,
                         QUALITY_DECODE_ERROR)

import json
import os

from core import iso15118 as iso

LABEL_PROFILE = os.environ.get("EV_AI_LABEL_PROFILE", "strict").strip().lower()
if LABEL_PROFILE not in ("strict", "iso_reviewed"):
    raise ValueError("EV_AI_LABEL_PROFILE must be 'strict' or 'iso_reviewed', "
                     f"got {LABEL_PROFILE!r}")
ISO_REVIEWED = LABEL_PROFILE == "iso_reviewed"

FREEZE_S = 5.0
CABLECHECK_STUCK_S = (iso.CABLECHECK_TIMEOUT_S
                      if ISO_REVIEWED else 60.0)
PRECHARGE_LABEL_S = 10.0
# Pairing the powerline takes 8.6 s at the fleet median and never more than
# 40.8 s in 273 sampled sessions that went on to charge successfully, so a
# minute of it is a degraded link even when V2G eventually opens. Measured
# blast radius: 0.1% of currently-clean sessions.
SLAC_SLOW_S = 60.0
BENIGN_EV_ERR = {"", "NO_ERROR"}
ISO_BENIGN_EV_ERR = BENIGN_EV_ERR | {"NODATA"}
RESERVED_EV_ERR = {"RESERVED_A", "RESERVED_B", "RESERVED_C"}
SLAC_MIN_ROWS = 3

# Require positive evidence before calling a session aborted. Default on; set
# EV_AI_STRICT_ABORT=0 to reproduce the legacy abort behaviour used by the
# 2026-09-09 labelling run (not the entire historical label snapshot).
STRICT_ABORT = os.environ.get("EV_AI_STRICT_ABORT", "1") == "1"

# How many events must still arrive after a timer expires before we believe the
# link was alive to observe it. The PLC link-status poll runs at ~20 Hz through
# a dead V2G stream, so a genuine stall keeps producing rows; a capture that
# simply ended produces none.
ALIVE_AFTER = 20
# The rows must arrive close to the deadline.  Counting packets from an
# unrelated later capture segment would turn data loss into positive evidence.
ALIVE_WINDOW_S = 10.0


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes")


def _extra(row):
    value = row.get("extra") or {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _continuous(rows, start, end, min_events=10, max_gap=1.0):
    """Whether packets prove the capture remained alive over an interval."""
    if end <= start:
        return False
    ts = [float(r["t"]) for r in rows if start <= r["t"] <= end]
    if len(ts) < min_events:
        return False
    points = [float(start)] + ts + [float(end)]
    return max(b - a for a, b in zip(points, points[1:])) <= max_gap


def _iso_timing_faults(rows, v2g):
    """Hard ISO timer breaches for the reviewed label profile.

    The pre-review strict profile's flat 5 s gap remains untouched.  This
    profile measures the quantity each timer actually owns: request->response,
    response->next request, and the first Ongoing->Finished interval.  A fleet
    margin determines whether a label is admitted, but the fault timestamp is
    the standard's deadline.
    """
    out = []
    pending = {}
    last_res_t = None
    ongoing_t0 = {}

    def add(t, fam, detail):
        out.append((float(t), fam, detail))

    for r in v2g:
        msg, t = r["msg"], r["t"]
        if msg.endswith("Req"):
            if (last_res_t is not None
                    and msg not in ("supportedAppProtocolReq", "SessionSetupReq")):
                gap = t - last_res_t
                if (gap >= iso.SEQ_TIMEOUT_S
                        and _continuous(rows, last_res_t,
                                        last_res_t + iso.SEQ_TIMEOUT_S,
                                        min_events=100, max_gap=2.0)):
                    add(last_res_t + iso.SEQ_TIMEOUT_S, FAULT_FREEZE,
                        f"no next request for {gap:.1f}s "
                        "[V2G2-443 SECC sequence timeout]")
            pending[msg[:-3]] = t
            last_res_t = None
        elif msg.endswith("Res"):
            base = msg[:-3]
            req_t = pending.pop(base, None)
            lim = iso.MSG_TIMEOUT_S.get(base + "Req")
            if req_t is not None and lim is not None:
                latency = t - req_t
                label_margin = max(2.0 * lim, 1.5)
                if (latency >= label_margin
                        and _continuous(rows, req_t, t,
                                        min_events=10, max_gap=1.0)):
                    add(req_t + lim, FAULT_FREEZE,
                        f"{base}Req unanswered for {latency:.2f}s "
                        f"(timeout {lim:g}s; label margin {label_margin:g}s)")
            last_res_t = t

            if msg in ("CableCheckRes", "ChargeParameterDiscoveryRes"):
                processing = str(r.get("evse_processing") or "")
                if processing == "Ongoing":
                    ongoing_t0.setdefault(msg, t)
                elif processing == "Finished":
                    t0 = ongoing_t0.pop(msg, None)
                    if (t0 is not None and t - t0 >= iso.ONGOING_TIMEOUT_S
                            and _continuous(rows, t0,
                                            t0 + iso.ONGOING_TIMEOUT_S,
                                            min_events=20, max_gap=5.0)):
                        add(t0 + iso.ONGOING_TIMEOUT_S, FAULT_PROCESSING,
                            f"{msg} Ongoing for {t - t0:.1f}s "
                            "[V2G2-711]")

    t_end = rows[-1]["t"]
    for base, req_t in pending.items():
        lim = iso.MSG_TIMEOUT_S.get(base + "Req")
        if lim is None:
            continue
        margin = max(2.0 * lim, 1.5)
        if (t_end - req_t >= margin
                and _continuous(rows, req_t + lim,
                                min(t_end, req_t + lim + ALIVE_WINDOW_S),
                                min_events=10, max_gap=1.0)):
            add(req_t + lim, FAULT_FREEZE,
                f"{base}Req unanswered past {lim:g}s timeout on live link")

    if (last_res_t is not None and t_end - last_res_t >= iso.SEQ_TIMEOUT_S
            and _continuous(rows, last_res_t,
                            last_res_t + iso.SEQ_TIMEOUT_S,
                            min_events=100, max_gap=2.0)):
        add(last_res_t + iso.SEQ_TIMEOUT_S, FAULT_FREEZE,
            "no next request for 60s [V2G2-443 SECC sequence timeout]")

    for msg, t0 in ongoing_t0.items():
        if (t_end - t0 >= iso.ONGOING_TIMEOUT_S
                and _continuous(rows, t0, t0 + iso.ONGOING_TIMEOUT_S,
                                min_events=20, max_gap=5.0)):
            add(t0 + iso.ONGOING_TIMEOUT_S, FAULT_PROCESSING,
                f"{msg} left Ongoing past 60s [V2G2-711]")
    return out


def _decode_quality(v2g):
    """Return data-quality flags; never turn decoder failures into faults."""
    voltage = ("evse_v", "ev_target_v", "ev_max_v", "evse_max_v")
    for r in v2g:
        if str(r.get("resp_code") or "").upper().startswith("FAILED"):
            continue
        for key in voltage:
            value = r.get(key)
            if value is not None and not 0.0 <= float(value) <= 1000.0:
                return [f"{QUALITY_DECODE_ERROR}:{key}={value}"]
        # Do not apply ISO's 0..400 A physical-value bound to this DIN fleet.
        # The audit found 436 otherwise-valid sessions whose advertised EV
        # maxima are 401..901 A. That is a dialect/range difference, not proof
        # of a multiplier decode error; enforcing it would invalidate real
        # high-current chargers. Voltage and SOC bounds are shared and remain
        # safe checks. See the proposal decision matrix.
        value = r.get("soc")
        if value is not None and not 0.0 <= float(value) <= 100.0:
            return [f"{QUALITY_DECODE_ERROR}:soc={value}"]
    return []


def _precharge_fault(rows, v2g):
    """Conservative 10 s pre-charge label with an explicit convergence gate."""
    start = next((r["t"] for r in v2g if r["msg"] == "PreChargeReq"), None)
    if start is None:
        return None
    deadline = start + PRECHARGE_LABEL_S
    end = next((r["t"] for r in v2g
                if r["t"] > start and r["msg"] == "PowerDeliveryReq"),
               max((r["t"] for r in v2g
                    if r["t"] >= start and r["msg"].startswith("PreCharge")),
                   default=start))
    if end <= deadline or not _continuous(
            rows, start, deadline, min_events=10, max_gap=2.0):
        return None
    measurements = []
    for r in v2g:
        if not start <= r["t"] <= deadline:
            continue
        target, present = r.get("ev_target_v"), r.get("evse_v")
        if target is not None and present is not None:
            measurements.append(abs(float(target) - float(present)))
    if len(measurements) < 2:
        return None
    initial, final = measurements[0], measurements[-1]
    # ISO publishes no voltage tolerance.  The 20 V / 50% band is therefore
    # explicitly a conservative data-quality heuristic, not an ISO constant.
    if final > 20.0 and final >= 0.5 * max(initial, 1.0):
        return (deadline, FAULT_PRECHARGE,
                f"PreCharge >{PRECHARGE_LABEL_S:g}s without convergence "
                f"(gap {initial:.1f}->{final:.1f}V)")
    return None


def _abort_evidence(rows, v2g):
    """-> (t, detail) for the first thing that positively shows the dialog broke.

    Every criterion here is something that had to HAPPEN — a timer the standard
    itself defines running out while the link was still delivering packets, or
    the EV reopening a dialog it could only reopen after an error (clause 8.8.1).
    None of them can be produced by a capture ending, which is the whole point.
    """
    def alive_after(t):
        return sum(1 for r in rows
                   if t < r["t"] <= t + ALIVE_WINDOW_S) >= ALIVE_AFTER

    best = None

    def offer(t, detail):
        nonlocal best
        if best is None or t < best[0]:
            best = (t, detail)

    # a request left unanswered past its own Table 109 timeout [V2G2-438]
    pending = {}
    last_res_t = None
    last_res_msg = ""
    ongoing_t0 = None
    ongoing_msg = None
    n_dialog = 0
    for r in v2g:
        msg, t = r["msg"], r["t"]
        if msg.endswith("Req"):
            base = msg[:-3]
            if ongoing_msg is not None and ongoing_msg != base + "Res":
                ongoing_t0 = None
                ongoing_msg = None
            # A dialog opens at supportedAppProtocolReq, or at SessionSetupReq
            # when the app-protocol handshake was not the thing that just
            # happened (some EVs skip it on a retry). Clause 8.8.1 offers no
            # route back here except through a session that was stopped.
            if (msg == "supportedAppProtocolReq"
                    or (msg == "SessionSetupReq"
                        and last_res_msg != "supportedAppProtocolRes")):
                n_dialog += 1
                if n_dialog > 1:
                    offer(t, "dialog reopened after an error [8.8.1] "
                             f"(#{n_dialog})")
            pending[base] = t
            if last_res_t is not None:
                gap = t - last_res_t
                if gap >= iso.SEQ_TIMEOUT_S:
                    offer(last_res_t + iso.SEQ_TIMEOUT_S,
                          f"no request for {gap:.0f}s [V2G2-443]")
            last_res_t = None
        elif msg.endswith("Res"):
            pending.pop(msg[:-3], None)
            last_res_t = t
            last_res_msg = msg
            processing = r.get("evse_processing")
            if processing == "Ongoing":
                # The ongoing timer belongs to one response phase.  Carrying
                # it into a later phase can manufacture a 60 s timeout even
                # though the earlier phase already completed.
                if ongoing_t0 is None or ongoing_msg != msg:
                    ongoing_t0 = t
                    ongoing_msg = msg
                elif t - ongoing_t0 >= iso.ONGOING_TIMEOUT_S:
                    offer(ongoing_t0 + iso.ONGOING_TIMEOUT_S,
                          f"EVSEProcessing Ongoing {t - ongoing_t0:.0f}s "
                          "[V2G2-711]")
            elif processing == "Finished" or (
                    ongoing_msg is not None and ongoing_msg != msg):
                ongoing_t0 = None
                ongoing_msg = None

    t_end = rows[-1]["t"]
    for base, t_req in pending.items():
        lim = iso.MSG_TIMEOUT_S.get(base + "Req")
        if lim and t_end - t_req >= lim and alive_after(t_req + lim):
            offer(t_req + lim,
                  f"{base}Req unanswered past its {lim}s timeout [V2G2-438]")
    if ongoing_t0 is not None and t_end - ongoing_t0 >= iso.ONGOING_TIMEOUT_S \
            and alive_after(ongoing_t0 + iso.ONGOING_TIMEOUT_S):
        offer(ongoing_t0 + iso.ONGOING_TIMEOUT_S,
              "EVSEProcessing left Ongoing past 60s [V2G2-711]")
    if last_res_t is not None and t_end - last_res_t >= iso.SEQ_TIMEOUT_S \
            and alive_after(last_res_t + iso.SEQ_TIMEOUT_S):
        offer(last_res_t + iso.SEQ_TIMEOUT_S,
              "no further request for 60s [V2G2-443]")
    return best


def label_session(skey, station, conn, rows):
    v2g = [r for r in rows if r["kind"] == "v2g"]
    slac = [r for r in rows if r["kind"] == "hpav"
            and ("SLAC" in r["msg"] or "ATTEN_CHAR" in r["msg"])]
    if not v2g and len(slac) < SLAC_MIN_ROWS:
        return None  # noise chunk, not a session

    faults = []
    quality_flags = _decode_quality(v2g) if ISO_REVIEWED else []
    censor_reason = ""

    def add(t, fam, detail):
        faults.append((float(t), fam, detail))

    # --- marker scan over V2G rows -------------------------------------
    first_cd_t = None
    last_cd_t = None
    stop_res_t = None
    stop_req_t = None
    cablecheck_t0 = None
    param_req_t = None          # the EV committing: "here is what I want"
    last_dc_t = None            # last message of the DC sequence before the stop
    invalid_isolation_after_cc = []
    charging_complete_seen = False
    stopcharging_seen = False
    for r in v2g:
        t, msg = r["t"], r["msg"]
        if msg.startswith("CurrentDemand"):
            if first_cd_t is None:
                first_cd_t = t
            last_cd_t = t
            charging_complete_seen |= _truthy(r.get("charge_complete"))
        elif msg == "CableCheckReq" and cablecheck_t0 is None:
            cablecheck_t0 = t
        elif msg == "ChargeParameterDiscoveryReq" and param_req_t is None:
            param_req_t = t
        elif msg == "SessionStopReq" and stop_req_t is None:
            stop_req_t = t
        if msg[:-3] in ("ChargeParameterDiscovery", "CableCheck", "PreCharge",
                        "PowerDelivery"):
            last_dc_t = t
        elif (msg == "SessionStopRes"
              and not r.get("resp_code", "").upper().startswith("FAILED")):
            stop_res_t = t
        stopcharging_seen |= str(r.get("notification") or "") == "StopCharging"
        rc = r.get("resp_code", "")
        failed_row = rc.upper().startswith("FAILED")
        if failed_row:   # includes SAP "Failed_NoNegotiation"
            add(t, FAULT_PROTOCOL, f"{msg}:{rc}")
        if ISO_REVIEWED and failed_row:
            # [V2G2-735/736]: payload fields on FAILED responses are filler.
            continue
        st = r.get("evse_status", "")
        if st in ("EVSE_Malfunction", "EVSE_EmergencyShutdown"):
            add(t, FAULT_EVSE, f"{msg}:{st}")
        isolation = r.get("isolation", "")
        if isolation == "Fault":
            add(t, FAULT_ISOLATION, f"{msg}:IsolationFault")
        elif (ISO_REVIEWED and isolation == "Invalid"
              and first_cd_t is not None):
            invalid_isolation_after_cc.append(t)
        ev_err = str(r.get("ev_err", "") or "")
        ev_err_u = ev_err.upper()
        if ISO_REVIEWED:
            if ev_err_u in RESERVED_EV_ERR:
                quality_flags.append(f"RESERVED_EV_ERROR:{ev_err}")
            elif ev_err_u not in ISO_BENIGN_EV_ERR:
                add(t, FAULT_EV_ERROR, f"{msg}:{ev_err}")
            elif ev_err_u == "NODATA" and first_cd_t is not None:
                add(t, FAULT_EV_ERROR, f"{msg}:NoData persisted into delivery")
        elif ev_err not in BENIGN_EV_ERR:
            add(t, FAULT_EV_ERROR, f"{msg}:{ev_err}")

    if ISO_REVIEWED and len(invalid_isolation_after_cc) >= 2:
        add(invalid_isolation_after_cc[1], FAULT_ISOLATION,
            "Isolation Invalid persisted into CurrentDemand")

    # --- CableCheck stuck ----------------------------------------------
    if cablecheck_t0 is not None:
        if ISO_REVIEWED:
            # A successful Finished response is the normative completion;
            # PreCharge is a safe fallback for DIN traces that omit the flag.
            cc_end = next((r["t"] for r in v2g
                           if r["t"] > cablecheck_t0
                           and ((r["msg"] == "CableCheckRes"
                                 and not str(r.get("resp_code") or "").upper()
                                 .startswith("FAILED")
                                 and r.get("evse_processing") == "Finished")
                                or r["msg"] == "PreChargeReq")), None)
        else:
            cc_end = next((r["t"] for r in v2g
                           if r["msg"] in ("PreChargeReq", "PowerDeliveryReq")
                           and r["t"] > cablecheck_t0), None)
        cc_last = max((r["t"] for r in v2g if r["msg"].startswith("CableCheck")),
                      default=cablecheck_t0)
        cc_span = (cc_end or cc_last) - cablecheck_t0
        continuity_ok = (not ISO_REVIEWED or _continuous(
            rows, cablecheck_t0, cablecheck_t0 + CABLECHECK_STUCK_S,
            min_events=20, max_gap=5.0))
        if cc_span > CABLECHECK_STUCK_S and continuity_ok:
            add(cablecheck_t0 + CABLECHECK_STUCK_S, FAULT_FREEZE,
                f"CableCheck stuck {cc_span:.0f}s")

    # --- freezes mid power delivery ------------------------------------
    # scan strictly inside the CurrentDemand loop: the closing handshake
    # (PowerDelivery stop -> WeldingDetection -> SessionStop) legitimately
    # takes multi-second pauses and must not count as a stall
    if (not ISO_REVIEWED and first_cd_t is not None
            and last_cd_t is not None):
        prev_t = None
        for r in v2g:
            if r["t"] < first_cd_t or r["t"] > last_cd_t:
                continue
            if prev_t is not None and (r["t"] - prev_t) > FREEZE_S:
                add(prev_t + FREEZE_S, FAULT_FREEZE,
                    f"stall {r['t']-prev_t:.1f}s in power delivery")
            prev_t = r["t"]

    if ISO_REVIEWED:
        for timing_fault in _iso_timing_faults(rows, v2g):
            add(*timing_fault)
        if not any(str(q).startswith(QUALITY_DECODE_ERROR)
                   for q in quality_flags):
            precharge_fault = _precharge_fault(rows, v2g)
            if precharge_fault is not None:
                add(*precharge_fault)

    # --- SLAC failure / abort ------------------------------------------
    last_opener_t = max((r["t"] for r in v2g
                         if r["msg"] in ("supportedAppProtocolReq",
                                         "SessionSetupReq")),
                        default=None)
    graceful = (stop_res_t is not None
                and (last_opener_t is None or stop_res_t >= last_opener_t))
    if not v2g:
        if ISO_REVIEWED:
            # Broadcasts from the neighbouring connector share this medium.
            # Admit a positive only when a link-specific response/IP frame
            # shows participation and the 20 s setup budget was observable.
            own = any(
                (r["kind"] in ("sdp", "tcp"))
                or (r["kind"] == "hpav" and any(name in r["msg"] for name in (
                    "SLAC_PARM.CNF", "SLAC_MATCH.CNF", "ATTEN_CHAR.RSP")))
                for r in rows
            )
            setup_t0 = slac[0]["t"] if slac else rows[0]["t"]
            deadline = setup_t0 + iso.COMM_SETUP_TIMEOUT_S
            if (own and rows[-1]["t"] >= deadline
                    and _continuous(rows, setup_t0, deadline,
                                    min_events=20, max_gap=2.0)):
                add(deadline, FAULT_SLAC,
                    "own-link SLAC participated but no V2G within 20s setup "
                    "budget")
            elif not own:
                censor_reason = "shared-PLC SLAC could not be attributed"
            else:
                censor_reason = "capture ended before 20s setup budget"
        else:
            add(rows[-1]["t"], FAULT_SLAC,
                f"SLAC attempts without V2G ({len(slac)} frames)")
    else:
        # A SLAC_PARM.REQ during our session is only a comm drop when THIS
        # session's V2G stream actually broke around it. The powerline is a
        # shared medium: the neighbouring connector's EV matching its own link
        # broadcasts SLAC frames that we capture while our CurrentDemand loop
        # runs on untouched (same SessionID, same TCP stream, sub-second
        # cadence) and the session still closes with SessionStopRes.
        first_v2g_t = v2g[0]["t"]
        re_slac = None
        for s in slac:
            if s["t"] <= first_v2g_t + 1.0 or "SLAC_PARM.REQ" not in s["msg"]:
                continue
            if graceful and s["t"] > stop_res_t:
                continue          # belongs to the next session, not this one
            nxt = next((r["t"] for r in v2g if r["t"] > s["t"]), None)
            prv = max((r["t"] for r in v2g if r["t"] < s["t"]),
                      default=first_v2g_t)
            if (nxt is None                              # stream died here
                    or nxt - prv > FREEZE_S              # v2g stalled across it
                    or any("SLAC_PARM.CNF" in o["msg"]   # our EVSE answered
                           and 0.0 <= o["t"] - s["t"] <= 10.0 for o in slac)
                    or any(r["msg"] == "supportedAppProtocolReq"
                           and r["t"] > s["t"] for r in v2g)):  # renegotiated
                re_slac = s["t"]
                break
        if re_slac is not None:
            last_before = max((r["t"] for r in v2g if r["t"] < re_slac),
                              default=first_v2g_t)
            add(last_before, FAULT_ABORT, "re-SLAC mid-session (link drop)")
        elif not graceful:
            v2g_streams = {r.get("tcp_stream", "") for r in v2g
                           if r.get("tcp_stream", "") != ""}
            rst = next((r["t"] for r in rows
                        if r["kind"] == "tcp" and r["msg"] == "RST"
                        and r["t"] >= first_v2g_t
                        and (not v2g_streams
                             or r.get("tcp_stream", "") in v2g_streams)),
                       None)
            if rst is not None:
                add(rst, FAULT_ABORT, "TCP RST")
            elif STRICT_ABORT:
                # A missing SessionStopRes is not by itself evidence of a fault.
                # On this fleet idle means zero packets and nearly every session
                # ends at a ring-buffer boundary, so "the dialog stopped" and
                # "the capture stopped" look identical from here. Measured: 44
                # of 78 held-out SESSION_ABORTs rested on nothing else, every
                # detector scored far worse on them than on corroborated ones,
                # and their median detection "lead" ran to 616-1633 s against
                # 0-106 s — the signature of a fault time pinned to the last
                # captured packet rather than to an event.
                ev = _abort_evidence(rows, v2g)
                if ev is not None:
                    if not ISO_REVIEWED or "dialog reopened" in ev[1]:
                        add(ev[0], FAULT_ABORT, ev[1])
            else:
                add(rows[-1]["t"], FAULT_ABORT, "stream death, no SessionStop")

    # --- pairing that barely worked ------------------------------------
    # Not the same as SLAC_FAILURE's "no V2G at all", but the same physical
    # problem and the same thing to go and check.
    if not ISO_REVIEWED and v2g and slac:
        pair_s = v2g[0]["t"] - slac[0]["t"]
        if pair_s > SLAC_SLOW_S:
            add(slac[0]["t"] + SLAC_SLOW_S, FAULT_SLAC,
                f"PLC pairing took {pair_s:.0f}s before V2G opened "
                f"(fleet median 9s)")

    # --- attempted in earnest, delivered nothing ------------------------
    # The EV asked for charge parameters, so it meant to charge; the dialogue
    # then closed properly without a single CurrentDemand. Requiring the
    # graceful close is what makes this safe: a capture that simply ran out
    # cannot produce a SessionStopRes.
    if graceful and first_cd_t is None and param_req_t is not None:
        phase = "ChargeParameterDiscovery"
        for name, seen in (("CableCheck", cablecheck_t0),
                           ("PreCharge", any(r["msg"].startswith("PreCharge")
                                             for r in v2g)),
                           ("PowerDelivery", any(r["msg"].startswith("PowerDelivery")
                                                 for r in v2g))):
            if seen:
                phase = name
        add(stop_req_t or last_dc_t or stop_res_t, FAULT_NO_POWER,
            f"stopped after {phase}, never reached CurrentDemand")

    faults.sort(key=lambda f: f[0])
    # collapse duplicate families riding the same instant (keep first each)
    seen = set()
    dedup = []
    for f in faults:
        k = f[1]
        if k not in seen:
            seen.add(k)
            dedup.append(f)
    censored = False
    if ISO_REVIEWED and not faults:
        if censor_reason:
            censored = True
        elif not graceful:
            censored = True
            if charging_complete_seen or stopcharging_seen:
                censor_reason = ("normal stop evidence present but "
                                 "SessionStopRes was not observable")
            else:
                censor_reason = ("non-graceful end without positive fault "
                                 "evidence")

    return SessionLabel(
        session_key=skey, station=station, connector=conn,
        t_start=rows[0]["t"], t_end=rows[-1]["t"], n_events=len(rows),
        reached_current_demand=first_cd_t is not None,
        graceful_close=graceful, faults=dedup, censored=censored,
        censor_reason=censor_reason if censored else "",
        quality_flags=sorted(set(quality_flags)), label_profile=LABEL_PROFILE,
    )
