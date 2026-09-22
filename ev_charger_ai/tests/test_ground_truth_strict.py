"""Fast regression checks for strict ground truth and session boundaries.

Run directly; no fleet data or model artifacts are read:

    python tests/test_ground_truth_strict.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.ground_truth import label_session  # noqa: E402
from pipeline.sessionize import is_truncation_artifact, iter_sessions  # noqa: E402


def row(t, kind, msg, **extra):
    return {"t": float(t), "kind": kind, "msg": msg, **extra}


def label(rows):
    return label_session("station__connector1__0000", "station",
                         "connector1", rows)


def test_strict_clean_tail_is_still_unjudgeable_at_a_cut():
    rows = [
        row(0, "v2g", "supportedAppProtocolReq", tcp_stream="0"),
        row(0.1, "v2g", "supportedAppProtocolRes", tcp_stream="0"),
    ]
    lab = label(rows)
    assert lab.faults == [] and not lab.graceful_close
    assert is_truncation_artifact(lab, [lab.t_end])
    assert not is_truncation_artifact(lab, [lab.t_end + 10])


def test_graceful_tail_is_not_dropped_at_a_cut():
    rows = [
        row(0, "v2g", "SessionSetupReq", tcp_stream="0"),
        row(0.1, "v2g", "SessionSetupRes", tcp_stream="0"),
        row(1, "v2g", "SessionStopReq", tcp_stream="0"),
        row(1.1, "v2g", "SessionStopRes", tcp_stream="0",
            resp_code="OK"),
    ]
    lab = label(rows)
    assert lab.graceful_close and lab.faults == []
    assert not is_truncation_artifact(lab, [lab.t_end])


def test_alive_after_requires_packets_near_the_deadline():
    rows = [row(0, "v2g", "SessionSetupReq", tcp_stream="0")]
    rows.extend(row(100 + i / 10, "tcp", "RETX", tcp_stream="0")
                for i in range(20))
    lab = label(rows)
    assert not any("unanswered" in f[2] for f in lab.faults)


def test_alive_after_boundary_is_twenty_rows():
    def fixture(n):
        rows = [row(0, "v2g", "CurrentDemandReq", tcp_stream="0")]
        rows.extend(row(0.3 + i / 100, "tcp", "RETX", tcp_stream="0")
                    for i in range(n))
        return label(rows)

    assert not any("unanswered" in f[2] for f in fixture(19).faults)
    assert any("unanswered" in f[2] for f in fixture(20).faults)


def test_new_session_setup_after_close_starts_a_new_chunk():
    rows = [
        row(0, "v2g", "SessionSetupReq"),
        row(0.1, "v2g", "SessionSetupRes"),
        row(1, "v2g", "SessionStopReq"),
        row(1.1, "v2g", "SessionStopRes"),
        row(2, "v2g", "SessionSetupReq"),
        row(2.1, "v2g", "SessionSetupRes"),
    ]
    chunks = list(iter_sessions(rows))
    assert len(chunks) == 2
    assert chunks[0][-1]["msg"] == "SessionStopRes"
    assert chunks[1][0]["msg"] == "SessionSetupReq"


def test_old_stop_does_not_make_a_later_dialog_graceful():
    rows = [
        row(0, "v2g", "SessionSetupReq", tcp_stream="0"),
        row(0.1, "v2g", "SessionSetupRes", tcp_stream="0"),
        row(1, "v2g", "SessionStopRes", tcp_stream="0"),
        row(2, "v2g", "SessionSetupReq", tcp_stream="0"),
        row(2.1, "v2g", "SessionSetupRes", tcp_stream="0"),
    ]
    assert not label(rows).graceful_close


def test_rst_must_belong_to_the_v2g_stream():
    base = [
        row(0, "v2g", "SessionSetupReq", tcp_stream="1"),
        row(0.1, "v2g", "SessionSetupRes", tcp_stream="1"),
    ]
    unrelated = label(base + [row(1, "tcp", "RST", tcp_stream="0")])
    related = label(base + [row(1, "tcp", "RST", tcp_stream="1")])
    assert not any(f[2] == "TCP RST" for f in unrelated.faults)
    assert any(f[2] == "TCP RST" for f in related.faults)


def test_abort_anchored_at_a_cut_is_dropped_even_with_later_quiet_rows():
    rows = [
        row(0, "v2g", "SessionSetupReq", tcp_stream="1"),
        row(0.1, "v2g", "SessionSetupRes", tcp_stream="1"),
        row(1, "tcp", "RST", tcp_stream="1"),
        row(10, "tcp", "RETX", tcp_stream="1"),
    ]
    lab = label(rows)
    assert lab.t_end == 10
    assert is_truncation_artifact(lab, [1])


def test_ongoing_timer_resets_when_the_response_phase_changes():
    rows = [
        row(0, "v2g", "SessionSetupReq"),
        row(0.1, "v2g", "SessionSetupRes"),
        row(1, "v2g", "CableCheckRes", evse_processing="Ongoing"),
        row(2, "v2g", "PreChargeRes"),
    ]
    rows.extend(row(70 + i / 10, "tcp", "RETX") for i in range(20))
    lab = label(rows)
    assert not any("EVSEProcessing" in f[2] for f in lab.faults)


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} strict ground-truth regressions")


if __name__ == "__main__":
    main()
