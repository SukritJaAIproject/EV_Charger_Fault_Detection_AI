# รายงานส่งต่องานแบบละเอียด — iMPS Charger Fault Detection

วันที่ตรวจสถานะล่าสุด: 22 กันยายน 2026  
ผู้ส่งต่อ: Codex  
ผู้รับช่วงต่อ: Claude

## 1. ภาพรวมและ mapping ของสองงาน

มี release ที่เกี่ยวข้องสองชุด แต่ไม่ได้เป็นโปรแกรมคนละฟีเจอร์โดยสิ้นเชิง ทั้งคู่พัฒนาจาก codebase เดียวกันและใช้ชื่อผลิตภัณฑ์ `iMPS Fault Detection` เหมือนกัน

| งาน/แชต | Release | Snapshot/โมเดล | สถานะ |
|---|---:|---|---|
| `สานต่องาน AI ตรวจจับ Charger Fault` / `AI models for charger fault detection` | 1.1.0 | snapshot 12 ก.ย. 2026, artifact `41ded2cdd5c2ba3f` | build Online/Offline สำเร็จ |
| `ต่อยอด AI models for charger fault` / `AI models for charger fault detection 11` | 1.2.0 | benchmark v4 snapshot 21 ก.ย. 2026, artifact `53b6f14244c2e633` | build Online/Offline สำเร็จ และเป็น source ปัจจุบัน |

ข้อควรรู้: `appId = th.co.imps.faultdetection` และ `productName = iMPS Fault Detection` เหมือนกันทั้งสอง release จึงไม่สามารถติดตั้งคู่ขนานบน Windows เป็นสองแอปแยกกันได้ การติดตั้ง 1.2.0 หลัง 1.1.0 จะทำหน้าที่เหมือนอัปเกรด/แทนที่รุ่นเดิม

## 2. สิ่งที่ทำเสร็จแล้ว

### 2.1 Web/dashboard feature

- เพิ่มหน้า `/dashboard/ai/fault-detection`
- UI ไทย/อังกฤษ
- หน้าภาพรวมงานวิจัยและผล benchmark
- รายการสถานี 45 สถานี พร้อมค้นหา เรียงลำดับ และ dialog รายละเอียด
- ตารางเปรียบเทียบ detector 5 แบบ:
  - Traditional AI
  - RL / DQN
  - AI Agent
  - Agentic AI
  - Multi-Agent
- แสดง profile/fault family และ policy ที่เกี่ยวข้องกับ ISO 15118 และ SLAC
- glossary และคำอธิบาย fault
- workflow วิเคราะห์ `.pcap`/`.pcapng` ขนาดไม่เกิน 256 MiB
- แสดง verdict, confidence, fault family, evidence, probable cause, stop-party attribution, per-session details และ warnings

### 2.2 Backend/API สำหรับ PCAP jobs

- เพิ่ม router `backend/routers/fault_detection.py`
- เพิ่ม job service `backend/services/fault_detection_jobs.py`
- ต่อ router เข้ากับ `backend/main.py`
- รองรับ upload, status/result และ lifecycle ของงานวิเคราะห์
- ฝั่ง desktop ใช้ loopback-only runtime และอนุญาตเฉพาะ web origin ที่จับคู่กัน
- ประมวลผล PCAP ทีละงาน
- ลบ raw capture และ telemetry ชั่วคราวหลังสำเร็จหรือล้มเหลว
- เก็บ job-result ขนาดเล็กไว้เพื่อ traceability และหมดอายุใน 30 วัน

### 2.3 Windows desktop runtime

- Electron shell
- production Next.js standalone server
- Python sidecar แบบ PyInstaller one-folder
- NumPy-only inference สำหรับ LSTM autoencoder และ GRU; ไม่ ship PyTorch
- bundled Wireshark/TShark 4.4.6
- bundled dsV2Gshark 1.5.1
- bundled Microsoft Visual C++ x64 runtime DLLs
- random loopback ports ตอนเริ่มโปรแกรม
- runtime log อยู่ที่ `%APPDATA%\iMPS Fault Detection\logs\desktop-runtime.log`
- job records อยู่ที่ `%APPDATA%\iMPS Fault Detection\pcap-jobs`

### 2.4 Installer

สร้าง Windows x64 installers ครบทั้งสองรูปแบบสำหรับ 1.1.0 และ 1.2.0

- Offline Setup: รวม application payload ทั้งหมด ใช้ติดตั้งและใช้งานแบบออฟไลน์ได้
- Online Setup: bootstrapper ขนาดเล็ก ดาวน์โหลด version-matched `.nsis.7z` ผ่าน HTTPS และตรวจ hash ก่อนติดตั้ง

