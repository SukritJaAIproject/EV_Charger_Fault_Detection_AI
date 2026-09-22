# ISO 15118-3 continuation and label-review report

## Outcome

This closes the two items left unfinished in the Claude session **“AI models
for charger fault detection”**:

1. recover the ISO 15118-3 SLAC state machine and timers from legitimate public
   sources, then correct the detector rule; and
2. adjudicate all 34 remaining ground-truth proposals (35 total proposals,
   with the strict-abort proposal already implemented).

Published baseline files and labels were not overwritten. New work is exposed
as separate rule and label profiles.

## ISO 15118-3 evidence recovery

The saved 93-agent research workflow was archived into
`results/iso15118_3_public_sources.json` (SHA-256 of the source workflow:
`4ac9f7e3c7bcc4eba20ccfca8a76c57362bad9100249c6e99b147644ad0cb1a7`).
It contains 42 independently corroborated findings and 45 pending findings.
Sixty-four agents completed; 29 verifier jobs stopped at the Claude weekly
quota. Pending findings were retained but do not set hard detector thresholds.

No pirated or redistributed copy of ISO 15118-3 was used. Values must be
described as public-source, second-hand attributions to the standard, not as a
direct reading of the paid text. Full provenance and URLs are in
`docs/iso15118_3_public_sources.md`.

## The corrected SLAC rule

The old rule waited 10 s after `CM_SLAC_MATCH.REQ` and attached the wrong
normative meaning to that number. Public sources distinguish two clocks:

| Condition | Timer | Hard budget used |
|---|---|---:|
| Match request sent, no confirmation | `TT_match_response=200 ms`, two retries | **600 ms** |
| Attenuation complete, no match/validate request | `TT_EVSE_match_session` | **10 s** |
| Match request sent, no confirmation (fleet policy) | measured operating point | **10 s** |

The 10 s fleet policy remains the default `empirical` arm for exact
reproduction. `normative` uses the 600 ms response/retry budget and the
separate 10 s missing-request clock. `both` evaluates their union. Every rule
is suppressed once this session has produced its own V2G traffic, because the
neighbouring connector shares the PLC medium.

Here `normative` is the profile name, not a conformance-certification claim.
The 600 ms figure is derived from a Table-A.1 transcription that calls
`C_EV_match_retry=2` a retry count. EVerest's current loop interprets the same
constant as two total attempts, so the implementation deliberately uses the
later, conservative three-window budget and retains the disagreement in the
evidence archive.

```powershell
$env:EV_AI_SLAC = '1'
$env:EV_AI_SLAC_RULE_MODE = 'normative'  # empirical | normative | both
python benchmark\project_slac_arm.py C:\ev_fleet\sessions 6
```

## Holdout results under the published labels

The held-out fleet has 8,820 sessions: 957 faulty and 7,863 clean across 45
unseen stations. Scores below retain the published models, split, and labels.

| Detector | Baseline | ISO-2 rules | SLAC empirical 10 s | SLAC normative |
|---|---:|---:|---:|---:|
| TraditionalAI | 68.0 | 69.1 | 77.0 | **77.7** |
| RL | 49.5 | 49.5 | 49.5 | 49.5 |
| AIAgent | 52.2 | 58.8 | 62.3 | **63.0** |
| AgenticAI | 69.9 | 69.9 | 71.0 | **71.5** |
| MultiAgent | 56.3 | 62.5 | 65.7 | **66.4** |

The normative state machine fired on 229 sessions: 221 response-budget
breaches and 8 missing-request breaches. Of these, 170 are labelled
`SLAC_FAILURE`, 51 are labelled clean, and 8 carry another fault family. The
empirical rule fired on 199 sessions, including 161 `SLAC_FAILURE` and 31
clean. The normative rule therefore gains coverage at a modest false-positive
cost rather than simply relabelling the same cases.

The threshold sweep confirms the result is not sensitive around the normative
point: at 0.2, 0.4, 0.6, and 0.8 s the four adopting architectures round to
essentially the same leaderboard scores. `results/slac_wait_sweep.json`
contains every point. AIAgent is exact through the shipped 10 s point by using
the completed replay as its graded-evidence reference; its exploratory points
above 10 s are explicitly marked approximate. All other detector columns are
exact at every point.

