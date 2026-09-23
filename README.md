# EV Charger Fault Detection AI

Fault detection for DC EV chargers from raw PLC/V2G packet captures (DIN 70121 / ISO 15118-2), built on the EGAT charging fleet: **212 stations, 40,542 charging sessions, 44,198 captures**. Five detector architectures are trained and scored on the same held-out split; a Windows desktop application ships the winning detectors with a bundled Wireshark/TShark so a technician can analyse a `.pcap` offline.

**Installers (Windows x64):** see [Releases](../../releases) — three editions that install side by side, each as an Offline installer (self-contained, ~231 MB) and an Online installer (700 KB bootstrapper + payload):

| Edition | Release | App ID | Contents |
|---|---|---|---|
| `iMPS Fault Detection` 1.3.0 (current line, blue icon) | `imps-fault-detection-v1.3.0` | `th.co.imps.faultdetection` | benchmark v4 weights, artifact `53b6f14244c2e633`; 45 held-out stations + in-sample results for the 167 training stations |
| `iMPS Fault Detection Snapshot 2026-09-12` 1.1.3 (amber icon) | `imps-fault-detection-v1.1.3` | `th.co.imps.faultdetection.snapshot20260912` | frozen 12 Sep 2026 snapshot, artifact `41ded2cdd5c2ba3f` |
| `iMPS Fault Detection ISO 15118` 1.3.0 (green icon) | `imps-fault-detection-iso15118-v1.3.0` | `th.co.imps.faultdetection.iso15118` | v4 weights run under detection policy `iso15118-standard` (ISO 15118-2 rule layer + ISO 15118-3 SLAC timers, normative). The 8,820-session held-out benchmark was replayed under that policy: Agentic AI 66.9 → 70.9 (recall 85.1% → 92.1%) and Traditional AI 69.6 → 77.3 |

Since 1.2.1 / 1.1.1 the dashboard names the running edition (product, version, model artifact, snapshot date) in its header and opens the Overview with the benchmark bundled in that build. Since 1.2.2 / 1.1.2 each edition also has its own icon (exe, installer, taskbar, browser tab) and a browser-tab title naming the edition. Since 1.3.0 the Stations tab of the current line covers all 212 stations. The 167 training stations are badged *in-sample* and kept out of every benchmark number, and the Overview's numbers and research grid come from the model set the edition ships. Earlier releases stay available.

## Repository layout

| Path | What it is |
|---|---|
| `ev_charger_ai/` | Research code: packet → session pipeline, ground truth, 33-feature tracker, the five detectors, benchmark harness, ISO 15118-2 / SLAC rule layers, analysis scripts, results (`results/*.json`) and trained weights (`artifacts*/`). The 41 GB session/feature data is **not** in the repo. |
| `imps_platform/` | The fault-detection module of the iMPS platform: dashboard page (`src/app/dashboard/ai/fault-detection/`), PCAP job API (`backend/routers/fault_detection.py`, `backend/services/fault_detection_jobs.py`), Windows desktop packaging (`desktop/`), and the commits as `patches/*.patch` for applying onto an iMPS checkout. |
| `docs/` | Hand-off notes and the v1.1 ↔ v1.2 feature-comparison PDF. |

Deep-dive documents live in `ev_charger_ai/docs/`: the ISO 15118-2 experiment (`iso15118_experiment.md`, HTML report `iso15118_ablation_report.html`), the ISO 15118-3 continuation (`iso15118_3_continuation_report.md`, `iso15118_3_public_sources.md`), the 773-rule extraction (`iso15118_rulebook.md`) and the label-proposal decisions.

## Detectors

| Detector | Idea |
|---|---|
| TraditionalAI | fleet-tuned rules + XGBoost horizon model + Isolation Forest |
| RL (DQN) | policy trained on the replay, no rule layer (the control arm) |
| AIAgent | tool-using agent with an evidence board and belief fusion |
| AgenticAI | goal-driven agent with per-station memory and investigations |
| MultiAgent | five specialist agents (power / battery / protocol / comms / standards) with a coordinator |

Scoring per faulty session: on-time detection (first alert ≤ fault + 10 s), lead time, false alarms on clean sessions; `score = 50·recall + 30·(1−FAR) + 20·earliness`.

## Headline results (fleet hold-out: 8,820 sessions, 45 unseen stations)

**Does attaching the ISO 15118-2 standard help?** Three arms on identical sessions, labels and weights.

