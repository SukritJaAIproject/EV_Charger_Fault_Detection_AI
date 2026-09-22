"""Online view of the HomePlug AV SLAC matching sequence.

SLAC_FAILURE is 224 of 957 held-out fleet faults (23%) and the one family
ISO 15118-2 cannot describe at all — PLC matching is specified in part 3. These
sessions contain no V2G rows whatsoever, so every V2G-derived feature is
identically zero and the only signal lives in the HomePlug frames. The existing
FeatureTracker counts CM_SLAC_PARM.REQ occurrences and watches LINK_STATUS
gaps, but never tracks WHICH STAGE of the matching sequence was reached, which
is why four of five detectors score 0-21% on the family while AgenticAI
recovers 88% of it indirectly through per-station memory.

Measured on the 8,820-session fleet holdout (2026-09-16):

  * a healthy match is answered in 7 ms (p50; p99 14 ms over 5,129 matches).
    There is no gradual degradation - the charger answers essentially instantly
    or never at all.
  * 80.2% of SLAC_FAILURE sessions that sent CM_SLAC_MATCH.REQ never saw a
    .CNF; their deepest stage is the match request itself in 71.9% of cases.
  * after a successful match, V2G follows in 7.35 s (p50), 13.7 s (p95).

The neighbouring connector shares the powerline, so its matching frames land in
our capture too. That is why every hard SLAC signal is gated on this session
having produced no V2G of its own: without that gate the rule charges 685
healthy charges whose own match simply predates the capture window.

There are deliberately two timeout policies. ``empirical`` preserves the
published 10 s fleet rule. ``normative`` uses the public-source ISO 15118-3
state machine: 200 ms response windows and two retries (600 ms total), plus the
separate 10 s EVSE window for receiving a match/validate request after
attenuation characterization.  These must not be conflated: both happen to
mention SLAC matching, but they start at different messages.
"""
import os

from core import iso15118_3 as iso3

# The matching sequence in order. Indices are used as a monotonic progress
# measure, so the list order is load-bearing.
STAGES = (
    "SLAC_PARM.REQ",         # 1  EV asks to start matching
    "SLAC_PARM.CNF",         # 2  charger accepts
    "START_ATTEN_CHAR.IND",  # 3  EV announces the sounding burst
    "MNBC_SOUND.IND",        # 4  EV sounds
    "ATTEN_PROFILE.IND",     # 5  charger reports the profile
    "ATTEN_CHAR.IND",        # 6  charger reports attenuation
    "ATTEN_CHAR.RSP",        # 7  EV acknowledges
    "SLAC_MATCH.REQ",        # 8  EV asks to match this charger
    "SLAC_MATCH.CNF",        # 9  charger confirms - link is up
    "SET_KEY.REQ",           # 10 NMK distribution
    "SET_KEY.CNF",           # 11
)
STAGE_INDEX = {name: i + 1 for i, name in enumerate(STAGES)}
N_STAGES = len(STAGES)

MATCH_REQ = "SLAC_MATCH.REQ"
MATCH_CNF = "SLAC_MATCH.CNF"
VALIDATE_REQ = "VALIDATE.REQ"
ATTEN_RSP = "ATTEN_CHAR.RSP"

# How long an unanswered match request must stand before we call it failed.
# The knee of the measured cost curve: 71.9% of the family at a 0.39% false
# alarm rate and 49.5 s of median lead. Healthy matches answer in 7 ms, so this
# is ~700x the p99 and is not calibrating against normal variance - it is
# buying confidence that no V2G is coming.
MATCH_TIMEOUT_S = float(os.environ.get("EV_AI_SLAC_WAIT", "10"))
NORMATIVE_MATCH_TIMEOUT_S = iso3.UNANSWERED_MATCH_BUDGET_S
MATCH_SESSION_TIMEOUT_S = iso3.TT_EVSE_MATCH_SESSION_S

RULE_MODE = os.environ.get("EV_AI_SLAC_RULE_MODE",
                           iso3.RULE_MODE_EMPIRICAL).strip().lower()
if RULE_MODE not in iso3.RULE_MODES:
    raise ValueError(
        f"EV_AI_SLAC_RULE_MODE must be one of {sorted(iso3.RULE_MODES)}, "
        f"got {RULE_MODE!r}")

ENABLED = os.environ.get("EV_AI_SLAC", "0") == "1"


class SlacState:
    """Snapshot of the matching sequence at one event."""

    __slots__ = ("stage", "stage_frac", "matched", "v2g_seen",
                 "match_pending_s", "match_req_pending",
                 "match_session_pending_s", "awaiting_match_request",
                 "n_match_req", "n_restart", "since_match_s")


class SlacTracker:
    """Feeds on Events, emits SlacState. One instance per session."""

    def __init__(self):
        self.stage = 0
        self.matched = False
        self.v2g_seen = False
        self.n_match_req = 0
        self.n_restart = 0
        self.match_req_t = None     # oldest unanswered CM_SLAC_MATCH.REQ
        # Observable anchor for TT_EVSE_match_session.  The normative table
        # starts slightly earlier (at expiry of TT_EVSE_match_MNBC); captures
        # expose CM_ATTEN_CHAR.RSP reliably, so this later anchor is a
        # conservative implementation-compatible approximation.
        self.match_session_t = None
        self.match_cnf_t = None
        self._seen_late = False     # reached a stage beyond SLAC_PARM

    def update(self, ev):
        t = ev.t
        if ev.kind == "v2g":
            self.v2g_seen = True
        elif ev.kind == "hpav":
            msg = ev.msg
            if ATTEN_RSP in msg and self.match_session_t is None:
                self.match_session_t = t
            if VALIDATE_REQ in msg:
                self.match_session_t = None
            for name, idx in STAGE_INDEX.items():
                if name in msg:
                    if idx > self.stage:
                        self.stage = idx
                    if idx > STAGE_INDEX["SLAC_PARM.CNF"]:
                        self._seen_late = True
                    if name == MATCH_REQ:
                        self.n_match_req += 1
                        if self.match_req_t is None:
                            self.match_req_t = t
                        self.match_session_t = None
                    elif name == MATCH_CNF:
                        self.matched = True
                        self.match_cnf_t = t
                        self.match_req_t = None      # answered
                    elif name == "SLAC_PARM.REQ" and self._seen_late:
                        # the sequence went back to the beginning after having
                        # progressed: a retry, not the first attempt
                        self.n_restart += 1
                        self._seen_late = False
                    break

        st = SlacState()
        st.stage = self.stage
        st.stage_frac = self.stage / float(N_STAGES)
        st.matched = self.matched
        st.v2g_seen = self.v2g_seen
        st.n_match_req = self.n_match_req
        st.n_restart = self.n_restart
        st.match_req_pending = self.match_req_t is not None
        st.match_pending_s = (t - self.match_req_t
                              if self.match_req_t is not None else 0.0)
        st.awaiting_match_request = self.match_session_t is not None
        st.match_session_pending_s = (
            t - self.match_session_t
            if self.match_session_t is not None else 0.0)
        st.since_match_s = (t - self.match_cnf_t
                            if self.match_cnf_t is not None else 0.0)
        return st