เครื่องปลายทางไม่ต้องติดตั้ง Node.js, Python, Conda, PyTorch, Wireshark, Npcap หรือ MongoDB

### 2.5 Benchmark v4

- resume wrapper ทำงานจนเสร็จสมบูรณ์
- ไม่เหลือ process `resume_v4.ps1`
- สำเร็จตั้งแต่ attempt 1/3 สำหรับ benchmark และ 1/2 สำหรับ analysis
- ไม่มี `resume_v4.failed.txt`
- `records_test.json` มี 8,820 records
- `leaderboard_test.json` มี 5 detectors
- `analysis_test.json` อ่านได้และมีทั้ง `overall` และ `by_source`
- checkpoints 91 ไฟล์ รวม 5,466,643 bytes
- ประมวลผล 90 connectors / 8,820 sessions ด้วย 18 workers
- elapsed จริงของ benchmark ประมาณ 347.2 นาที หรือ 5 ชม. 47 นาที

## 3. ฟีเจอร์ที่เหมือนกันระหว่าง 1.1.0 กับ 1.2.0

จากการตรวจ packaged artifacts พบว่า UI bundle, Electron entry, Python runtime entry และ flow หลักเหมือนกัน โดยหลักฐาน hash ที่ตรวจได้คือ

| ส่วน | SHA-256 ที่เหมือนกัน |
|---|---|
| Fault Detection client bundle | `5A66CD1BC7CF7822910C8E08FBA5FCFA9DF08BE24CEC86C5F51D369BA37A1CA7` |
| Server page | `21F2180CA4F8C06FACC04A96CEB505FB92E8214C457259F1D830A66415A497BC` |
| Electron main | `CC539182C71F9917B9BEF72EB6AB0544196BB74E8DA5D59F69E0B97BDCAA56E7` |
| Python runtime entry | `A5EBD16923C275B96F79EC8C69D026380711A9F2A267279CD4D34C90FB1F6E5B` |

ทั้งสองชุดมี 54 routes, 429 Python modules และ TShark payload 1,343 files เท่ากัน ฟีเจอร์สำหรับผู้ใช้จึงเหมือนกันโดยสาระ

## 4. ความแตกต่างระหว่าง 1.1.0 กับ 1.2.0

### 4.1 Dataset และ label distribution

| รายการ | 1.1.0 | 1.2.0 |
|---|---:|---:|
| Snapshot time | 2026-09-12T00:52:33Z | 2026-09-21T08:11:19Z |
| Test sessions | 8,820 | 8,820 |
| Faulty | 957 | 1,326 |
| Normal/Clean | 7,863 | 7,494 |
| Stations | 45 | 45 |
| Fault families | 6 | 7 |
| เพิ่ม `NO_POWER_DELIVERED` | ไม่มี | 360 sessions |

1.2.0 เพิ่ม/แก้ label โดยเฉพาะ `NO_POWER_DELIVERED` ทำให้จำนวน faulty เพิ่ม 369 sessions แม้จำนวน test sessions รวมยังเท่าเดิม ผลสรุประดับสถานีเปลี่ยน 43 จาก 45 สถานี

### 4.2 Model artifacts

สถาปัตยกรรม inference เหมือนกัน: LSTM-AE ใช้ 33 features และ GRU ใช้ 8 inputs แต่ weights/thresholds ถูกสร้างใหม่ทั้งหมด

| รายการ | 1.1.0 | 1.2.0 |
|---|---|---|
| Artifact version | `41ded2cdd5c2ba3f` | `53b6f14244c2e633` |
| LSTM-AE SHA-256 | `65a0932737118bf01a161cc86c5cdb212821f67094117e779f76a85871f13e92` | `937118cc1e8ad3b2bfb95d54b59ecd77b17a23c57282f4f0ee007db450ccf74d` |
| GRU SHA-256 | `cf4898a01ac9d1b83dc0d8d4aaf7eee706631d1e9a6753d7d758623c02a5850b` | `1abb39c5b8d7f6bcc7447f4eff9096c3aafd5949755313528cb7c20ee51e4cb2` |

model snapshots ของทั้งสองรุ่นถูก extract ไว้ใน `model_snapshots/v1.1.0` และ `model_snapshots/v1.2.0` แล้ว

### 4.3 ผล benchmark และอันดับ

1.1.0:

- Agentic AI อันดับ 1 score 69.943, recall 90.700%, FAR 34.809%
- Traditional AI อันดับ 2 score 68.014
- Multi-Agent อันดับ 3 score 56.322
- AI Agent อันดับ 4 score 52.204
- RL / DQN อันดับ 5 score 49.500

