"""Regression checks for the opt-in ISO-reviewed ground-truth profile."""
import os
import sys

os.environ["EV_AI_LABEL_PROFILE"] = "iso_reviewed"
os.environ["EV_AI_STRICT_ABORT"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.schema import (FAULT_EV_ERROR, FAULT_FREEZE, FAULT_ISOLATION,  # noqa: E402
                         FAULT_PRECHARGE, FAULT_PROCESSING, FAULT_PROTOCOL,
                         FAULT_SLAC, QUALITY_DECODE_ERROR)
from pipeline.ground_truth import label_session  # noqa: E402


def row(t, kind, msg, **extra):
    return {"t": float(t), "kind": kind, "msg": msg, **extra}


def close(t):
    return [row(t, "v2g", "SessionStopReq"),
            row(t + 0.01, "v2g", "SessionStopRes", resp_code="OK")]


def label(rows):
    return label_session("station__connector1__0000", "station",
                         "connector1", rows)


def families(lab):
    return {f[1] for f in lab.faults}


def test_failed_response_payload_is_ignored():
    rows = [row(0, "v2g", "CableCheckRes", resp_code="FAILED",
                evse_status="EVSE_Malfunction", isolation="Fault",
                ev_err="FAILED_ChargingSystemIncompatibility")]
    rows += close(1)
    lab = label(rows)
    assert families(lab) == {FAULT_PROTOCOL}


def test_nodata_is_benign_until_delivery_but_not_inside_it():
    early = [row(0, "v2g", "CableCheckReq", ev_err="NoData"),
             row(0.01, "v2g", "CableCheckRes", ev_err="NoData")]
    clean = label(early + close(1))
    assert FAULT_EV_ERROR not in families(clean)

    late = early + [row(1, "v2g", "CurrentDemandReq", ev_err="NoData")]
    faulty = label(late + close(2))
    assert FAULT_EV_ERROR in families(faulty)


def test_reserved_ev_error_is_quality_not_fault():
    lab = label([row(0, "v2g", "SessionSetupReq", ev_err="Reserved_A")]
                + close(1))
    assert FAULT_EV_ERROR not in families(lab)
    assert any(q.startswith("RESERVED_EV_ERROR") for q in lab.quality_flags)


def test_five_second_delivery_gap_is_not_a_hard_label():
    rows = [row(0, "v2g", "CurrentDemandReq"),
            row(0.01, "v2g", "CurrentDemandRes"),
            row(6, "v2g", "CurrentDemandReq"),
            row(6.01, "v2g", "CurrentDemandRes")]
    lab = label(rows + close(7))
    assert FAULT_FREEZE not in families(lab)


def test_unanswered_request_needs_live_capture_and_anchors_at_timeout():
    rows = [row(0, "v2g", "CurrentDemandReq")]
    rows += [row(0.3 + i * 0.06, "hpav", "CM_LINK_STATUS.REQ")
             for i in range(22)]
    lab = label(rows)
    hit = next(f for f in lab.faults if f[1] == FAULT_FREEZE)
    assert abs(hit[0] - 0.25) < 1e-9


def test_cablecheck_uses_forty_second_timeout_with_continuity():
    rows = [row(0, "v2g", "CableCheckReq")]
    rows += [row(float(i), "v2g", "CableCheckRes",
                 evse_processing="Ongoing") for i in range(1, 42)]
    lab = label(rows)
    hit = next(f for f in lab.faults if f[1] == FAULT_FREEZE)
    assert hit[0] == 40.0 and "CableCheck" in hit[2]


def test_ongoing_machine_phase_gets_own_family():
    rows = []
    for i in range(22):
        t = i * 3.0
        rows += [row(t, "v2g", "ChargeParameterDiscoveryReq"),
                 row(t + 0.01, "v2g", "ChargeParameterDiscoveryRes",
                     evse_processing="Ongoing")]
    lab = label(rows)
    assert FAULT_PROCESSING in families(lab)


def test_precharge_requires_timeout_and_failed_convergence():
    rows = []
    for i in range(12):
        rows += [row(i, "v2g", "PreChargeReq", ev_target_v=500.0),
                 row(i + 0.01, "v2g", "PreChargeRes", ev_target_v=500.0,
                     evse_v=100.0)]
    lab = label(rows)
    assert FAULT_PRECHARGE in families(lab)


def test_decode_error_invalidates_precharge_label():
    rows = []
    for i in range(12):
        rows += [row(i, "v2g", "PreChargeReq", ev_target_v=500.0),
                 row(i + 0.01, "v2g", "PreChargeRes", ev_target_v=500.0,
                     evse_v=1200.0)]
    lab = label(rows)
    assert FAULT_PRECHARGE not in families(lab)
    assert any(q.startswith(QUALITY_DECODE_ERROR) for q in lab.quality_flags)


def test_uncorroborated_non_graceful_end_is_censored():
    lab = label([row(0, "v2g", "SessionSetupReq"),
                 row(0.01, "v2g", "SessionSetupRes")])
    assert not lab.faults and lab.censored


def test_shared_plc_broadcasts_are_censored_not_faults():
    rows = [row(0, "hpav", "CM_SLAC_PARM.REQ"),
            row(0.1, "hpav", "CM_START_ATTEN_CHAR.IND"),
            row(0.2, "hpav", "CM_SLAC_MATCH.REQ")]
    lab = label(rows)
    assert lab.censored and FAULT_SLAC not in families(lab)


def test_owned_slac_with_observable_setup_budget_is_a_fault():
    rows = [row(0, "hpav", "CM_SLAC_PARM.REQ"),
            row(0.1, "hpav", "CM_SLAC_PARM.CNF"),
            row(0.2, "hpav", "CM_SLAC_MATCH.REQ")]
    rows += [row(float(i), "hpav", "CM_LINK_STATUS.REQ")
             for i in range(1, 22)]
    lab = label(rows)
    assert not lab.censored and FAULT_SLAC in families(lab)


def test_persistent_invalid_isolation_after_cablecheck_is_fault():
    rows = [row(0, "v2g", "CurrentDemandReq", isolation="Invalid"),
            row(0.01, "v2g", "CurrentDemandRes", isolation="Invalid")]
    lab = label(rows + close(1))
    assert FAULT_ISOLATION in families(lab)


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} ISO-reviewed ground-truth regressions")


if __name__ == "__main__":
    main()
