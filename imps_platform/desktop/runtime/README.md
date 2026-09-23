# iMPS portable PCAP runtime

This directory builds the Python/TShark sidecar used by the full Windows
desktop edition. The installed runtime needs neither Conda, Torch, sklearn,
nor access to the build machine's `F:`/`G:` drives.

Build from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File desktop\runtime\build_runtime.ps1
```

The build-time `ev_ai` interpreter converts the audited Torch checkpoints to
safe NumPy NPZ files. The runtime Python then packages an onedir executable
with PyInstaller. Outputs consumed by Electron are:

- `.desktop-build/runtime/imps-fault-runtime.exe`
- `.desktop-build/runtime/_internal/`
- `.desktop-build/models/lstm_ae.npz`
- `.desktop-build/models/gru_fore.npz`
- `.desktop-build/models/manifest.json`

Portable Wireshark/TShark is prepared separately at
`.desktop-build/runtime/wireshark/tshark.exe`.

Runtime CLI contract:

```text
imps-fault-runtime.exe serve --host 127.0.0.1 --port PORT \
  --origin http://127.0.0.1:WEB_PORT --summary SUMMARY_JSON \
  --model-dir MODELS --tshark TSHARK_EXE --jobs-root JOBS_DIR \
  [--product-name NAME] [--app-version VERSION]
```

The edition identity is optional: the Electron launcher passes it through the
environment (`IMPS_PRODUCT_NAME`, `IMPS_APP_VERSION`), the flags override it.
`GET /health` reports it together with the bundled model, so the dashboard can
name what is running: `productName`, `appVersion`, `artifactVersion` and
`modelCreatedAt` (from `models/manifest.json`) and `summarySnapshotAt` (from
the summary file); all are `null` when unknown.

Detection policy: the detector runs under the policy its bundled benchmark
was measured with, read from `summary.json` `detectionPolicy.id`
(`detection_policy.py`; absent = `baseline`):

| Policy | Research switches | Meaning |
|---|---|---|
| `baseline` | `EV_AI_ISO=0 EV_AI_ISO_VEC=0 EV_AI_SLAC=0` | fleet-tuned rules only (the published v4 benchmark) |
| `iso15118-standard` | `EV_AI_ISO=1 EV_AI_ISO_VEC=0 EV_AI_SLAC=1 EV_AI_SLAC_RULE_MODE=normative` | ISO 15118-2 rule layer + ISO 15118-3 SLAC timers (600 ms match response, 10 s match session) |

The worker receives the policy as `--detection-policy` (with
`--benchmark-rank`, Agentic AI's rank in the bundled leaderboard), clears any
inherited research switch (`EV_AI_NPD_RULE`, `EV_AI_SLAC_WAIT`, ...), sets the
policy's before importing a detector module and raises if the imported modules
disagree. `EV_AI_ISO_VEC` is always 0: the packaged weights are 33 features wide.
An unknown or malformed policy stops the sidecar at start-up with the reason
in `desktop-runtime.log`. `/health` and every PCAP result report `detectionPolicy`.

The server launches the same executable in `worker` mode for one queued PCAP
at a time. Uploads are limited to 256 MiB, validated by extension and capture
magic, and stored under a random 128-bit job ID. Raw PCAP/telemetry files are
removed when analysis finishes; small result records expire after 30 days.