1.2.0:

| Rank | Detector | Score | Recall | FAR | TP | Miss | FP |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Traditional AI | 69.562 | 82.504% | 24.486% | 1,094 | 204 | 1,835 |
| 2 | Agentic AI | 66.854 | 85.143% | 31.011% | 1,129 | 149 | 2,324 |
| 3 | Multi-Agent | 60.158 | 70.136% | 25.033% | 930 | 328 | 1,876 |
| 4 | AI Agent | 46.418 | 49.321% | 34.975% | 654 | 536 | 2,621 |
| 5 | RL / DQN | 39.224 | 18.477% | 5.591% | 245 | 1,035 | 419 |

ข้อสรุปของ 1.2.0:

- Traditional AI ชนะคะแนน composite เพราะสมดุล recall/FAR/earliness ดีที่สุด
- Agentic AI มี recall สูงสุดและ miss ต่ำสุด เหมาะกับ interactive diagnostic workflow เพราะให้ evidence และ probable cause เพิ่มเติม
- RL มี FAR ต่ำสุด แต่ recall ต่ำมาก
- Multi-Agent เด่นที่ `NO_POWER_DELIVERED` recall 92.778% แต่ต่ำที่ `SLAC_FAILURE`
- Agentic AI เด่นที่ `SLAC_FAILURE` recall 88.186%

การใช้ Agentic AI ในหน้า Analyze PCAP แม้ Traditional AI ชนะคะแนนรวมเป็นการตัดสินใจโดยเจตนา: interactive workflow ต้องการ evidence/probable cause ไม่ใช่เพียงคะแนน benchmark สูงสุด

## 5. ผล benchmark v4 แยกตาม fault family

| Family | N | Traditional | RL | AI Agent | Agentic | Multi-Agent |
|---|---:|---:|---:|---:|---:|---:|
| PROTOCOL_FAILED | 310 | 1.000 | 0.329 | 1.000 | 1.000 | 1.000 |
| SESSION_ABORT | 230 | 0.813 | 0.291 | 0.243 | 0.735 | 0.352 |
| SLAC_FAILURE | 237 | 0.249 | 0.101 | 0.000 | 0.882 | 0.068 |
| EVSE_FAULT | 93 | 1.000 | 0.075 | 1.000 | 1.000 | 1.000 |
| NO_POWER_DELIVERED | 360 | 0.969 | 0.094 | 0.281 | 0.700 | 0.928 |
| EV_ERROR | 91 | 1.000 | 0.099 | 1.000 | 1.000 | 1.000 |
| COMM_FREEZE | 5 | 1.000 | 0.400 | 0.600 | 1.000 | 1.000 |

ผลแยกตาม source:

| Source | Faulty | Clean | Total | Winner | Score |
|---|---:|---:|---:|---|---:|
| legacy | 336 | 2,099 | 2,435 | Traditional AI | 72.327 |
| main | 846 | 4,767 | 5,613 | Traditional AI | 69.908 |
| v2g2024 | 96 | 263 | 359 | Agentic AI | 75.759 |
| v2g2025 | 48 | 365 | 413 | Agentic AI | 61.122 |

warning ที่พบมีเพียง NumPy `RuntimeWarning: overflow encountered in exp` ใน sigmoid ที่ `models/fast_infer.py` บรรทัด 259, 260 และ 262 จำนวนสองชุด ไม่ทำให้ benchmark ล้มและผลถูกเขียนครบ ไม่มี final error

## 6. Installer artifacts และ checksum

### Release 1.1.0

| File | Bytes | SHA-256 |
|---|---:|---|
| `iMPS-Fault-Detection-Offline-Setup-1.1.0.exe` | 231,942,830 | `E613206FA11B407C4F53DC4E7859ADA84B3A644A691F397764F9DE6E4140C9CB` |
| `iMPS-Fault-Detection-Online-Setup-1.1.0.exe` | 697,502 | `ECEA47BA1E6BBB6D7C73FAE19821EE465DADBB459935456073D0A7E02C661769` |
| `material-tailwind-dashboard-nextjs-pro-1.1.0-x64.nsis.7z` | 231,613,206 | `CBC5E382084159CA8E1A98ADCDE5BC17FDDC21C8CCD195ABD7A954C07E3D7915` |

### Release 1.2.0

