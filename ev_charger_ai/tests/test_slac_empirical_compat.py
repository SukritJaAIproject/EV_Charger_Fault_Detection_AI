"""Regression checks that the published empirical SLAC arm stays unchanged."""
import os
import sys
from types import SimpleNamespace

os.environ["EV_AI_SLAC"] = "1"
os.environ["EV_AI_SLAC_RULE_MODE"] = "empirical"
os.environ["EV_AI_SLAC_WAIT"] = "10"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.schema import Event, FAULT_SLAC  # noqa: E402
from core.slac_features import SlacTracker  # noqa: E402
from models.slac_rules import slac_alert  # noqa: E402


def hpav(t, msg):
    return Event(t=float(t), kind="hpav", msg=msg)


def observe(tracker, event):
    return slac_alert(SimpleNamespace(slac=tracker.update(event)))


def test_six_hundred_ms_does_not_change_empirical_default():
    tr = SlacTracker()
    assert observe(tr, hpav(0, "CM_SLAC_MATCH.REQ")) is None
    assert observe(tr, hpav(0.61, "CM_LINK_STATUS.REQ")) is None


def test_empirical_rule_still_fires_at_ten_seconds():
    tr = SlacTracker()
    assert observe(tr, hpav(0, "CM_SLAC_MATCH.REQ")) is None
    assert observe(tr, hpav(9.99, "CM_LINK_STATUS.REQ")) is None
    hit = observe(tr, hpav(10.01, "CM_LINK_STATUS.REQ"))
    assert hit is not None and hit[2] == FAULT_SLAC
    assert "fleet policy" in hit[1]


def test_empirical_mode_does_not_enable_match_session_timer():
    tr = SlacTracker()
    assert observe(tr, hpav(0, "CM_ATTEN_CHAR.RSP")) is None
    assert observe(tr, hpav(11, "CM_LINK_STATUS.REQ")) is None


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} empirical SLAC compatibility regressions")


if __name__ == "__main__":
    main()
