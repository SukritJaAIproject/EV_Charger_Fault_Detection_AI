"""SLAC matching rules shared by the four rule-adopting competitors.

The learned RL policy deliberately has no rule layer and remains unchanged.

The published ``empirical`` arm is one measured rule. On the 8,820-session
fleet holdout its 10 s threshold catches 161 of 224 SLAC_FAILURE sessions
(71.9%) for 31 false alarms out of 7,863 clean ones (0.39%), with 49.5 s of
median lead.

The ``normative`` arm is intentionally separate. Public sources that cite ISO
15118-3 Annex A put ``TT_match_response`` at 200 ms. A public Table A.1
transcription describes ``C_EV_match_retry=2`` as two repetitions, so the
research profile allows an initial window plus two retries (600 ms). EVerest's
current loop interprets that same constant as two total sends, which is why
this is documented as a conservative public-source profile rather than a
conformance claim. The sources also put ``TT_EVSE_match_session`` at 10 s, but
that timer covers the *absence of a request after sounding*; it does not
justify waiting 10 s after a request has already been sent. See
``docs/iso15118_3_public_sources.md``.

Deliberately NOT included, despite looking tempting:

  * "matched but no V2G within N seconds". A successful match is followed by
    V2G in 7.35 s median but 119 s at the maximum, so any N tight enough to be
    useful fires on healthy charges. The `since_match_s` field is exposed for
    the learned layers to weigh in context; it is not a rule.
  * "stage never reached SLAC_MATCH.REQ". 27.2% of CLEAN sessions contain no
    SLAC frames at all - they open mid-charge at a ring-buffer boundary - so
    absence of progress is not evidence of failure.
"""
from core.schema import FAULT_SLAC
from core.slac_features import (MATCH_SESSION_TIMEOUT_S, MATCH_TIMEOUT_S,
                                NORMATIVE_MATCH_TIMEOUT_S, RULE_MODE)
from core import iso15118_3 as iso3


def slac_alert(fs):
    """-> (confidence, reason, fault_family) if the match has failed."""
    s = getattr(fs, "slac", None)
    if s is None or s.v2g_seen:
        # V2G traffic means this session's own link came up. Any unanswered
        # match request still in the air belongs to the neighbouring connector
        # on the shared powerline, not to us.
        return None
    if RULE_MODE in (iso3.RULE_MODE_NORMATIVE, iso3.RULE_MODE_BOTH):
        if (s.match_req_pending
                and s.match_pending_s >= NORMATIVE_MATCH_TIMEOUT_S):
            return (
                0.95,
                "ISO 15118-3 public-source profile: "
                "CM_SLAC_MATCH.REQ unanswered for "
                f"{s.match_pending_s * 1000:.0f}ms "
                f"(3 x TT_match_response = "
                f"{NORMATIVE_MATCH_TIMEOUT_S * 1000:.0f}ms; "
                f"C_EV_match_retry={iso3.C_EV_MATCH_RETRY}), no V2G",
                FAULT_SLAC,
            )
        if (s.awaiting_match_request
                and s.match_session_pending_s >= MATCH_SESSION_TIMEOUT_S):
            return (
                0.9,
                "ISO 15118-3 public-source profile: "
                "no CM_VALIDATE.REQ/CM_SLAC_MATCH.REQ for "
                f"{s.match_session_pending_s:.1f}s after "
                "CM_ATTEN_CHAR.RSP "
                f"(TT_EVSE_match_session={MATCH_SESSION_TIMEOUT_S:.0f}s), "
                "no V2G",
                FAULT_SLAC,
            )

    if (RULE_MODE in (iso3.RULE_MODE_EMPIRICAL, iso3.RULE_MODE_BOTH)
            and s.match_req_pending and s.match_pending_s >= MATCH_TIMEOUT_S):
        return (0.9,
                f"SLAC fleet policy: CM_SLAC_MATCH.REQ unanswered for "
                f"{s.match_pending_s:.1f}s (threshold {MATCH_TIMEOUT_S:g}s; "
                f"healthy match answers in 7ms), "
                f"no V2G", FAULT_SLAC)
    return None

