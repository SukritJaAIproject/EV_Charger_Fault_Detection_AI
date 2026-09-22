# ISO 15118-3 public-source SLAC rulebook

> Evidence status: public secondary sources only. The paid ISO 15118-3 text was not opened, copied, or quoted. Values are second-hand attributions to Annex A/Table A.1 and must be described that way in publications.

## Research status

- 42 findings passed an independent corroboration check; 45 remain single-source or otherwise unresolved.
- Workflow agents: 64 completed and 29 verifier jobs stopped at the Claude weekly quota. A pending item is not a rejected item; it is excluded from normative rules until independently verified.
- Archived input SHA-256: `4ac9f7e3c7bcc4eba20ccfca8a76c57362bad9100249c6e99b147644ad0cb1a7`.
- The full evidence, disagreements, URLs, and verifier reasoning are in `results/iso15118_3_public_sources.json`.

## Critical correction to the detector

The earlier fleet rule waited 10 s after `CM_SLAC_MATCH.REQ` and described that value as ISO-backed. The measurement remains useful, but the attribution was wrong. Two different clocks were conflated:

| Observable condition | Public-source ISO symbol | Budget | Use |
|---|---|---:|---|
| `CM_SLAC_MATCH.REQ` sent; no `.CNF` | `TT_match_response` plus `C_EV_match_retry` | 200 ms × (1 + 2) = **600 ms** | ISO-derived arm |
| Attenuation completed; no `CM_VALIDATE.REQ` or `CM_SLAC_MATCH.REQ` | `TT_EVSE_match_session` | **10 s** | ISO-derived arm |
| `CM_SLAC_MATCH.REQ` sent; no `.CNF` | Fleet operating policy | **10 s** | Published empirical arm, retained for reproducibility |