| Detector | baseline | + ISO 15118-2 rules (773 rules) | + SLAC rule (1 measured rule, ISO 15118-3 territory) |
|---|---:|---:|---:|
| TraditionalAI | 68.0 | 69.1 (+1.1) | **77.0 (+9.0)** |
| AIAgent | 52.2 | 58.8 (+6.6) | **62.3 (+10.1)** |
| MultiAgent | 56.3 | 62.5 (+6.2) | **65.7 (+9.4)** |
| AgenticAI | 69.9 | 69.9 (+0.0) | 71.0 (+1.0) |
| RL | 49.5 | 49.5 (0.0) | 49.5 (0.0) |

- The standard's *rules* lift the evidence-fusing architectures; its *features* lift the pure learner; nothing lifts both. RL's exact 0.0 in the rules arm is the control proving the harness does not leak.
- `SLAC_FAILURE` (23% of faults) is invisible to part 2 — PLC matching is ISO 15118-**3**. One rule measured off the wire (a `CM_SLAC_MATCH.REQ` unanswered while the session has no V2G traffic; healthy matches answer in 7 ms) recovers 72–87% of that family at +0.1–0.2 pp false alarms, and the leaderboard is flat across a 1–45 s threshold sweep. A public-source reconstruction of the ISO 15118-3 timers (600 ms response budget + 10 s match-session timer) scores 77.7 / 63.0 / 71.5 / 66.4.
- Label quality mattered more than the standard: requiring positive evidence for `SESSION_ABORT` removed 141 "faults" that were captures ending at a ring-buffer boundary (−20% of all faults) and changed the ranking on its own.

**Benchmark v4 (labels with `NO_POWER_DELIVERED`, shipped in installer 1.2.0):** 1,326 faulty / 7,494 clean — TraditionalAI 69.6, AgenticAI 66.9 (highest recall 85.1%), MultiAgent 60.2, AIAgent 46.4, RL 39.2. Installer 1.1.0 carries the earlier snapshot (957 faulty; AgenticAI 69.9 leads).

## Reproducing the research

```bash
cd ev_charger_ai
python pipeline/sessionize.py            # captures -> per-session CSV + index.json   (needs the pcaps)
python train/build_dataset.py            # feature matrices
python train/train_traditional.py && python train/train_nn.py && python train/train_rl.py
python benchmark/run_competition.py test # replay the hold-out; EV_AI_CKPT=<dir> checkpoints per connector
python benchmark/compare_arms.py test fleet_baseline,fleet_slac,fleet_iso_rules
```

Arm switches are environment variables: `EV_AI_ISO=1` (ISO 15118-2 rule layer), `EV_AI_ISO_VEC=1` (its 27 features), `EV_AI_SLAC=1` with `EV_AI_SLAC_RULE_MODE=empirical|normative|both`, `EV_AI_LABEL_PROFILE=strict|iso_reviewed`. Data roots are found by folder name (`core/findroot.py`) or overridden with `EV_AI_DATA`, `EV_AI_SESSIONS`, `EV_AI_ARTIFACTS`, `EV_AI_RESULTS`.

## Building the desktop application

Inside an iMPS platform checkout with the patches applied (`git am imps_platform/patches/*.patch`):

```powershell
npm install --legacy-peer-deps
npm run desktop:build:offline                       # Offline installer
$env:IMPS_ONLINE_PACKAGE_URL = "https://github.com/SukritJaAIproject/EV_Charger_Fault_Detection_AI/releases/download/<tag>/<payload>.nsis.7z"
npm run desktop:build:online                        # Online bootstrapper + payload
```

`imps_platform/desktop/README.md` is the full runbook (smoke tests, golden PCAP, known issues). A second edition that installs alongside the current line is built by overriding the product identity (`IMPS_PRODUCT_NAME`, `IMPS_APP_ID`, optionally `IMPS_RESOURCES_ROOT` to re-issue an earlier unpacked build); the *Editions* section there shows the exact recipe used for the Snapshot 2026-09-12 edition.

**Code signing.** Released installers and executables are Authenticode-signed with an internal self-signed certificate (thumbprint `74C4795C67E81EFCCFFAAB2B946661F1003C7A3E`; public `.cer` attached to every release and kept in `imps_platform/desktop/signing/`). Machines that import it into *Trusted Root* and *Trusted Publishers* verify the signature as valid; elsewhere Windows SmartScreen still shows *More info → Run anyway*, because the certificate is not CA-issued. Set `IMPS_SIGN_CERT_SHA1` to sign a build; see `imps_platform/desktop/signing/README.md`.

## Provenance

Research and packaging were carried out with Claude (Anthropic) and Codex (OpenAI) as coding agents between 2026-09-09 and 2026-09-22; every reported number is reproducible from the scripts and result files in this repository. ISO 15118-2:2014 was read from a licensed copy; ISO 15118-3 values come from public secondary sources only and are labelled as such.