The empirical projection was checked session-by-session against the completed
full replay: all 8,820 first-alert times match for all five detectors. AIAgent
uses its completed empirical replay as an exact graded-evidence reference, then
adds an earlier normative hard fire where applicable; the other three rule
adopters are exact `min(baseline, rule_fire)` paths. RL has no rule layer.

## Label-proposal review

All 35 proposals have an explicit disposition in
`docs/iso15118_label_proposal_decisions.md`. The opt-in profile implements the
accepted changes without changing `index.json`:

```powershell
$env:EV_AI_SESSIONS = 'C:\ev_fleet\sessions'
$env:EV_AI_STRICT_ABORT = '1'
$env:EV_AI_LABEL_PROFILE = 'strict'
python pipeline\relabel.py --workers 8 --out index_strict_pre_review.json
$env:EV_AI_LABEL_PROFILE = 'iso_reviewed'
python pipeline\relabel.py --workers 8 `
  --out index_iso_reviewed.json `
  --all-out index_iso_reviewed_all.json --drop-censored
```

### Label lineage audit

The audit uncovered a pre-existing version boundary that must not be hidden:
the immutable published `index.json` is older than the `strict` code present at
hand-off. The latter already contained `NO_POWER_DELIVERED` and stricter SLAC
ownership logic. Recomputing both the backed-up pre-continuation source and the
current `strict` source over all 8,820 sessions produced zero differences in
`faults`, `graceful_close`, or `reached_current_demand`. This continuation did
not create that earlier drift.

| Label snapshot | Scored sessions | Faulty | Clean | Excluded censored |
|---|---:|---:|---:|---:|
| Published `index.json` | 8,820 | 957 | 7,863 | 0 |
| Pre-review `strict` recomputation | 8,820 | 1,326 | 7,494 | 0 |
| `iso_reviewed` scoring index | 8,525 | 1,317 | 7,208 | 295 |

Published → pre-review strict is exactly 360 clean sessions becoming
`NO_POWER_DELIVERED`, nine clean sessions becoming `SLAC_FAILURE`, and four
`SESSION_ABORT` sessions becoming `SLAC_FAILURE`: a net increase of 369 faults
that predates this continuation.

On the same 8,525-session cohort retained by `iso_reviewed`, pre-review strict
has 1,247 faulty and 7,278 clean sessions. The review changes that to 1,317
faulty and 7,208 clean—a net increase of 70 faults after censorship. Its most
material strict → reviewed transitions are:

| Transition | Sessions |
|---|---:|
| clean → censored | 216 |
| clean → `COMM_FREEZE` | 75 |
| `SESSION_ABORT` → censored | 40 |
| `SLAC_FAILURE` → censored | 39 |
| `SESSION_ABORT` → `COMM_FREEZE` | 16 |
| `SESSION_ABORT` → `PROTOCOL_FAILED` | 10 |
| `SLAC_FAILURE` → clean | 9 |
| `PROTOCOL_FAILED` → `COMM_FREEZE` | 6 |
| clean → `ISOLATION_FAULT` | 5 |
| `SLAC_FAILURE` → `SESSION_ABORT` | 4 |
| `SESSION_ABORT` → `EVSE_PROCESSING_STALL` | 3 |

The profile also re-anchored 188 same-family faults, median 40.9 s earlier,
because timer expiry—not the final captured packet—is now the fault time.
Machine-readable counts, transitions, censor reasons, and index hashes are in
`results/iso15118_label_profile_impact.json`.

One proposal was narrowed after measurement: applying the ISO 0–400 A range as
a decoder validity check marked 436 otherwise-valid DIN/high-current sessions
whose advertised EV maximum is 401–901 A. That current check is therefore not
armed. Voltage/SOC quality checks remain; remaining-time validation stays
blocked until the extracted unit is resolved. They produced one non-fault
quality flag on the holdout (`soc=127`) and did not create a fault family.

### Full-fleet reviewed export

The same reviewed relabel completed over all 40,542 sessions on the full fleet.
`index_iso_reviewed_all.json` preserves every decision; the scoring index
`index_iso_reviewed.json` excludes 1,400 censored sessions and therefore has
39,142 rows: 5,892 faulty and 33,250 clean.

