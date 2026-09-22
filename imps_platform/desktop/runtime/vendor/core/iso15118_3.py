"""ISO 15118-3 SLAC timing constants recovered from public sources.

The paid standard was not used.  Every value below is a second-hand
attribution to ISO 15118-3 Annex A/Table A.1 that was independently
corroborated in public government material and/or independent open-source
implementations.  See ``docs/iso15118_3_public_sources.md`` for provenance.

Keep normative timers separate from fleet policy.  In particular, the
production SLAC rule historically waited 10 seconds after a
CM_SLAC_MATCH.REQ.  That threshold performed well on this fleet, but it is not
``TT_EVSE_match_session``: the latter is the EVSE's window for receiving a
match/validate request after sounding.  A sent match request is governed by
the much shorter ``TT_match_response``.
"""

# EVSE waits for the EV to begin SLAC after CP state B.
TT_EVSE_SLAC_INIT_MIN_S = 20.0
TT_EVSE_SLAC_INIT_MAX_S = 50.0

# EVSE waits for CM_VALIDATE.REQ or CM_SLAC_MATCH.REQ after sounding.
TT_EVSE_MATCH_SESSION_S = 10.0

# A SLAC request must receive its matching response within this time.
TT_MATCH_RESPONSE_S = 0.2

# A public Table-A.1 transcription describes this as two retries of the
# corresponding message, whose literal reading is an initial attempt plus two
# retries. The current EVerest loop treats the same value as two total attempts,
# so the composed deadline is not itself a directly published constant. Three
# response windows are deliberately the conservative public-source-derived
# observer budget; the raw 200 ms timer and retry counter remain separate.
C_EV_MATCH_RETRY = 2
UNANSWERED_MATCH_BUDGET_S = (1 + C_EV_MATCH_RETRY) * TT_MATCH_RESPONSE_S

# Other high-confidence values used by the state-machine audit.
TT_MATCH_SEQUENCE_S = 0.4
TT_EVSE_MATCH_MNBC_S = 0.6
TT_EV_ATTEN_RESULTS_S = 1.2
TT_MATCHING_REPETITION_S = 10.0
TT_MATCHING_RATE_S = 0.4
TT_MATCH_JOIN_S = 12.0

C_EV_START_ATTEN_CHAR_INDS = 3
C_EV_MATCH_MNBC_SOUNDS = 10
TP_EV_MNBC_SOUND_MIN_S = 0.020
TP_EV_MNBC_SOUND_MAX_S = 0.050

# Explicit names for the two evaluated policies.  Only NORMATIVE uses the
# Annex-A timing budget; EMPIRICAL preserves the published fleet experiment.
RULE_MODE_EMPIRICAL = "empirical"
RULE_MODE_NORMATIVE = "normative"
RULE_MODE_BOTH = "both"
RULE_MODES = {RULE_MODE_EMPIRICAL, RULE_MODE_NORMATIVE, RULE_MODE_BOTH}

