# ISO 15118 label-proposal decisions

## Scope and policy

The rulebook contains 35 ground-truth proposals: 9 from the timing lens, 14
from the protocol lens, and 12 from the electrical lens. One of them—the
positive-evidence requirement for `SESSION_ABORT`—was already implemented,
which is why the hand-off called these “34 remaining proposals.” The lists
overlap heavily; implementing all 35 literally would create duplicate and, in
several cases, contradictory labels.

Every proposal is closed below as accepted, partially accepted, already
satisfied, duplicate, rejected as a hard label, or blocked by missing data.
Accepted label changes live behind:

```text
EV_AI_LABEL_PROFILE=iso_reviewed
```

The default `strict` code path remains behaviorally unchanged from the source
at hand-off, and the immutable `index.json`/benchmark records remain available
to reproduce the published leaderboard. These are not the same label snapshot:
`index.json` predates the already-existing `NO_POWER_DELIVERED` rule and 13
SLAC reclassifications. A full 8,820-session before/after replay found zero
differences in `faults`, `graceful_close`, or `reached_current_demand` between
the pre-continuation and current `strict` implementations. `iso_reviewed` adds
an explicit `censored` state; censored sessions are neither faulty nor clean
and are excluded from scoring. It also records `quality_flags`, which never
makes a session faulty.

## Decision summary

| Outcome | Count |
|---|---:|
| Implemented in `iso_reviewed` | 12 |
| Already satisfied before this review | 3 |
| Deduplicated/resolved into another implemented proposal | 13 |
| Kept as feature/annotation, not hard ground truth | 5 |
| Rejected or blocked after fleet validation | 2 |
| **Total** | **35** |

## Timing lens (T1–T9)

| ID | Proposal | Decision | Implementation / reason |
|---|---|---|---|
| T1 | Replace flat `COMM_FREEZE` gap with unanswered-request timeouts | **Implemented** | `_iso_timing_faults()` matches each `Req` to `Res`, admits a label only after `max(2×timeout, 1.5 s)` plus a live-capture continuity gate, and anchors the fault at the normative deadline. Response→next-request stalls use the 60 s SECC sequence timeout. The old 5 s label exists only in the legacy profile. |
| T2 | Split `COMM_FREEZE` by the party that owes the message | **Partially implemented** | Detail text now identifies request/response (SECC-side) versus sequence (EVCC-side) ownership. Both retain the coarse parent family because the subclasses are too sparse for stable multiclass training. |
| T3 | CableCheck timeout at 40 s with correct completion | **Implemented** | First `CableCheckReq`, successful non-FAILED `CableCheckRes` with `Finished` (or `PreChargeReq` fallback), 40 s deadline, and packet-continuity gate. |
| T4 | PreCharge fault at 10 s plus failed voltage convergence | **Implemented** | New `PRECHARGE_FAULT`; requires a continuously observed 10 s phase, at least two voltage observations, final gap >20 V, and less than 50% convergence. The voltage band is documented as a conservative heuristic, not an ISO constant. |
| T5 | Ongoing timeout at 60 s for machine phases only | **Implemented** | New `EVSE_PROCESSING_STALL`, limited to `CableCheckRes` and `ChargeParameterDiscoveryRes`; `ContractAuthenticationRes` is explicitly excluded. |
| T6 | Require positive evidence for `SESSION_ABORT` | **Already satisfied and extended** | Strict abort evidence was already implemented. `iso_reviewed` additionally censors non-graceful ends with no positive evidence instead of allowing them into the clean class. |
| T7 | Ignore payload fields carried by FAILED responses | **Implemented** | A FAILED-prefixed row contributes only `PROTOCOL_FAILED`; EVSE status, isolation, EV error, and electrical values on that row are ignored. |
| T8 | Treat `NoData` as benign before delivery | **Implemented** | `NoData` is benign before CurrentDemand and becomes `EV_ERROR` only if it persists into delivery. Reserved EV error values become quality annotations, not faults. |
| T9 | Require own-link evidence and a setup budget for `SLAC_FAILURE` | **Implemented** | No-V2G traces require link-specific `.CNF`/`.RSP` or IP evidence, a continuously observable 20 s setup window, and otherwise become censored. The finer ISO 15118-3 online rules are evaluated in a separate SLAC arm. |

## Protocol lens (P1–P14)