| Reviewed outcome | Sessions |
|---|---:|
| clean | 33,250 |
| `NO_POWER_DELIVERED` | 1,694 |
| `PROTOCOL_FAILED` | 1,389 |
| `SLAC_FAILURE` | 914 |
| `SESSION_ABORT` | 705 |
| `COMM_FREEZE` | 462 |
| `EV_ERROR` | 430 |
| `EVSE_FAULT` | 270 |
| `ISOLATION_FAULT` | 17 |
| `EVSE_PROCESSING_STALL` | 11 |
| censored (all-index only) | 1,400 |

The censor reasons are 1,138 non-graceful endings without positive fault
evidence, 132 captures ending before the 20 s setup budget, 84 normal-stop
cases without an observable `SessionStopRes`, and 46 shared-PLC SLAC events
that could not be attributed to one connector. One `DECODE_ERROR` quality flag
was retained without converting it into a fault.

The full-fleet audit is a **published-to-reviewed combined delta**: 2,037
published-clean sessions become faults, six published faults become clean, and
922 same-family fault anchors move earlier by a median 40.932 s. A full-fleet
pre-review strict snapshot was not generated, so these figures include both
the older published-to-strict drift and the review itself. The 8,820-session
holdout audit above is the isolated strict-to-reviewed causal comparison.
Machine-readable full-fleet counts, transitions, hashes, and censor reasons are
in `results/iso15118_label_profile_impact_full.json`; the two exported indexes
are under `G:\ev_charger_ai_data\sessions`.

## Existing models rescored under evolved labels

These are **rescored, not retrained** results. They measure label sensitivity;
they are not a replacement trained-model leaderboard. The pre-review strict
table uses all 8,820 sessions, while the reviewed table uses the 8,525-session
non-censored cohort, so compare them as two label policies rather than a model
upgrade.

### Pre-review strict labels

| Detector | Strict baseline | ISO-2 rules | SLAC empirical | SLAC normative |
|---|---:|---:|---:|---:|
| TraditionalAI | 62.1 | 62.8 | 68.7 | **69.2** |
| RL | 44.5 | 44.5 | 44.5 | 44.5 |
| AIAgent | 46.7 | **61.0** | 54.2 | 54.8 |
| AgenticAI | 66.7 | **69.5** | 67.5 | 67.9 |
| MultiAgent | 60.2 | 65.3 | 67.2 | **67.6** |

### ISO-reviewed labels

| Detector | Reviewed baseline | ISO-2 rules | SLAC empirical | SLAC normative |
|---|---:|---:|---:|---:|
| TraditionalAI | 60.1 | 61.1 | 66.0 | **66.4** |
| RL | 42.3 | 42.3 | 42.3 | 42.3 |
| AIAgent | 48.6 | **61.9** | 54.8 | 55.1 |
| AgenticAI | 59.4 | 62.3 | 65.1 | **65.5** |
| MultiAgent | 61.0 | 65.1 | 67.1 | **67.4** |

Under reviewed labels, normative SLAC recall is 89%, 86%, 90%, and 86% for
TraditionalAI, AIAgent, AgenticAI, and MultiAgent respectively. RL remains 2%
because the controlled experiment intentionally does not add a rule path to
that architecture.

## Verification

- strict ground-truth regressions: 9
- ISO-reviewed ground-truth regressions: 13
- ISO 15118-3 SLAC state-machine regressions: 6
- empirical SLAC backward-compatibility regressions: 3
- pre-continuation backup versus current strict: 0 core-label differences over
  8,820 sessions
- Python compile check covers all modified modules
- fast-inference equivalence remains bit-identical to the reference models
- empirical SLAC projection equals the completed replay on every first-alert
  timestamp
- critical timer and retry claims were rechecked against the current EVerest
  source and the independent public Table-A.1 transcription; their attempt-
  count discrepancy is documented instead of silently resolved

Primary artifacts:

- `results/iso15118_3_public_sources.json`
- `results/slac_wait_sweep.json`
- `results/slac_projection_normative.json`
- `results/slac_projection_normative_index_iso_reviewed.json`
- `results/iso15118_label_profile_impact.json`
- `results/iso15118_label_profile_impact_full.json`
- `results/rescored_strict_pre_review_test.json`
- `results/rescored_iso_reviewed_test.json`
- `results/slac_projection_normative_index_strict_pre_review.json`
