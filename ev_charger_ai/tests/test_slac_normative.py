"""Fast regressions for the ISO 15118-3 SLAC rule arm.

Run directly; no fleet data or model artifacts are read:

    python tests/test_slac_normative.py
"""
import os
import sys
from types import SimpleNamespace

os.environ["EV_AI_SLAC"] = "1"
os.environ["EV_AI_SLAC_RULE_MODE"] = "normative"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.schema import Event, FAULT_SLAC  # noqa: E402
from core.slac_features import SlacTracker  # noqa: E402
from models.slac_rules import slac_alert  # noqa: E402


def hpav(t, msg):
    return Event(t=float(t), kind="hpav", msg=msg)


def v2g(t, msg="SessionSetupReq"):
    return Event(t=float(t), kind="v2g", msg=msg)


def alert(tracker, event):
    return slac_alert(SimpleNamespace(slac=tracker.update(event)))


def test_match_confirmation_clears_response_timer():
    tr = SlacTracker()
    assert alert(tr, hpav(0, "CM_SLAC_MATCH.REQ")) is None
    assert alert(tr, hpav(0.1, "CM_SLAC_MATCH.CNF")) is None
    assert alert(tr, hpav(1.0, "CM_LINK_STATUS.REQ")) is None


def test_two_retries_get_three_response_windows():
    tr = SlacTracker()
    assert alert(tr, hpav(0.00, "CM_SLAC_MATCH.REQ")) is None
    assert alert(tr, hpav(0.20, "CM_SLAC_MATCH.REQ")) is None
    assert alert(tr, hpav(0.40, "CM_SLAC_MATCH.REQ")) is None
    assert alert(tr, hpav(0.59, "CM_LINK_STATUS.REQ")) is None
    hit = alert(tr, hpav(0.61, "CM_LINK_STATUS.REQ"))
    assert hit is not None and hit[2] == FAULT_SLAC
    assert "TT_match_response" in hit[1] and "600ms" in hit[1]


def test_validate_request_satisfies_match_session_window():
    tr = SlacTracker()
    assert alert(tr, hpav(0, "CM_ATTEN_CHAR.RSP")) is None
    assert alert(tr, hpav(5, "CM_VALIDATE.REQ")) is None
    assert alert(tr, hpav(11, "CM_LINK_STATUS.REQ")) is None


def test_match_request_satisfies_session_window_then_starts_response_timer():
    tr = SlacTracker()
    assert alert(tr, hpav(0, "CM_ATTEN_CHAR.RSP")) is None
    assert alert(tr, hpav(9.9, "CM_SLAC_MATCH.REQ")) is None
    hit = alert(tr, hpav(10.51, "CM_LINK_STATUS.REQ"))
    assert hit is not None and "TT_match_response" in hit[1]


def test_missing_match_or_validate_request_uses_separate_ten_second_timer():
    tr = SlacTracker()
    assert alert(tr, hpav(0, "CM_ATTEN_CHAR.RSP")) is None
    assert alert(tr, hpav(9.99, "CM_LINK_STATUS.REQ")) is None
    hit = alert(tr, hpav(10.01, "CM_LINK_STATUS.REQ"))
    assert hit is not None and hit[2] == FAULT_SLAC
    assert "TT_EVSE_match_session=10s" in hit[1]


def test_own_v2g_traffic_suppresses_shared_powerline_frames():
    tr = SlacTracker()
    assert alert(tr, hpav(0, "CM_SLAC_MATCH.REQ")) is None
    assert alert(tr, v2g(0.1)) is None
    assert alert(tr, hpav(1.0, "CM_LINK_STATUS.REQ")) is None


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} ISO 15118-3 SLAC regressions")


if __name__ == "__main__":
    main()
