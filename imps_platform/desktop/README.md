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

1. Run either `iMPS-Fault-Detection-Offline-Setup-1.2.2.exe` or
   `iMPS-Fault-Detection-Online-Setup-1.2.2.exe`.
2. Open **iMPS Fault Detection** from the Desktop or Start menu.
3. Select **วิเคราะห์ PCAP / Analyze PCAP**.
4. Choose a `.pcap` or `.pcapng` file up to 256 MiB and select
   **เริ่มวิเคราะห์ด้วย AI / Analyze with AI**.

The app shows the verdict, confidence, fault family, packet evidence, stop-party
analysis, and per-session details. It also includes the fleet and per-station
fault summaries from the audited benchmark snapshot.

The hero of the dashboard names the running edition (product name and version),
the model artifact and the benchmark snapshot date, all reported by the sidecar's
`/health`; the Overview tab starts with the benchmark that is bundled with that
build (`data\summary.json`), so two editions with different models show
different rankings there. The research panel below it is a fixed research
snapshot that is identical in every edition.

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

(For another edition the folder is named after its product name, e.g.
`%APPDATA%\iMPS Fault Detection Snapshot 2026-09-12`.)

## Build the installers

Build prerequisites on Windows are Node.js/npm, Python with NumPy and
PyInstaller, the audited `ev_ai` model-conversion environment, Wireshark with
dsV2Gshark, and Visual Studio Build Tools with an x64 `VC\Redist` directory.

```powershell
npm install --legacy-peer-deps
npm run desktop:build:offline

$env:IMPS_ONLINE_PACKAGE_URL = `
  "https://downloads.example.org/imps/1.2.2/material-tailwind-dashboard-nextjs-pro-1.2.2-x64.nsis.7z"
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
dist-desktop\release\iMPS-Fault-Detection-Offline-Setup-1.2.2.exe
dist-desktop\release\iMPS-Fault-Detection-Online-Setup-1.2.2.exe
dist-desktop\release\material-tailwind-dashboard-nextjs-pro-1.2.2-x64.nsis.7z
dist-desktop\release\release-manifest.json
dist-desktop\release\SHA256SUMS.txt
```

The payload must be hosted before distributing Online Setup. `SHA256SUMS.txt`
is for release verification; Online Setup independently enforces the SHA-512
hash embedded by electron-builder. The two installers install the same local
application—"online" describes the installation transport, not a different app
mode or an auto-update service.

### Editions (side-by-side installs)

Product identity comes from `package.json` (`build.productName`, `build.appId`)
and can be overridden per build, so a second edition installs next to the
current line as its own Windows application with its own install folder,
shortcuts, uninstall entry and `%APPDATA%` folder:

| Variable | Effect |
|---|---|
| `IMPS_PRODUCT_NAME` | Product name: window title, shortcuts, `<name>.exe`, `%APPDATA%\<name>`, and the artifact names `<slug>-Offline-Setup-<version>.exe` / `<slug>-Online-Setup-<version>.exe` |
| `IMPS_APP_ID` | Windows App ID (uninstall entry and NSIS registry keys). Two editions must differ here, otherwise installing one replaces the other |
| `IMPS_APP_VERSION` | The edition's own version (asar `package.json`, `app.getVersion()`, artifact names); `package.json` stays at the current line's version |
| `IMPS_RESOURCES_ROOT` | Package a staged `resources` directory (`app`, `data\summary.json`, `runtime`, `models`) instead of `.desktop-build` |
| `IMPS_ICON_DIR` | The edition's artwork, `desktop\icons\<edition>`: `icon.ico` becomes the exe, installer and uninstaller icon, `icon.png` the window/taskbar icon (`resources\icon.png`) |

Published editions:

| Edition | Product name | App ID | Version |
|---|---|---|---|
| Current line (blue icon) | `iMPS Fault Detection` | `th.co.imps.faultdetection` | 1.2.2 (v4 benchmark, artifact `53b6f14244c2e633`) |
| Snapshot 2026-09-12 (amber icon) | `iMPS Fault Detection Snapshot 2026-09-12` | `th.co.imps.faultdetection.snapshot20260912` | 1.1.2 (artifact `41ded2cdd5c2ba3f`: the frozen 1.1.0 models and data with the current dashboard) |

Each edition has its own icons (`desktop\icons\<edition>`, generated by
`desktop\icons\make_edition_icons.py`: plate colour = edition) for the exe,
installers, taskbar and browser tab, and the dashboard sets the browser-tab
title from the running edition (`/health` product name and version), e.g.
`iMPS Snapshot 2026-09-12 v1.1.2 - Fault Detection`. Inside the app window the
title bar shows the product name.

Every edition is packaged from a staged resources directory
(`desktop\scripts\stage-edition-resources.ps1`): the dashboard and sidecar
from `npm run desktop:prepare` (`.next-desktop\standalone`,
`.desktop-build\runtime`), the edition's own `data\summary.json` and `models\`,
and its favicon copied over `app\public\img\favicon.png` (the Next app is shared
by all editions, and electron-builder copies extra resources concurrently, so
the favicon cannot be overridden by a second resource entry). The snapshot
edition uses the frozen 1.1.0 summary and models (artifact `41ded2cdd5c2ba3f`,
kept outside the repository):

```powershell
npm run desktop:prepare
powershell -NoProfile -ExecutionPolicy Bypass -File desktop\scripts\stage-edition-resources.ps1 `
  -Name snapshot -Summary "<frozen>\data\summary.json" -Models "<frozen>\models" `
  -IconDir desktop\icons\snapshot -ExpectedArtifact 41ded2cdd5c2ba3f