| File | Bytes | SHA-256 |
|---|---:|---|
| `iMPS-Fault-Detection-Offline-Setup-1.2.0.exe` | 231,945,028 | `5971EE4BEA545F5B7E9C3937FF8413C1975CE31791CD52E64EA8D4ADE618D210` |
| `iMPS-Fault-Detection-Online-Setup-1.2.0.exe` | 697,407 | `58369291F583C71C91F17718246B0DD404523907FD18C53B90BA4DD875B88744` |
| `material-tailwind-dashboard-nextjs-pro-1.2.0-x64.nsis.7z` | 231,615,367 | `A67DCA7E45C0E7DA1729F3DAA08BB13BDD9C5D2B96A3DEC930282265BC91CA37` |

ไฟล์ `.blockmap`, `release-manifest.json`, `SHA256SUMS.txt` และ `builder-debug.yml` รวมอยู่ในแต่ละโฟลเดอร์ release

## 7. ประเด็นสำคัญที่ยังต้องทำ

### P0 — Online installer ยังดาวน์โหลด payload ไม่ได้

URL ที่ฝังใน manifest ตอบ 404 ณ 22 ก.ย. 2026:

- `https://github.com/muffinyyss/IMPS-Project/releases/download/imps-fault-detection-v1.1.0/material-tailwind-dashboard-nextjs-pro-1.1.0-x64.nsis.7z`
- `https://github.com/muffinyyss/IMPS-Project/releases/download/imps-fault-detection-v1.2.0/material-tailwind-dashboard-nextjs-pro-1.2.0-x64.nsis.7z`

ต้องสร้าง GitHub Release tags `imps-fault-detection-v1.1.0` และ `imps-fault-detection-v1.2.0` แล้ว upload payload โดยห้ามเปลี่ยนชื่อ จากนั้นทดสอบ URL และ Online Setup จริง เครื่องที่ติดตั้งต้องเข้าถึง URL ผ่าน HTTPS ได้

### P1 — Commit/clean working tree

source ปัจจุบันยังเป็น working tree ที่มี modified/untracked files และยังไม่ได้ commit งาน fault-detection ทั้งชุด Base commit คือ:

`1245598fce27a6cc8d3706da523269ca68a5c8fb` (`update`, 2026-08-12)

ควร review diff, แยก commit ตามหมวด (feature/backend/desktop packaging/docs) และหลีกเลี่ยงการ commit secrets หรือ build cache

### P1 — ตัดสินใจเรื่อง coexistence/version policy

หากต้องการเก็บสองโปรแกรมพร้อมกัน ต้องเปลี่ยนอย่างน้อย `appId`, `productName`, shortcut name, app-data path และ artifact naming ของหนึ่งสายงาน แต่หาก 1.2.0 เป็น successor ของ 1.1.0 พฤติกรรม overwrite ปัจจุบันถูกต้องกว่า

### P1 — Release QA ก่อนแจกจริง

- ตรวจ Windows SmartScreen/code signing policy
- ทดสอบ install/uninstall บน Windows x64 เครื่องสะอาด
- ทดสอบ path ที่มีอักษรไทย/space
- ทดสอบ known-fault PCAP และ healthy PCAP
- ทดสอบ Online Setup หลัง upload payload
- ตรวจ GPL/source-offer obligations สำหรับ Wireshark/dsV2Gshark ตาม `desktop/licenses/THIRD_PARTY_NOTICES.md`

### P2 — Numerical warning

อาจปรับ sigmoid ใน `fast_infer.py` ให้ clamp input ก่อน `exp` เพื่อลด overflow warning แต่ต้อง regression-test ผล inference และ benchmark ก่อนเปลี่ยน เพราะ warning ปัจจุบันไม่ทำให้ผลผิดพลาดหรือรันล้ม

## 8. Source layout สำหรับทำต่อ

แพ็กเกจ `source/current_working_tree` เป็น snapshot เฉพาะไฟล์ที่เพิ่ม/แก้สำหรับงานนี้ ไม่ใช่ clone เต็ม repository โดยไฟล์หลักคือ

- `src/app/dashboard/ai/fault-detection/*` — UI, research dashboard, station dialog, glossary, API client และ tests
- `backend/routers/fault_detection.py` — API router
- `backend/services/fault_detection_jobs.py` — job orchestration
- `desktop/electron/main.cjs` — Electron main process
- `desktop/runtime/*` — standalone inference sidecar
- `desktop/scripts/*` — prepare/build/bundle scripts
- `desktop/export_summary.py` — export benchmark summary สำหรับ UI
- `desktop/README.md` — build/install/runbook
- `package.json`, `package-lock.json`, `next.config.js` — desktop packaging configuration

full repository ปัจจุบันอยู่ที่:

`C:\Users\user1\Documents\GitHub\IMPS-Project`