The 600 ms value is a conservative passive-observer derivation: one 200 ms response window plus two retries. The table transcription describes `C_EV_match_retry=2` as retries, while EVerest's current loop treats the same constant as two total attempts. The composed 600 ms deadline is therefore neither a directly published constant nor a conformance claim; it is also not a tuned threshold. The 10 s match-session timer is anchored in code at `CM_ATTEN_CHAR.RSP`, a later and therefore more lenient observable point than expiration of the 600 ms sounding window stated by one independent Table A.1 transcription.
The retry-count discrepancy is directly inspectable in the [Table-A.1 transcription](https://github.com/cepsdev/v2g-guru-slac/blob/main/model/timing.ceps#L59-L60) and the current [EVerest match-request loop](https://github.com/EVerest/everest-core/blob/main/lib/everest/slac/fsm/ev/src/states/others.cpp#L137-L157).

## Corroborated detector constants

| Symbol | Value | Confidence | Meaning | Evidence |
|---|---:|---|---|---|
| `TT_EVSE_SLAC_init` | 20 s – 50 s (pyslac uses 50 s; EVerest uses 40 s) | high | Time the EVSE waits, from detecting CP state B (5 % PWM), for the first SLAC message (CM_SLAC_PARM.REQ). Expiry = no EV SLAC attempt. | [source](https://github.com/ecog-io/pyslac/blob/main/pyslac/enums.py#L44-L55) |
| `TT_EVSE_match_session` | 10 s | high | EVSE-side window for receiving CM_VALIDATE.REQ or CM_SLAC_MATCH.REQ after it has received CM_ATTEN_CHAR.RSP. Expiry = EV never asked to match. | [source](https://github.com/EVerest/everest-core/blob/main/lib/everest/slac/fsm/evse/src/states/matching_handle_slac.cpp#L356-L359) |
| `TT_match_response` | 200 ms | high | Maximum time for a SLAC .REQ to be answered by the corresponding .CNF/.RSP. This is the normative limit behind "unanswered CM_SLAC_MATCH.REQ": the EV starts this timer when it sends CM_SLAC_MATCH.REQ and expects CM_SLAC_MATCH.CNF inside it. Same timer guards CM_SLAC_PARM.REQ→CNF and CM_ATTEN_CHAR.IND→RSP. | [source](https://github.com/EVerest/everest-core/blob/main/lib/everest/slac/fsm/ev/src/states/others.cpp#L193-L212) |
| `C_EV_match_retry` | 2 retries | medium | Number of times the EV re-sends a matching message that went unanswered before the matching attempt is declared failed. With TT_match_response this bounds an unanswered CM_SLAC_MATCH.REQ at roughly 3 × 200 ms ≈ 600 ms. | [source](https://github.com/EVerest/everest-core/blob/main/lib/everest/slac/include/slac/slac.hpp#L43-L57) |
| `TT_match_sequence` | 400 ms | high | Maximum time between two consecutive messages of a matching sequence, e.g. from CM_SLAC_PARM.CNF to the first CM_START_ATTEN_CHAR.IND. | [source](https://github.com/ecog-io/pyslac/blob/main/pyslac/enums.py#L65-L66) |
| `TT_EVSE_match_MNBC` | 600 ms (transmitted on the wire as 0x06, unit 100 ms) | high | Window in which all CM_MNBC_SOUND.IND must have been sent/received; the EVSE advertises it in CM_SLAC_PARM.CNF and the EV echoes it in CM_START_ATTEN_CHAR.IND (TIME_OUT field). | [source](https://github.com/ecog-io/pyslac/blob/main/pyslac/enums.py#L97-L103) |
| `TT_EV_atten_results` | 1200 ms (max) | high | Time the EV waits for CM_ATTEN_CHAR.IND, started when it sends the first CM_START_ATTEN_CHAR.IND. | [source](https://github.com/ecog-io/pyslac/blob/main/pyslac/session.py#L455-L470) |
| `TT_matching_repetition` | 10 s | medium | Total time during which matching attempts may be repeated; once expired the matching process is considered FAILED and the link goes to "Unmatched". | [source](https://github.com/ecog-io/pyslac/blob/main/pyslac/enums.py#L71-L87) |
| `TT_matching_rate` | 400 ms | medium | Wait time between a failed matching attempt and the next repetition ([V2G3-A09-124]). | [source](https://github.com/ecog-io/pyslac/blob/main/pyslac/enums.py#L89-L90) |
| `TT_match_join` | 12 s (max) | medium | Time allowed for the stations to actually join the logical network (AVLN) after matching, i.e. after CM_SLAC_MATCH.CNF / CM_SET_KEY. | [source](https://github.com/EVerest/everest-core/blob/main/lib/everest/slac/include/slac/slac.hpp#L43-L57) |
| `C_EV_start_atten_char_inds (EVerest: C_EV_START_ATTEN_CHAR_INDS)` | 3 messages | high | The EV broadcasts CM_START_ATTEN_CHAR.IND three times in a row, whether or not the first was received. | [source](https://github.com/EVerest/everest-core/blob/main/lib/everest/slac/fsm/ev/src/states/sounding.cpp#L70-L90) |
| `C_EV_match_MNBC` | 10 sounds | high | Number of CM_MNBC_SOUND.IND the EV transmits during attenuation characterisation. | [source](https://github.com/EVerest/everest-core/blob/main/lib/everest/slac/include/slac/slac.hpp#L43-L57) |
| `TP_EV_batch_msg_interval` | 20 ms – 50 ms (EVerest picks 40 ms, pyslac 20 ms, open-plc-utils 20 ms) | high | Pause between consecutive CM_START_ATTEN_CHAR.IND / CM_MNBC_SOUND.IND frames, so the EVSE PLC chip can forward CM_MNBC_SOUND.IND and CM_ATTEN_PROFILE.IND to the EVSE host. | [source](https://github.com/EVerest/everest-core/blob/main/lib/everest/slac/include/slac/slac.hpp#L43-L57) |

## Pcap-observable state machine

| Step | Exchange | Guard/check |
|---:|---|---|
| 1 | EV → EVSE `CM_SLAC_PARM.REQ`; EVSE → EV `.CNF` | Response window 200 ms; retry policy applies |
| 2 | EV sends 3 × `CM_START_ATTEN_CHAR.IND` | 20–50 ms batch spacing |
| 3 | EV sends 10 × `CM_MNBC_SOUND.IND` | 600 ms EVSE sounding window |
| 4 | EVSE sends `CM_ATTEN_CHAR.IND`; EV returns `.RSP` | Response window 200 ms; retry policy applies |
| 5 | Optional `CM_VALIDATE.REQ/.CNF` | Satisfies the EVSE match-session wait |
| 6 | EV sends `CM_SLAC_MATCH.REQ`; EVSE returns `.CNF` | Response window 200 ms; public retry-count readings differ (2 or 3 total attempts), so the detector conservatively budgets 3 |
| 7 | EV applies key; modems join the AVLN | `TT_match_join` 12 s |
| 8 | SDP, TCP/TLS, SupportedAppProtocol, SessionSetup | ISO 15118-2 begins only after SLAC link-up |

## Rule-arm configuration

- `EV_AI_SLAC_RULE_MODE=empirical` (default): reproduces the published 10 s fleet result.
- `EV_AI_SLAC_RULE_MODE=normative`: profile name for the public-source derived 600 ms unanswered-request budget and the separate 10 s missing-request timer; it is not a certification claim.
- `EV_AI_SLAC_RULE_MODE=both`: evaluates the union; the normative rule normally fires first.

All hard signals remain gated by absence of this session's own V2G traffic because both connectors share the PLC medium and their SLAC frames can appear in the same capture.

## Excluded from hard rules

- The 45 pending findings are preserved in the JSON archive but do not set thresholds.
- Implementation defaults from QCA, pyPLC, or vendor stacks are not called normative unless a separate source explicitly attributes the same symbol/value to ISO 15118-3.
- `CM_SLAC_MATCH.CNF → first V2G` has no corroborated tight application deadline; do not invent one from fleet observations.
- Missing SLAC frames alone are not a fault because ring-buffer captures frequently start after matching.