| ID | Proposal | Decision | Implementation / reason |
|---|---|---|---|
| P1 | Split each FAILED literal into its own family | **Feature/annotation only** | The literal is already retained in fault detail. `PROTOCOL_FAILED` remains the parent class to avoid fragmenting small subclasses; downstream analysis can group by literal without relabelling. |
| P2 | Case-fold `ok` / `failed` prefixes | **Already satisfied** | `rc.upper().startswith("FAILED")` catches `Failed_NoNegotiation`; OK-prefixed variants are not faults. Regression coverage was retained. |
| P3 | Suppress fields on FAILED rows | **Duplicate of T7** | Implemented once. |
| P4 | Corroborate missing SessionStop | **Duplicate of T6** | Implemented once with censorship for unknown outcomes. |
| P5 | CableCheck at 45 s | **Resolved in favour of T3** | The normative 40 s value plus a continuity gate is more auditable than an invented 5 s guard band. Fleet clean maximum was 27 s, so 40 s retains margin. |
| P6 | Keep 5 s `COMM_FREEZE` as ground truth | **Rejected as hard ISO label** | It conflicts with T1 and no 5 s timer governs the CurrentDemand exchange. The strict profile preserves it as the pre-review control; graded gap features remain available to models. |
| P7 | `NoData` and persistent `EVReady=FALSE` | **Partially implemented** | `NoData` is handled by T8. `EVReady=FALSE` stays a feature because it is normal before PowerDelivery and primarily describes vehicle incompatibility rather than charger failure. |
| P8 | Exclude UtilityInterrupt; downgrade orderly shutdown/emergency | **Partially implemented** | `EVSE_UtilityInterruptEvent` and `EVSE_Shutdown` were already non-faults. `EVSE_EmergencyShutdown` is deliberately retained: an E-stop remains a material safety event even if teardown is orderly. |
| P9 | Re-base SLAC on SDP/setup evidence | **Merged into T9** | SDP payload/response direction is not reliably extracted. The implemented rule uses any available IP evidence plus link-specific SLAC responses and censors ambiguous broadcast-only traces. |
| P10 | Ongoing timeout at ~65 s | **Resolved in favour of T5** | Uses the published hard timeout of 60 s rather than an unexplained 5 s extension, with continuity and phase guards. |
| P11 | Isolation `Invalid` persisting beyond CableCheck | **Implemented conservatively** | Requires two populated `Invalid` observations in CurrentDemand. Missing fields are not treated as `Invalid`; `No_IMD` remains a monitoring-blind-spot annotation, not a pass or a fault. |
| P12 | Suppress faults after `StopCharging` | **Implemented through context/censorship** | The reviewed profile removes the flat gap label and treats orderly stop evidence as a censoring/negative context. Hard FAILED, RST, isolation, or malfunction evidence is never suppressed. `NotificationMaxDelay` is unavailable, so “EV ignored stop too long” is not hard-labelled. |
| P13 | Do not treat legal renegotiation as restart/freeze | **Implemented by timer semantics** | The reviewed profile no longer labels a generic CurrentDemand gap, so a legal return to ChargeParameterDiscovery does not create `COMM_FREEZE`. Exact NotificationMaxDelay validation remains blocked by extraction. |
| P14 | Define positive clean and unknown/censored outcomes | **Implemented** | Graceful OK `SessionStopRes` is positive clean evidence. A non-graceful end without a hard marker is censored, not silently negative. Boundary handling therefore cannot inflate false alarms. |

## Electrical lens (E1–E12)

| ID | Proposal | Decision | Implementation / reason |
|---|---|---|---|
| E1 | Ignore electrical/status fields on FAILED rows | **Duplicate of T7** | Implemented once. |
| E2 | `NoData` / reserved EV error handling | **Duplicate of T8** | Implemented once. |
| E3 | CableCheck at 40 s | **Duplicate of T3** | Implemented once. |
| E4 | Replace 5 s freeze with normative timers | **Duplicate of T1** | Implemented once. |
| E5 | FAILED close as `SHUTDOWN_FAULT` | **Already satisfied / annotation only** | FAILED `SessionStopRes` has not counted as graceful since the strict-abort fix and is already `PROTOCOL_FAILED`. A redundant binary family would not change the label; the exact response remains in detail. |
| E6 | Corroborated abort versus unclean close | **Duplicate of T6/P14** | Implemented once with `censored`. |
| E7 | Require EVSE participation for SLAC | **Duplicate of T9** | Implemented once. |
| E8 | Ongoing processing stall | **Duplicate of T5** | Implemented once. |
| E9 | PreCharge at 7 s and UtilityInterrupt suppressor | **Merged into T4/P8** | Fleet clean sessions exceed 7 s; the reviewed label uses 10 s plus failed convergence. UtilityInterrupt remains non-fault. |
| E10 | Completion and StopCharging as negative evidence | **Implemented conservatively** | Completion/StopCharging affect censor reason and prevent generic gap/shortfall labels, but cannot erase independent hard fault evidence. |
| E11 | Table-68 `DECODE_ERROR` pseudo-family | **Partially implemented; current bound rejected** | Voltage 0–1000 V and SOC 0–100 checks produce quality flags and invalidate precharge comparison. The proposed 0–400 A bound was tested and rejected for this DIN fleet: 436 otherwise-valid holdout sessions advertise 401–901 A EV maxima. Remaining-time checks stay blocked until the extracted unit is resolved. |
| E12 | Never hard-label current shortfall from target alone | **Feature only, by design** | Ground truth still has no target-current shortfall rule. The detector keeps gated/learned current evidence because dual-connector load sharing occurs even when limit flags are unset and regulation tolerance is absent. |

## Reproduction and outputs

```powershell
$env:EV_AI_SESSIONS = 'C:\ev_fleet\sessions'
$env:EV_AI_LABEL_PROFILE = 'strict'
$env:EV_AI_STRICT_ABORT = '1'
python pipeline\relabel.py --workers 8 --out index_strict_pre_review.json

$env:EV_AI_LABEL_PROFILE = 'iso_reviewed'
python pipeline\relabel.py --workers 8 `
  --out index_iso_reviewed.json `
  --all-out index_iso_reviewed_all.json --drop-censored
python benchmark\label_profile_audit.py C:\ev_fleet\sessions `
  results\iso15118_label_profile_impact.json `
  index_strict_pre_review.json
```

The all-session index is the audit trail. The filtered index is the only one
appropriate for scoring. Neither command overwrites the published
`index.json`.
