# iMPS Fault Detection for Windows

The desktop edition is distributed as two Windows x64 installers:

- **Offline Setup** packages the complete verified application and does not need
  internet access during installation or use.
- **Online Setup** is a small bootstrapper. It downloads the version-matched app
  payload over HTTPS, verifies the payload hash embedded at build time, and then
  installs the same offline-capable application.

A target computer does not need Node.js, Python, Conda, PyTorch, Wireshark,
Npcap, or MongoDB.

## Install and use

1. Run either `iMPS-Fault-Detection-Offline-Setup-1.2.0.exe` or
   `iMPS-Fault-Detection-Online-Setup-1.2.0.exe`.
2. Open **iMPS Fault Detection** from the Desktop or Start menu.
3. Select **วิเคราะห์ PCAP / Analyze PCAP**.
4. Choose a `.pcap` or `.pcapng` file up to 256 MiB and select
   **เริ่มวิเคราะห์ด้วย AI / Analyze with AI**.

The app shows the verdict, confidence, fault family, packet evidence, stop-party
analysis, and per-session details. It also includes the fleet and per-station
fault summaries from the audited benchmark snapshot.

## What is bundled

- Electron and a production Next.js standalone server
- The completed v4 45-station benchmark snapshot (8,820 held-out sessions)
- A PyInstaller one-folder Python sidecar
- NumPy-only LSTM-AE and GRU forecasting model artifacts; Torch is not shipped
- Wireshark/TShark 4.4.6 and dsV2Gshark 1.5.1
- App-local Microsoft Visual C++ x64 runtime DLLs

Electron allocates random loopback ports at launch. The sidecar accepts only the
matching local web origin and processes one PCAP job at a time. Uploaded raw
captures and extracted telemetry are removed after completion or failure. Small
job-result records are retained for traceability and expire after 30 days under:

```text
%APPDATA%\iMPS Fault Detection\pcap-jobs
```

Runtime logs are written to:

```text
%APPDATA%\iMPS Fault Detection\logs\desktop-runtime.log
```

## Build the installers

Build prerequisites on Windows are Node.js/npm, Python with NumPy and
PyInstaller, the audited `ev_ai` model-conversion environment, Wireshark with
dsV2Gshark, and Visual Studio Build Tools with an x64 `VC\Redist` directory.

```powershell
npm install --legacy-peer-deps
npm run desktop:build:offline

$env:IMPS_ONLINE_PACKAGE_URL = `
  "https://downloads.example.org/imps/1.2.0/material-tailwind-dashboard-nextjs-pro-1.2.0-x64.nsis.7z"
npm run desktop:build:online
```

`desktop:build` performs all of the following before creating the NSIS package:

1. converts the two Torch checkpoints to safe non-pickle NPZ artifacts;
2. builds the Python sidecar;
3. copies and validates portable TShark, dsV2Gshark, and app-local VC++ DLLs;
4. decodes the golden capture and verifies the expected V2G messages;
5. exports and validates the benchmark summary;
6. runs the packaged inference runtime against the golden PCAP;
7. builds the production Next.js dashboard and NSIS installer.

Optional build-path overrides:

```text
PYTHON
IMPS_MODEL_PYTHON
IMPS_MODEL_SOURCE
IMPS_FAULT_DATA_ROOT
IMPS_WIRESHARK_SOURCE
IMPS_VC_RUNTIME_SOURCE
IMPS_GOLDEN_PCAP
```

To create both variants in one run, set `IMPS_ONLINE_PACKAGE_URL` and run
`npm run desktop:build`. The URL must be the full final HTTPS URL of the x64
`.nsis.7z` payload, not just a directory. Upload that payload without renaming it.

The release artifacts are written under `dist-desktop\release`:

```text
dist-desktop\release\iMPS-Fault-Detection-Offline-Setup-1.2.0.exe
dist-desktop\release\iMPS-Fault-Detection-Online-Setup-1.2.0.exe
dist-desktop\release\material-tailwind-dashboard-nextjs-pro-1.2.0-x64.nsis.7z
dist-desktop\release\release-manifest.json
dist-desktop\release\SHA256SUMS.txt
```

The payload must be hosted before distributing Online Setup. `SHA256SUMS.txt`
is for release verification; Online Setup independently enforces the SHA-512
hash embedded by electron-builder. The two installers install the same local
application—"online" describes the installation transport, not a different app
mode or an auto-update service.

## Verification

Run the packaged sidecar against both the known-fault and healthy reference
captures:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\desktop\runtime\smoke_runtime.ps1
```

The expected golden result is `fault_detected / PROTOCOL_FAILED`, 1,106 events,
one session, and model artifact `53b6f14244c2e633`. The healthy reference must
return `no_fault_detected`, 534 events, and one session.

## v4 model policy

The v4 held-out benchmark ranks Traditional AI first by the composite score
(69.562), while Agentic AI has the highest fault recall (85.1%). The interactive
PCAP workflow continues to use Agentic AI because it returns diagnostic evidence
and probable-cause context in addition to the alert. The research dashboard shows
all five detectors and identifies Traditional AI as the overall benchmark winner;
the two roles are intentionally distinct rather than presenting Agentic AI as the
top composite-score model.

To verify a packaged desktop directory without opening a window, run its main
executable with `--smoke-test`. The process exits successfully only after both
the inference health check and the embedded Next.js page are ready:

```powershell
& ".\dist-desktop\win-unpacked\iMPS Fault Detection.exe" --smoke-test
```

## Third-party distribution

The installer retains upstream Wireshark and dsV2Gshark licenses and notices.
Anyone distributing the installer must also satisfy the corresponding-source
requirements for the exact GPL Wireshark binaries being shipped. See
`desktop\licenses\THIRD_PARTY_NOTICES.md`.

The legacy `Start-iMPS-FaultDetection.ps1` launcher remains available for local
development against the external Conda environment. It is not used by the
standalone installer.