## 9. วิธี build รุ่น 1.2.0 ปัจจุบัน

Prerequisites: Windows, Node.js/npm, Python + NumPy + PyInstaller, model-conversion environment, Wireshark + dsV2Gshark และ Visual Studio Build Tools/VC++ x64 redist

```powershell
cd C:\Users\user1\Documents\GitHub\IMPS-Project\iMPS_platform
npm install --legacy-peer-deps
npm run desktop:build:offline

$env:IMPS_ONLINE_PACKAGE_URL = `
  "https://github.com/muffinyyss/IMPS-Project/releases/download/imps-fault-detection-v1.2.0/material-tailwind-dashboard-nextjs-pro-1.2.0-x64.nsis.7z"
npm run desktop:build:online
```

สร้างทั้งสองแบบในรอบเดียวด้วย `npm run desktop:build` หลังตั้ง `IMPS_ONLINE_PACKAGE_URL`

optional path overrides:

- `PYTHON`
- `IMPS_MODEL_PYTHON`
- `IMPS_MODEL_SOURCE`
- `IMPS_FAULT_DATA_ROOT`
- `IMPS_WIRESHARK_SOURCE`
- `IMPS_VC_RUNTIME_SOURCE`
- `IMPS_GOLDEN_PCAP`

runtime smoke test:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\desktop\runtime\smoke_runtime.ps1
```

packaged app smoke test:

```powershell
& ".\dist-desktop\release-v1.2.0\win-unpacked\iMPS Fault Detection.exe" --smoke-test
```

expected known-fault result: `fault_detected / PROTOCOL_FAILED`, 1,106 events, 1 session, artifact `53b6f14244c2e633`; healthy reference: `no_fault_detected`, 534 events, 1 session

## 10. Benchmark source/data locations

source snapshot:

`F:\pcap_downloads\ev_charger_ai_v4_original_snapshot`

data/results root:

`G:\ev_charger_ai_data_v4`

important outputs:

- `G:\ev_charger_ai_data_v4\results\records_test.json`
- `G:\ev_charger_ai_data_v4\results\leaderboard_test.json`
- `G:\ev_charger_ai_data_v4\results\analysis_test.json`
- `G:\ev_charger_ai_data_v4\logs\resume_v4.complete.json`
- `G:\ev_charger_ai_data_v4\checkpoints_original_v4`

raw files ที่ไม่รวมใน ZIP เพราะขนาดใหญ่มาก:

| File | Approx. size |
|---|---:|
| `train_X.npy` | 46.35 GB |
| `train_t.npy` | 2.81 GB |
| `train_sid.npy` | 1.40 GB |
| `train_v2g.npy` | 0.35 GB |
| `test_X.npy` | 13.10 GB |
| `test_t.npy` | 0.79 GB |
| `test_sid.npy` | 0.40 GB |
| `test_v2g.npy` | 0.10 GB |

ไฟล์ metadata, benchmark source, artifacts, checkpoints, logs และ result JSON ถูกรวมใน handoff ZIP แล้ว

## 11. หลักฐาน integrity ที่สำคัญ

- source snapshot/run competition SHA-256: `B0EC6A78BFD3DFB9FAC50EF5E69BB2D164E5F87A859282DBE0941FE6A062304D`
- `records_test.json`: `640D43265F1D1AAB895AC7365C5FA4D16443F72DBBAA09F724207365E7F7A8BD`
- `leaderboard_test.json`: `50BDFE55C925DBD99117DA8A31B432443978E2AC7E0564DB68D903FC4F875938`
- `analysis_test.json`: `0E2D097234BECD6345827BEDF762E67F1A23E95CF13366955EB9540D4B377E96`
- `resume_v4.complete.json`: `5D62DF10E2578845454A69A292C5A3146321B213DF84D45C9105B78B2B5D89FB`

ใช้ `SHA256SUMS.txt` ที่ root ของ handoff package เพื่อตรวจทุกไฟล์ใน ZIP

## 12. ข้อสรุปสำหรับผู้รับช่วง

งานหลักเสร็จแล้วทั้ง feature, desktop runtime, offline/online packaging, benchmark v4 และรายงานเปรียบเทียบ รุ่น 1.2.0 คือรุ่นล่าสุดที่อัปเดต dataset/model และสรุปผลแล้ว งานที่ควรทำต่อทันทีคือ upload payload ของ Online Setup ไปยัง GitHub Releases, ทดสอบ online install จริง, ทำ clean-machine release QA และ commit source ที่ยังค้างอยู่ โดยไม่ต้อง rerun benchmark v4