$env:IMPS_PRODUCT_NAME = "iMPS Fault Detection Snapshot 2026-09-12"
$env:IMPS_APP_ID = "th.co.imps.faultdetection.snapshot20260912"
$env:IMPS_APP_VERSION = "1.1.2"
$env:IMPS_RESOURCES_ROOT = "dist-desktop/staging/snapshot/resources"
$env:IMPS_ICON_DIR = "desktop/icons/snapshot"
$env:IMPS_ONLINE_PACKAGE_URL = "https://github.com/SukritJaAIproject/EV_Charger_Fault_Detection_AI/releases/download/imps-fault-detection-v1.1.2/material-tailwind-dashboard-nextjs-pro-1.1.2-x64.nsis.7z"
node desktop/scripts/build-installers.mjs --kind both --output dist-desktop/release-snapshot
```

The current line is staged the same way with `-Name current`,
`-Summary .desktop-build\summary.json -Models .desktop-build\models
-IconDir desktop\icons\current` and `IMPS_ICON_DIR=desktop/icons/current`.

`desktop\electron\main.cjs` reads the product name from the `package.json`
baked into the asar, which is why each edition keeps its own `%APPDATA%` data.

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

For an edition built under another product name, run the same check on its
executable and confirm the identity it reports, e.g. for the snapshot edition:

```powershell
& ".\dist-desktop\release-snapshot\win-unpacked\iMPS Fault Detection Snapshot 2026-09-12.exe" --smoke-test
```

then start it normally and check that `/health` on the API port printed in
`%APPDATA%\<product name>\logs\desktop-runtime.log` reports the expected
`productName`, `appVersion` and `artifactVersion` (`41ded2cdd5c2ba3f` for the
snapshot, `53b6f14244c2e633` for the current line). `Test-Coexistence.ps1`
(public repository, `imps_platform/desktop/signing/`) installs both editions
side by side and verifies they stay distinct.

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

The upstream uninstallers (`uninstall-wireshark.exe`, `unins000.exe` and
`unins000.dat`) are not copied into the portable runtime. They would only offer
to remove the build machine's own Wireshark installation, and the dsV2Gshark
one is the only unsigned executable in the installed tree. Every other file of
the installed Wireshark directory is shipped unchanged.

The legacy `Start-iMPS-FaultDetection.ps1` launcher remains available for local
development against the external Conda environment. It is not used by the
standalone installer.
